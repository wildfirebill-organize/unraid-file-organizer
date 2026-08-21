"""REST API routes for the organizer."""

import asyncio
import logging
from collections import Counter
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException

from app.core.config import ConfigManager
from app.models.models import (
    ApplyRequest,
    OrganizerConfig,
    PlanResponse,
)
from app.services.organizer import OrganizerService
from app.services.scanner import ScannerService
from app.services.scheduler import ScanScheduler, digest_message
from app.services.notify import Notifier
from app.services.duplicates import DuplicateFinder
from app.services.history import read_history

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

config_manager = ConfigManager()
scanner = ScannerService(config_manager)
organizer = OrganizerService(config_manager)
notifier = Notifier()
scheduler = ScanScheduler(config_manager, scanner)
duplicate_finder = DuplicateFinder(config_manager)


# ---------- Config ----------

@router.get("/config", response_model=OrganizerConfig)
def get_config():
    return config_manager.load()


@router.put("/config", response_model=OrganizerConfig)
def save_config(new_config: OrganizerConfig):
    try:
        return config_manager.update(new_config)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        logger.exception("Config write denied")
        raise HTTPException(
            status_code=500,
            detail=f"Cannot write config file ({config_manager.config_path}): {e}. "
            "Check that the /config volume is writable by the container.",
        )
    except Exception as e:
        logger.exception("Config save failed")
        raise HTTPException(status_code=500, detail=f"Config save failed: {e}")


# ---------- Scan ----------

@router.post("/scan")
def run_scan(max_files: Optional[int] = None):
    result = scanner.scan(max_files=max_files)
    return {
        "started_at": result.started_at,
        "finished_at": result.finished_at,
        "roots_scanned": result.roots_scanned,
        "total_files": result.total_files,
        "errors": result.errors[:20],
        "items": [i.model_dump() for i in result.items],
    }


@router.get("/scan/last")
def last_scan():
    if scanner.last_result is None:
        raise HTTPException(status_code=404, detail="No scan has been run yet")
    r = scanner.last_result
    return {
        "started_at": r.started_at,
        "finished_at": r.finished_at,
        "roots_scanned": r.roots_scanned,
        "total_files": r.total_files,
        "errors": r.errors[:20],
        "items": [i.model_dump() for i in r.items],
    }


# ---------- LLM assist ----------

@router.get("/llm/status")
def llm_status():
    from app.services.llm_classifier import LLMClassifier
    cfg = config_manager.load()
    ok, detail = LLMClassifier().available(cfg)
    return {
        "enabled": cfg.llm_enabled,
        "reachable": ok,
        "url": cfg.ollama_url,
        "model": cfg.ollama_model,
        "detail": detail,
    }


# ---------- Schedule & notifications ----------

@router.get("/schedule/status")
def schedule_status():
    cfg = config_manager.load()
    now = datetime.utcnow()
    next_run = None
    if cfg.schedule_enabled:
        next_run = ScanScheduler.next_run(
            scheduler.last_run, cfg.schedule_interval_hours, now
        ).isoformat()
    return {
        "enabled": cfg.schedule_enabled,
        "interval_hours": cfg.schedule_interval_hours,
        "running": scheduler.running,
        "last_run": scheduler.last_run.isoformat() if scheduler.last_run else None,
        "next_run": next_run,
        "last_digest": scheduler.last_digest,
    }


@router.post("/schedule/run-now")
async def schedule_run_now():
    try:
        digest = await asyncio.to_thread(scheduler.run_scan_once)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return digest


@router.post("/notify/test")
async def notify_test():
    cfg = config_manager.load()
    ok, detail = notifier.send(
        "🗂️ Unraid File Organizer",
        "Test notification — your webhook is working!",
        cfg,
    )
    return {"ok": ok, "detail": detail}


# ---------- History ----------

@router.get("/history")
def get_history(limit: int = 100):
    entries = read_history(limit=limit)
    return [e.model_dump() for e in reversed(entries)]  # newest first


# ---------- Duplicates ----------

@router.post("/duplicates/scan")
async def run_duplicates_scan(max_files: int = 20000):
    report = await asyncio.to_thread(duplicate_finder.find, max_files)
    return report.model_dump()


@router.get("/duplicates/last")
def last_duplicates_report():
    if duplicate_finder.last_report is None:
        raise HTTPException(status_code=404, detail="No duplicate scan has been run yet")
    return duplicate_finder.last_report.model_dump()


class QuarantineRequest(ApplyRequest):
    selected_paths: List[str]


@router.post("/duplicates/quarantine")
async def quarantine_duplicates(request: QuarantineRequest):
    """Move selected duplicate files to the quarantine folder via the journalled engine."""
    import os as _os
    from app.models.models import MoveOperation, PlanResponse

    cfg = config_manager.load()
    dest_dir = "/mnt/user/quarantine/duplicates"
    ops: List[MoveOperation] = []
    for p in request.selected_paths:
        if not _os.path.exists(p):
            continue
        dst = _os.path.join(dest_dir, _os.path.basename(p))
        if _os.path.exists(dst):
            dst = OrganizerService._unique_name(dst, 1)
        ops.append(MoveOperation(
            source=p, destination=dst,
            category="duplicate", intent="data_file", confidence=1.0,
        ))
    plan = PlanResponse(
        operations=ops,
        total_size_bytes=sum(_os.path.getsize(o.source) for o in ops),
        by_category={"duplicate": len(ops)},
        conflicts=0,
    )
    dry_run = request.force_dry_run or cfg.dry_run
    entry = organizer.apply_plan(plan, dry_run=dry_run)
    return {
        "dry_run": dry_run,
        "applied": entry.applied,
        "operations": [op.model_dump() for op in entry.operations],
        "summary": _summarize(entry.operations),
    }


# ---------- Plan / Apply / Undo ----------

@router.post("/plan", response_model=PlanResponse)
def build_plan(selected_sources: Optional[List[str]] = None):
    if scanner.last_result is None:
        raise HTTPException(status_code=404, detail="Run a scan first")
    return organizer.build_plan(scanner.last_result.items, selected_sources)


@router.post("/apply")
def apply_plan(request: ApplyRequest):
    if scanner.last_result is None:
        raise HTTPException(status_code=404, detail="Run a scan first")
    cfg = config_manager.load()
    plan = organizer.build_plan(
        scanner.last_result.items,
        request.selected_sources,
    )
    dry_run = request.force_dry_run or cfg.dry_run
    entry = organizer.apply_plan(plan, dry_run=dry_run)

    moved = sum(1 for o in entry.operations if o.status == "done")
    if entry.applied and moved and cfg.notify_enabled:
        by_cat = Counter(o.category for o in entry.operations if o.status == "done")
        msg = "Applied moves:\n" + "\n".join(
            f"• {c.replace('_', ' ')}: {n}" for c, n in sorted(by_cat.items(), key=lambda kv: -kv[1])
        )
        asyncio.create_task(asyncio.to_thread(
            notifier.send, "🗂️ Unraid Organizer — files moved", msg, cfg
        ))

    return {
        "dry_run": dry_run,
        "applied": entry.applied,
        "operations": [op.model_dump() for op in entry.operations],
        "summary": _summarize(entry.operations),
    }


@router.get("/log")
def get_log(limit: int = 50):
    entries = organizer.read_log(limit=limit)
    return [
        {
            "timestamp": e.timestamp.isoformat(),
            "dry_run": e.dry_run,
            "applied": e.applied,
            "count": len(e.operations),
            "done": sum(1 for o in e.operations if o.status == "done"),
            "skipped": sum(1 for o in e.operations if o.status == "skipped"),
            "errors": sum(1 for o in e.operations if o.status == "error"),
        }
        for e in entries
    ]


@router.post("/undo")
def undo_last():
    return organizer.undo_last()


def _summarize(ops) -> dict:
    statuses = Counter(o.status for o in ops)
    cats = Counter(o.category for o in ops if o.status == "done")
    return {"statuses": dict(statuses), "moved_by_category": dict(cats)}

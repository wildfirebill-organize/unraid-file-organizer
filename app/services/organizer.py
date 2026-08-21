"""Organizer engine — builds a move plan from a scan and executes it safely.

Safety rules enforced here:
- Never touch anything under HARD_FORBIDDEN_PREFIXES or user disallow paths.
- Never overwrite an existing destination file (skip or rename per policy).
- Every applied operation is journaled to /config/operations.log.jsonl for undo.
"""

import json
import logging
import os
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from app.core.config import ConfigManager
from app.models.models import (
    MoveOperation,
    OperationLogEntry,
    PlanResponse,
    ScanResultItem,
)

logger = logging.getLogger(__name__)

LOG_PATH = Path(os.environ.get("ORGANIZER_LOG", "/config/operations.log.jsonl"))


def _norm(p: str) -> str:
    return os.path.normpath(p).rstrip("\\/") or "/"


class OrganizerService:
    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager

    def build_plan(
        self,
        items: List[ScanResultItem],
        selected_sources: Optional[List[str]] = None,
    ) -> PlanResponse:
        cfg = self.config_manager.load()
        disallow = [_norm(dp.path) for dp in cfg.disallow_paths]

        def forbidden(path: str) -> bool:
            p = _norm(path)
            if any(p == d or p.startswith(d + "/") for d in disallow):
                return True
            return ConfigManager.is_forbidden(path)

        ops: List[MoveOperation] = []
        seen_dests: set[str] = set()

        for item in items:
            if selected_sources is not None and item.source_path not in selected_sources:
                continue
            if item.confidence < cfg.min_confidence:
                continue
            if not item.suggested_destination:
                continue
            if forbidden(item.source_path):
                continue

            dest_dir = _norm(item.suggested_destination)
            if forbidden(dest_dir):
                continue

            dest_path = os.path.join(dest_dir, item.filename)

            # Resolve duplicates deterministically before execution
            key = dest_path.lower()
            if key in seen_dests:
                dest_path = self._unique_name(dest_path, 1)
                key = dest_path.lower()
            elif os.path.exists(dest_path):
                if cfg.duplicate_policy == "skip":
                    ops.append(MoveOperation(
                        source=item.source_path, destination=dest_path,
                        category=item.category, intent=item.intent,
                        confidence=item.confidence, status="skipped",
                        error="destination exists",
                    ))
                    continue
                dest_path = self._unique_name(dest_path, 1)
                key = dest_path.lower()

            seen_dests.add(key)
            ops.append(MoveOperation(
                source=item.source_path,
                destination=dest_path,
                category=item.category,
                intent=item.intent,
                confidence=item.confidence,
            ))

        by_category = Counter(op.category for op in ops)
        total_size = sum(
            os.path.getsize(op.source) for op in ops
            if op.status == "pending" and os.path.exists(op.source)
        )
        conflicts = sum(1 for op in ops if op.status == "skipped")

        return PlanResponse(
            operations=ops,
            total_size_bytes=total_size,
            by_category=dict(by_category),
            conflicts=conflicts,
        )

    @staticmethod
    def _unique_name(dest_path: str, attempt: int) -> str:
        base, ext = os.path.splitext(dest_path)
        candidate = f"{base} ({attempt}){ext}"
        while os.path.exists(candidate):
            attempt += 1
            candidate = f"{base} ({attempt}){ext}"
        return candidate

    def apply_plan(
        self,
        plan: PlanResponse,
        dry_run: bool,
    ) -> OperationLogEntry:
        """Execute pending operations. Journals everything for undo."""
        entry = OperationLogEntry(
            timestamp=datetime.utcnow(),
            dry_run=dry_run,
            applied=False,
            operations=[],
        )

        for op in plan.operations:
            if op.status != "pending":
                entry.operations.append(op.model_copy())
                continue

            if dry_run:
                op.status = "pending"  # stays pending; nothing moved
                entry.operations.append(op.model_copy())
                continue

            try:
                src = Path(op.source)
                dst = Path(op.destination)
                if not src.exists():
                    op.status = "skipped"
                    op.error = "source missing"
                elif dst.exists():
                    op.status = "skipped"
                    op.error = "destination appeared during apply"
                else:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(src), str(dst))
                    op.status = "done"
            except Exception as e:
                op.status = "error"
                op.error = str(e)
                logger.exception("Move failed: %s -> %s", op.source, op.destination)

            entry.operations.append(op.model_copy())

        if not dry_run:
            entry.applied = True
            self._journal(entry)

        return entry

    @staticmethod
    def _journal(entry: OperationLogEntry):
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(entry.model_dump_json() + "\n")

    @staticmethod
    def read_log(limit: int = 50) -> List[OperationLogEntry]:
        if not LOG_PATH.exists():
            return []
        entries: List[OperationLogEntry] = []
        with LOG_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(OperationLogEntry(**json.loads(line)))
                except Exception as e:
                    logger.debug("Bad log line skipped: %s", e)
        return entries[-limit:]

    def undo_last(self) -> dict:
        """Reverse the most recent applied operation batch."""
        entries = self.read_log(limit=500)
        last_applied = next((e for e in reversed(entries) if e.applied), None)
        if not last_applied:
            return {"undone": 0, "message": "No applied operations found"}

        undone, errors = 0, []
        for op in reversed(last_applied.operations):
            if op.status != "done":
                continue
            src, dst = Path(op.source), Path(op.destination)
            try:
                if dst.exists():
                    src.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(dst), str(src))
                    undone += 1
            except Exception as e:
                errors.append(f"{op.destination}: {e}")

        return {"undone": undone, "errors": errors}

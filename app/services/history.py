"""Scan history persistence — JSONL journal of scan summaries for the dashboard."""

import json
import logging
import os
from pathlib import Path
from typing import List

from app.models.models import HistoryEntry, ScanResult

logger = logging.getLogger(__name__)

HISTORY_PATH = Path(os.environ.get("ORGANIZER_HISTORY", "/config/scan_history.jsonl"))


def record_history(result: ScanResult, cfg, trigger: str) -> None:
    try:
        movable = [
            i for i in result.items
            if i.confidence >= cfg.min_confidence and i.suggested_destination
        ]
        by_cat = {}
        for i in movable:
            by_cat[i.category] = by_cat.get(i.category, 0) + 1
        entry = HistoryEntry(
            timestamp=result.finished_at or result.started_at,
            trigger=trigger,
            roots_scanned=result.roots_scanned,
            total_files=result.total_files,
            movable_files=len(movable),
            total_size_bytes=sum(i.size_bytes for i in movable),
            by_category=by_cat,
        )
        HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with HISTORY_PATH.open("a", encoding="utf-8") as f:
            f.write(entry.model_dump_json() + "\n")
    except Exception as e:
        logger.warning("Failed to record scan history: %s", e)


def read_history(limit: int = 100) -> List[HistoryEntry]:
    if not HISTORY_PATH.exists():
        return []
    entries: List[HistoryEntry] = []
    with HISTORY_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(HistoryEntry(**json.loads(line)))
            except Exception as e:
                logger.debug("Bad history line skipped: %s", e)
    return entries[-limit:]

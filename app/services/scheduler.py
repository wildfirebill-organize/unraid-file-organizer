"""Background scheduler for automatic dry-run scans.

Scheduled scans NEVER move files — they produce a digest (counts, size,
sample moves) and optionally push it to the configured webhook.
"""

import asyncio
import logging
from collections import Counter
from datetime import datetime, timedelta
from typing import Optional

from app.models.models import ScanResult
from app.services.notify import Notifier

logger = logging.getLogger(__name__)


def build_digest(result: ScanResult, cfg) -> dict:
    """Summarize a scan result into a notification-friendly digest."""
    movable = [
        i for i in result.items
        if i.confidence >= cfg.min_confidence and i.suggested_destination
    ]
    by_category = Counter(i.category for i in movable)
    sample = [
        {"from": i.source_path, "to": f"{i.suggested_destination}{i.filename}"}
        for i in movable[:5]
    ]
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "total_files": result.total_files,
        "movable_files": len(movable),
        "total_size_bytes": sum(i.size_bytes for i in movable),
        "by_category": dict(by_category),
        "sample_moves": sample,
        "roots_scanned": result.roots_scanned,
    }


def digest_message(digest: dict) -> str:
    lines = [
        f"{digest['movable_files']} of {digest['total_files']} files are ready to move "
        f"({digest['total_size_bytes'] / (1024**3):.1f} GB).",
        "",
    ]
    for cat, n in sorted(digest["by_category"].items(), key=lambda kv: -kv[1])[:8]:
        lines.append(f"• {cat.replace('_', ' ')}: {n}")
    if digest["sample_moves"]:
        lines.append("")
        lines.append("Sample moves:")
        for m in digest["sample_moves"][:3]:
            lines.append(f"  {m['from']} → {m['to']}")
    return "\n".join(lines)


class ScanScheduler:
    CHECK_INTERVAL_SECONDS = 60

    def __init__(self, config_manager, scanner):
        self.config_manager = config_manager
        self.scanner = scanner
        self.notifier = Notifier()
        self.last_run: Optional[datetime] = None
        self.last_digest: Optional[dict] = None
        self.running = False

    @staticmethod
    def next_run(last_run: Optional[datetime], interval_hours: int, now: datetime) -> datetime:
        """Pure helper — when the next scan is due."""
        base = last_run or now
        return base + timedelta(hours=interval_hours)

    async def run(self):
        logger.info("Scan scheduler started")
        while True:
            try:
                await asyncio.sleep(self.CHECK_INTERVAL_SECONDS)
                cfg = self.config_manager.load()
                if not cfg.schedule_enabled or self.running:
                    continue
                now = datetime.utcnow()
                due = self.next_run(self.last_run, cfg.schedule_interval_hours, now)
                if now >= due:
                    logger.info("Scheduled scan due — running")
                    await asyncio.to_thread(self.run_scan_once)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Scheduler iteration failed")

    def run_scan_once(self) -> dict:
        """Run a dry-run scan, build digest, notify. Never moves files."""
        if self.running:
            raise RuntimeError("A scheduled scan is already running")
        cfg = self.config_manager.load()
        self.running = True
        try:
            result = self.scanner.scan(trigger="scheduled")
            digest = build_digest(result, cfg)
            self.last_run = datetime.utcnow()
            self.last_digest = digest

            if cfg.notify_enabled:
                ok, detail = self.notifier.send(
                    "🗂️ Unraid Organizer — scheduled scan",
                    digest_message(digest),
                    cfg,
                )
                digest["notified"] = {"ok": ok, "detail": detail}

            logger.info(
                "Scheduled scan complete: %d files, %d movable",
                digest["total_files"], digest["movable_files"],
            )
            return digest
        finally:
            self.running = False

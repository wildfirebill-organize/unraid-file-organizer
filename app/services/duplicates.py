"""Content-aware duplicate finder.

Three-stage pipeline keeps hashing cheap:
  1. group by file size
  2. same-size candidates → hash first 64 KB
  3. same-head candidates → full MD5

Report-only by default; quarantining selected duplicates goes through the
organizer's journalled move engine so undo works.
"""

import hashlib
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import List

from app.core.config import ConfigManager
from app.models.models import DuplicateGroup, DuplicateReport

logger = logging.getLogger(__name__)

HEAD_BYTES = 65536


def _norm(p: str) -> str:
    return os.path.normpath(p).rstrip("\\/") or "/"


class DuplicateFinder:
    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
        self.last_report = None

    def find(self, max_files: int = 20000) -> DuplicateReport:
        cfg = self.config_manager.load()
        roots = [
            _norm(mp.path) for mp in cfg.managed_paths
            if mp.enabled and Path(mp.path).exists()
        ]
        disallow = [_norm(dp.path) for dp in cfg.disallow_paths]

        def forbidden(path: str) -> bool:
            p = _norm(path)
            if ConfigManager.is_forbidden(p):
                return True
            return any(p == d or p.startswith(d + "/") for d in disallow)

        report = DuplicateReport(started_at=datetime.utcnow())
        files: List[str] = []
        for root in roots:
            if forbidden(root):
                continue
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = sorted(
                    d for d in dirnames if not forbidden(os.path.join(dirpath, d))
                )
                for fname in filenames:
                    files.append(os.path.join(dirpath, fname))
                    if len(files) >= max_files:
                        break
                if len(files) >= max_files:
                    break

        report.scanned_files = len(files)

        # Stage 1: size
        by_size = {}
        for f in files:
            try:
                by_size.setdefault(os.path.getsize(f), []).append(f)
            except OSError:
                continue
        candidates = [fs for fs in by_size.values() if len(fs) > 1]

        # Stage 2: head hash
        by_head = {}
        for group in candidates:
            for f in group:
                h = _hash(f, HEAD_BYTES)
                if h:
                    by_head.setdefault((os.path.getsize(f), h), []).append(f)
        head_candidates = [fs for fs in by_head.values() if len(fs) > 1]

        # Stage 3: full hash
        by_full = {}
        for group in head_candidates:
            for f in group:
                h = _hash(f, None)
                if h:
                    by_full.setdefault(h, []).append(f)

        for h, group in by_full.items():
            if len(group) < 2:
                continue
            group.sort(key=lambda p: os.path.getmtime(p))
            size = os.path.getsize(group[0])
            report.groups.append(DuplicateGroup(
                hash=h, size_bytes=size, files=group, keep=group[0],
            ))
            report.wasted_bytes += size * (len(group) - 1)

        report.groups.sort(key=lambda g: -g.size_bytes * (len(g.files) - 1))
        report.finished_at = datetime.utcnow()
        self.last_report = report
        return report


def _hash(path: str, limit: int = None) -> str | None:
    try:
        h = hashlib.md5()
        with open(path, "rb") as f:
            if limit is None:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(chunk)
            else:
                h.update(f.read(limit))
        return h.hexdigest()
    except OSError as e:
        logger.debug("Hash failed for %s: %s", path, e)
        return None

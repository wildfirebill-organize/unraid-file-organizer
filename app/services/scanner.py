"""Directory scanner — walks allowed roots, skips disallowed paths, classifies files."""

import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import List

from app.core.config import ConfigManager
from app.core.file_classifier import (
    FileCategory,
    FileIntent,
    SmartFileClassifier,
    detect_folder_unit,
    looks_like_app_folder,
)
from app.models.models import ScanResult, ScanResultItem
from app.services.history import record_history
from app.services.media_library import destination_for, parse_media

logger = logging.getLogger(__name__)


def _norm(p: str) -> str:
    return os.path.normpath(p).rstrip("\\/") or "/"


class ScannerService:
    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
        self.classifier = SmartFileClassifier()
        self.last_result: ScanResult | None = None

    def scan(self, max_files: int | None = None, trigger: str = "manual") -> ScanResult:
        cfg = self.config_manager.load()
        limit = max_files or cfg.max_files_per_scan

        allowed_roots = [
            _norm(mp.path) for mp in cfg.managed_paths
            if mp.enabled and Path(mp.path).exists()
        ]
        disallow = [_norm(dp.path) for dp in cfg.disallow_paths]

        result = ScanResult(started_at=datetime.utcnow(), roots_scanned=allowed_roots)

        def is_disallowed(path: str) -> bool:
            p = _norm(path)
            if ConfigManager.is_forbidden(p):
                return True
            return any(p == d or p.startswith(d + "/") for d in disallow)

        count = 0
        for root in allowed_roots:
            if is_disallowed(root):
                continue
            try:
                for dirpath, dirnames, filenames in os.walk(root):
                    # Prune disallowed subdirectories in-place (prevents descending)
                    dirnames[:] = sorted(
                        d for d in dirnames if not is_disallowed(os.path.join(dirpath, d))
                    )

                    # Folder-unit detection (phase 2): nested clusters, launcher
                    # artifacts, engine data — portable app/game dirs move whole
                    maybe_unit = (
                        looks_like_app_folder(filenames)
                        or bool(dirnames)
                        or any(f.lower().endswith((".exe", ".dll")) for f in filenames)
                    )
                    if dirpath != root and maybe_unit:
                        unit_info = None
                        try:
                            unit_info = detect_folder_unit(Path(dirpath))
                        except Exception as e:
                            result.errors.append(f"{dirpath}: {e}")
                        if unit_info:
                            try:
                                cls = self.classifier.classify_folder(Path(dirpath), unit_info)
                                item = ScanResultItem(
                                    source_path=dirpath,
                                    filename=os.path.basename(dirpath),
                                    parent_dir=os.path.dirname(dirpath),
                                    size_bytes=cls.details.get("size", 0),
                                    category=cls.category.value,
                                    intent=cls.intent.value,
                                    confidence=round(cls.confidence, 2),
                                    suggested_destination=cls.suggested_location,
                                    details=self._lean_details(cls.details),
                                )
                                self._apply_rules_and_overrides(item, cfg)
                                result.items.append(item)
                                dirnames[:] = []  # unit claimed — don't descend
                                count += 1
                                continue
                            except Exception as e:
                                result.errors.append(f"{dirpath}: {e}")

                    for fname in filenames:
                        full = os.path.join(dirpath, fname)
                        try:
                            cls = self.classifier.classify(Path(full))
                        except Exception as e:
                            result.errors.append(f"{full}: {e}")
                            continue
                        item = ScanResultItem(
                            source_path=full,
                            filename=fname,
                            parent_dir=dirpath,
                            size_bytes=cls.details.get("size", 0),
                            category=cls.category.value,
                            intent=cls.intent.value,
                            confidence=round(cls.confidence, 2),
                            suggested_destination=cls.suggested_location,
                            details=self._lean_details(cls.details),
                        )
                        self._apply_rules_and_overrides(item, cfg)
                        self._apply_media_library(item, cfg)
                        result.items.append(item)
                        count += 1
                        if count >= limit:
                            logger.warning("Scan hit file limit (%d)", limit)
                            break
                    if count >= limit:
                        break
            except Exception as e:
                result.errors.append(f"root {root}: {e}")

        result.total_files = len(result.items)
        result.finished_at = datetime.utcnow()

        if cfg.llm_enabled and result.items:
            self._llm_enhance(result, cfg)
            for item in result.items:
                if item.details.get("llm_assisted"):
                    self._apply_category_override(item, cfg)

        record_history(result, cfg, trigger)
        self.last_result = result
        return result

    @staticmethod
    def _apply_media_library(item: ScanResultItem, cfg) -> None:
        """Route TV episodes / movies into library layout. Rules win; media beats generic overrides."""
        if not getattr(cfg, "media_library_enabled", False):
            return
        if item.details.get("rule_matched"):
            return
        parsed = parse_media(item.filename)
        if not parsed:
            return
        item.suggested_destination = destination_for(parsed, cfg)
        item.confidence = max(item.confidence, 0.9)
        item.details["media_parsed"] = parsed["type"]

    def _apply_rules_and_overrides(self, item: ScanResultItem, cfg) -> None:
        """Custom rules first (first match wins), then per-category destination overrides."""
        explicit_dest = False
        for rule in cfg.custom_rules:
            if not rule.enabled:
                continue
            target = item.filename if rule.match_on == "filename" else item.source_path
            try:
                matched = re.search(rule.pattern, target, re.IGNORECASE)
            except re.error:
                continue
            if not matched:
                continue

            if rule.category:
                item.category = rule.category
                item.suggested_destination = self.classifier._suggest_location(
                    FileCategory(rule.category), FileIntent(item.intent)
                )
            if rule.intent:
                item.intent = rule.intent
            if rule.destination:
                item.suggested_destination = rule.destination.rstrip("/\\") + "/"
                explicit_dest = True

            item.confidence = max(item.confidence, 0.95)  # user-defined = trusted
            item.details["rule_matched"] = rule.name or rule.pattern
            break

        self._apply_category_override(item, cfg, skip=explicit_dest)

    @staticmethod
    def _apply_category_override(item: ScanResultItem, cfg, skip: bool = False) -> None:
        if skip:
            return
        dest = cfg.category_destinations.get(item.category)
        if dest:
            item.suggested_destination = dest.rstrip("/\\") + "/"

    @staticmethod
    def _lean_details(details: dict) -> dict:
        """Trim details for API payload but keep string samples (LLM needs them)."""
        lean = {k: v for k, v in details.items() if k != "size"}
        strings = lean.get("strings_sample")
        if isinstance(strings, list):
            lean["strings_sample"] = [str(s)[:60] for s in strings[:15]]
        return lean

    @staticmethod
    def _llm_enhance(result: ScanResult, cfg) -> None:
        from app.services.llm_classifier import LLMClassifier
        try:
            stats = LLMClassifier().enhance(result.items, cfg)
            logger.info(
                "LLM assist: %d candidates, %d upgraded, %d failed",
                stats["candidates"], stats["upgraded"], stats["failed"],
            )
            if stats["candidates"]:
                result.errors.append(
                    f"llm_assist: upgraded {stats['upgraded']}/{stats['candidates']} low-confidence files"
                )
        except Exception as e:
            logger.warning("LLM assist unavailable, using deterministic results: %s", e)
            result.errors.append(f"llm_assist skipped: {e}")

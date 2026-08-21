"""Optional LLM-assisted classification via a local Ollama instance.

Design contract:
- Only invoked for files the deterministic classifier scored below the
  configured confidence threshold (or marked unknown).
- Every failure mode degrades silently to the deterministic result.
- Results are validated against the known category/intent enums before use.
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Tuple

import httpx

from app.core.file_classifier import FileCategory, FileIntent, SmartFileClassifier
from app.models.models import OrganizerConfig, ScanResultItem

logger = logging.getLogger(__name__)

VALID_CATEGORIES = {c.value for c in FileCategory}
VALID_INTENTS = {i.value for i in FileIntent}

SYSTEM_PROMPT = """You are a file classification assistant for a NAS file organizer.
Classify the given file into exactly one category and one intent.

Valid categories:
executable_windows, executable_linux, executable_macos, executable_android,
os_image, game_rom, homebrew, archive, document, media_audio, media_video,
media_image, code_source, config, database, log, temp, unknown

Valid intents:
music_player, network_tool, system_utility, game, development_tool,
office_app, media_player, archive_tool, os_component, driver, emulator,
homebrew, data_file, unknown

Reply with ONLY a JSON object, no other text:
{"category": "<category>", "intent": "<intent>", "confidence": <0.0-1.0>}

If the evidence is insufficient, use category "unknown", intent "unknown",
and confidence 0.1. Never invent categories or intents outside the lists."""


class LLMClassifier:
    """Second-opinion tier backed by Ollama. Never raises into the scan path."""

    def __init__(self):
        # Reuse deterministic location mapping for LLM results
        self._fallback = SmartFileClassifier()

    # ---------- connectivity ----------

    def available(self, cfg: OrganizerConfig) -> Tuple[bool, str]:
        """Check Ollama reachability and that the model exists (prefix match)."""
        base = cfg.ollama_url.rstrip("/")
        try:
            r = httpx.get(f"{base}/api/tags", timeout=5)
            r.raise_for_status()
            models = [m.get("name", "") for m in r.json().get("models", [])]
        except Exception as e:
            return False, f"Ollama unreachable at {base}: {e}"

        wanted = cfg.ollama_model.lower()
        match = next(
            (m for m in models if m.lower() == wanted or m.lower().startswith(wanted + ":")),
            None,
        )
        if not match:
            return False, f"Model '{cfg.ollama_model}' not found. Available: {', '.join(models[:10]) or 'none'}"
        return True, f"OK — using {match}"

    # ---------- batch enhancement ----------

    def enhance(self, items: List[ScanResultItem], cfg: OrganizerConfig) -> dict:
        """Upgrade low-confidence items in place. Returns stats for logging/UI."""
        targets = [
            i for i in items
            if (i.confidence < cfg.min_confidence or i.category == FileCategory.UNKNOWN.value)
            and not i.details.get("rule_matched")
        ]
        targets = targets[: max(0, cfg.llm_max_files)]
        stats = {"candidates": len(targets), "upgraded": 0, "failed": 0}

        if not targets:
            return stats

        with ThreadPoolExecutor(max_workers=4) as ex:
            futures = {ex.submit(self._classify_one, item, cfg): item for item in targets}
            for fut in as_completed(futures):
                item = futures[fut]
                try:
                    parsed = fut.result()
                except Exception as e:
                    logger.debug("LLM classify failed for %s: %s", item.filename, e)
                    stats["failed"] += 1
                    continue
                if parsed is None:
                    stats["failed"] += 1
                    continue
                cat, intent, conf = parsed
                item.category = cat
                item.intent = intent
                item.confidence = conf
                item.suggested_destination = self._fallback._suggest_location(
                    FileCategory(cat), FileIntent(intent)
                )
                item.details["llm_assisted"] = True
                stats["upgraded"] += 1

        return stats

    # ---------- single file ----------

    def _classify_one(self, item: ScanResultItem, cfg: OrganizerConfig) -> Optional[Tuple[str, str, float]]:
        base = cfg.ollama_url.rstrip("/")
        payload = {
            "model": cfg.ollama_model,
            "format": "json",
            "stream": False,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": self._file_brief(item)},
            ],
            "options": {"temperature": 0},
        }
        r = httpx.post(f"{base}/api/chat", json=payload, timeout=60)
        r.raise_for_status()
        content = r.json()["message"]["content"]
        return self.parse_response(content)

    @staticmethod
    def _file_brief(item: ScanResultItem) -> str:
        lines = [f"name: {item.filename}", f"size_bytes: {item.size_bytes}"]
        mime = item.details.get("mime_type")
        if mime:
            lines.append(f"mime_type: {mime}")
        strings = item.details.get("strings_sample") or []
        if strings:
            lines.append("embedded_strings: " + ", ".join(str(s) for s in strings[:25]))
        return "\n".join(lines)

    @staticmethod
    def parse_response(content: str) -> Optional[Tuple[str, str, float]]:
        """Validate an LLM reply. Returns (category, intent, confidence) or None."""
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return None

        cat = str(data.get("category", "")).strip().lower()
        intent = str(data.get("intent", "")).strip().lower()
        try:
            conf = float(data.get("confidence", 0))
        except (TypeError, ValueError):
            return None

        if cat not in VALID_CATEGORIES or intent not in VALID_INTENTS:
            return None
        conf = max(0.0, min(1.0, conf))
        if cat == "unknown" or conf < 0.5:
            return None  # LLM is unsure — keep deterministic result
        return cat, intent, round(conf, 2)

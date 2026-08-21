"""Configuration persistence — stores organizer settings as JSON."""

import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

from app.core.file_classifier import FileCategory, FileIntent
from app.models.models import OrganizerConfig, ManagedPath, DisallowPath

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = os.environ.get("ORGANIZER_CONFIG", "/config/config.json")

# Locations that are ALWAYS forbidden regardless of user config.
HARD_FORBIDDEN_PREFIXES = [
    "/boot",
    "/etc",
    "/usr",
    "/bin",
    "/sbin",
    "/lib",
    "/lib64",
    "/proc",
    "/sys",
    "/dev",
    "/run",
    "/var/run",
    "/mnt/cache/appdata",       # docker appdata
    "/mnt/user/system",         # unraid system shares (docker.img etc.)
    "/mnt/user0/system",
]

DEFAULT_DISALLOW = [
    DisallowPath(path="/mnt/user/system", label="Unraid system share"),
    DisallowPath(path="/mnt/cache/appdata", label="Docker appdata"),
    DisallowPath(path="/mnt/user/domains", label="VM domains"),
    DisallowPath(path="/mnt/user/appdata", label="Appdata share"),
]

DEFAULT_MANAGED = [
    ManagedPath(path="/mnt/user/downloads", label="Downloads", enabled=False),
    ManagedPath(path="/mnt/user/isos", label="ISOs", enabled=False),
    ManagedPath(path="/mnt/user/media", label="Media", enabled=False),
    ManagedPath(path="/mnt/user/apps", label="Apps/Installers", enabled=False),
]


def _norm(p: str) -> str:
    return p.rstrip("/") or "/"


class ConfigManager:
    def __init__(self, config_path: str = DEFAULT_CONFIG_PATH):
        self.config_path = Path(config_path)
        self._config: Optional[OrganizerConfig] = None

    def load(self) -> OrganizerConfig:
        if self._config is not None:
            return self._config
        try:
            if self.config_path.exists():
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                self._config = OrganizerConfig(**data)
            else:
                self._config = OrganizerConfig(
                    managed_paths=DEFAULT_MANAGED,
                    disallow_paths=DEFAULT_DISALLOW,
                )
                self.save()
        except Exception as e:
            logger.error("Failed to load config: %s", e)
            self._config = OrganizerConfig()
        return self._config

    def save(self, config: Optional[OrganizerConfig] = None) -> OrganizerConfig:
        cfg = config or self._config
        if cfg is None:
            raise RuntimeError("No config to save")
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.config_path.with_suffix(".tmp")
        tmp.write_text(cfg.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(self.config_path)
        self._config = cfg
        return cfg

    def update(self, new_config: OrganizerConfig) -> OrganizerConfig:
        """Validate safety constraints before saving."""
        for mp in new_config.managed_paths:
            p = _norm(mp.path)
            if any(p == f or p.startswith(f + "/") for f in HARD_FORBIDDEN_PREFIXES):
                raise ValueError(f"Managed path '{mp.path}' is inside a protected system location")
        for dp in new_config.disallow_paths:
            dp.path = _norm(dp.path)
        for mp in new_config.managed_paths:
            mp.path = _norm(mp.path)

        valid_cats = {c.value for c in FileCategory}
        valid_intents = {i.value for i in FileIntent}

        for rule in new_config.custom_rules:
            label = rule.name or rule.pattern
            try:
                re.compile(rule.pattern)
            except re.error as e:
                raise ValueError(f"Invalid regex in rule '{label}': {e}")
            if rule.match_on not in ("filename", "path"):
                raise ValueError(f"Rule '{label}': match_on must be 'filename' or 'path'")
            if rule.category and rule.category not in valid_cats:
                raise ValueError(f"Rule '{label}': unknown category '{rule.category}'")
            if rule.intent and rule.intent not in valid_intents:
                raise ValueError(f"Rule '{label}': unknown intent '{rule.intent}'")

        for cat, dest in list(new_config.category_destinations.items()):
            if cat not in valid_cats:
                raise ValueError(f"Destination override: unknown category '{cat}'")
            new_config.category_destinations[cat] = _norm(dest)

        if new_config.notify_type not in ("generic", "discord", "ntfy"):
            raise ValueError(f"Unknown notification type '{new_config.notify_type}'")
        if new_config.schedule_interval_hours < 1:
            raise ValueError("Schedule interval must be at least 1 hour")

        return self.save(new_config)

    @staticmethod
    def is_forbidden(path: str) -> bool:
        p = _norm(path)
        return any(p == f or p.startswith(f + "/") for f in HARD_FORBIDDEN_PREFIXES)

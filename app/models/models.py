"""Data models for the Unraid organizer"""

import os

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime


def _default_ollama_url() -> str:
    return os.environ.get("ORGANIZER_OLLAMA_URL") or "http://host.docker.internal:11434"


class ManagedPath(BaseModel):
    """A location the organizer is ALLOWED to touch/move files from.
    Controlled by a checkbox in the UI."""
    path: str
    label: str = ""
    enabled: bool = False  # checkbox state


class DisallowPath(BaseModel):
    """A location the organizer must NEVER touch, even if nested inside an allowed path."""
    path: str
    label: str = ""


class CustomRule(BaseModel):
    """User-defined classification rule. First match wins; outranks built-in heuristics."""
    name: str = ""
    pattern: str
    match_on: str = "filename"  # filename | path
    category: Optional[str] = None
    intent: Optional[str] = None
    destination: Optional[str] = None
    enabled: bool = True


class OrganizerConfig(BaseModel):
    """Full organizer configuration, persisted as JSON."""
    managed_paths: List[ManagedPath] = Field(default_factory=list)
    disallow_paths: List[DisallowPath] = Field(default_factory=list)
    destination_root: str = "/mnt/user"
    dry_run: bool = True
    min_confidence: float = 0.6
    duplicate_policy: str = "rename"  # skip | rename
    max_files_per_scan: int = 50000
    # Optional LLM assist (local Ollama). Only used for low-confidence files.
    llm_enabled: bool = False
    ollama_url: str = Field(default_factory=_default_ollama_url)
    ollama_model: str = "qwen2.5:3b"
    llm_max_files: int = 100
    # User-defined rules that outrank built-in heuristics (first match wins)
    custom_rules: List[CustomRule] = Field(default_factory=list)
    # Per-category destination overrides, e.g. {"media_audio": "/mnt/user/media/music"}
    category_destinations: Dict[str, str] = Field(default_factory=dict)
    # Scheduled automatic dry-run scans (never move files)
    schedule_enabled: bool = False
    schedule_interval_hours: int = 24
    # Webhook notifications (generic JSON | discord | ntfy)
    notify_enabled: bool = False
    notify_type: str = "generic"
    notify_url: str = ""
    # Media library mode (Plex/Jellyfin-style TV & movie routing)
    media_library_enabled: bool = False
    media_library_root: str = "/mnt/user/media"


class HistoryEntry(BaseModel):
    """One recorded scan, for the history dashboard."""
    timestamp: datetime
    trigger: str  # manual | scheduled
    roots_scanned: List[str] = []
    total_files: int = 0
    movable_files: int = 0
    total_size_bytes: int = 0
    by_category: Dict[str, int] = {}


class DuplicateGroup(BaseModel):
    hash: str
    size_bytes: int
    files: List[str]
    keep: str  # suggested original to retain


class DuplicateReport(BaseModel):
    started_at: datetime
    finished_at: Optional[datetime] = None
    scanned_files: int = 0
    groups: List[DuplicateGroup] = []
    wasted_bytes: int = 0


class ScanResultItem(BaseModel):
    source_path: str
    filename: str
    parent_dir: str
    size_bytes: int
    category: str
    intent: str
    confidence: float
    suggested_destination: Optional[str] = None
    details: Dict[str, Any] = {}


class ScanResult(BaseModel):
    started_at: datetime
    finished_at: Optional[datetime] = None
    roots_scanned: List[str] = []
    total_files: int = 0
    items: List[ScanResultItem] = []
    errors: List[str] = []


class MoveOperation(BaseModel):
    source: str
    destination: str
    category: str
    intent: str
    confidence: float
    status: str = "pending"  # pending | done | skipped | error
    error: Optional[str] = None


class OperationLogEntry(BaseModel):
    timestamp: datetime
    dry_run: bool
    applied: bool
    operations: List[MoveOperation]


class ApplyRequest(BaseModel):
    """Request body for applying a plan. Selected sources can be filtered."""
    selected_sources: Optional[List[str]] = None  # None = all
    force_dry_run: bool = False


class PlanResponse(BaseModel):
    operations: List[MoveOperation]
    total_size_bytes: int
    by_category: Dict[str, int]
    conflicts: int

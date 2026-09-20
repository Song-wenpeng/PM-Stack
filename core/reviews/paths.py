"""Writable paths used by the integrated review subsystem."""

from __future__ import annotations

import os
from pathlib import Path


def _local_app_data() -> Path:
    value = os.environ.get("LOCALAPPDATA")
    if value:
        return Path(value)
    return Path.home() / ".pm-stack"


def _documents_dir() -> Path:
    value = os.environ.get("USERPROFILE")
    return (Path(value) if value else Path.home()) / "Documents"


PM_STACK_DATA_DIR = _local_app_data() / "PM Stack"
APP_DATA_DIR = PM_STACK_DATA_DIR / "reviews"
DATA_DIR = APP_DATA_DIR / "data"
BROWSER_PROFILE_DIR = APP_DATA_DIR / "browser_profile"
LOG_DIR = APP_DATA_DIR / "logs"
BACKUP_DIR = APP_DATA_DIR / "backups"
DEBUG_DIR = APP_DATA_DIR / "debug_pages"
EXPORT_DIR = _documents_dir() / "PM Stack" / "评论导出"

# The standalone collector used this location.  It is only a migration source;
# the integrated application never writes to it implicitly.
LEGACY_APP_DATA_DIR = _local_app_data() / "ReviewCollector"
LEGACY_DB_PATH = LEGACY_APP_DATA_DIR / "data" / "reviews.db"


def ensure_app_dirs() -> None:
    for path in (
        APP_DATA_DIR,
        DATA_DIR,
        BROWSER_PROFILE_DIR,
        LOG_DIR,
        BACKUP_DIR,
        DEBUG_DIR,
        EXPORT_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)


ensure_app_dirs()


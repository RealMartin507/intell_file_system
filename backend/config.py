import json
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent / "config.json"

_config: dict | None = None


def get_config() -> dict:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def load_config() -> dict:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return _default_config()


def save_config(config: dict) -> None:
    global _config
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=4)
    _config = config


def reload_config() -> dict:
    global _config
    _config = None
    return get_config()


def _default_config() -> dict:
    return {
        "scan_roots": [],
        "exclude_dirs": [
            "$RECYCLE.BIN",
            "System Volume Information",
            ".Trash",
        ],
        "exclude_patterns": [
            "~$*",
            "*.tmp",
            "Thumbs.db",
            "desktop.ini",
        ],
        "auto_scan_interval_minutes": 30,
        "server_port": 8000,
        "thumbnail_cache_dir": "./data/thumbnails",
    }

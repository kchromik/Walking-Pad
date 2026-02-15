"""Persistent configuration for WalkingPad OBS Overlay."""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".config" / "walkingpad-obs"
CONFIG_FILE = CONFIG_DIR / "config.json"


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception as e:
            logger.warning("Failed to load config: %s", e)
    return {}


def save_config(config: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2))


def get_last_mac() -> str | None:
    return load_config().get("last_mac")


def set_last_mac(mac: str) -> None:
    config = load_config()
    config["last_mac"] = mac
    save_config(config)

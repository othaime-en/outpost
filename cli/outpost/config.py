"""
CLI Configuration

Reads/writes ~/.outpost/config.yaml. Holds the API endpoint, the transient
bearer token from `outpost auth login`, and the persistent API key from
`outpost auth key generate`. Every command other than the auth ones uses the
API key day-to-day — the bearer token exists only long enough to mint it.
"""

from pathlib import Path
from typing import Any, Optional

import yaml

CONFIG_PATH = Path.home() / ".outpost" / "config.yaml"


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    return yaml.safe_load(CONFIG_PATH.read_text()) or {}


def save_config(config: dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(yaml.dump(config))
    CONFIG_PATH.chmod(0o600)  # holds credentials — owner read/write only


def get_endpoint() -> str:
    return load_config().get("endpoint", "http://localhost:8000")


def get_token() -> Optional[str]:
    return load_config().get("token")


def get_api_key() -> Optional[str]:
    return load_config().get("api_key")
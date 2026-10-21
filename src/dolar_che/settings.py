"""Where the bot keeps its token and settings: a folder in the user's home, never in the repo."""

from __future__ import annotations

import json
import os
from pathlib import Path


def home(env: dict[str, str | None] | os._Environ[str] = os.environ) -> Path:
    return Path(env.get("DOLAR_CHE_HOME") or Path.home() / ".dolar-che")


def load_token(env, folder: Path) -> str | None:
    """DISCORD_TOKEN from the environment, or the first line of <folder>/token."""
    token = (env.get("DISCORD_TOKEN") or "").strip()
    if token:
        return token
    try:
        token = (folder / "token").read_text(encoding="utf-8").strip().splitlines()[0].strip()
    except (OSError, IndexError):
        return None
    return token or None


def summary_channel(env, folder: Path) -> int | None:
    """The channel for the daily summary: DOLAR_CHE_CANAL_RESUMEN, or the one set with /resumen-aca."""
    raw = env.get("DOLAR_CHE_CANAL_RESUMEN")
    if not raw:
        try:
            raw = json.loads((folder / "config.json").read_text(encoding="utf-8")).get("summary_channel")
        except (OSError, json.JSONDecodeError, AttributeError):
            return None
    try:
        return int(raw) if raw else None
    except (TypeError, ValueError):
        return None


def set_summary_channel(folder: Path, channel_id: int | None) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "config.json"
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            config = {}
    except (OSError, json.JSONDecodeError):
        config = {}
    config["summary_channel"] = channel_id
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(config, indent=2), encoding="utf-8")
    os.replace(tmp, path)

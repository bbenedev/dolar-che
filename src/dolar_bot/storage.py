"""Alerts kept in a small JSON file, so they survive a restart."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .core import Alert

MAX_ALERTS_PER_USER = 5


def load(path: Path) -> list[Alert]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (json.JSONDecodeError, OSError):
        return []  # a corrupt file must not stop the bot; it starts with no alerts
    alerts = []
    for item in raw if isinstance(raw, list) else []:
        try:
            alerts.append(
                Alert(
                    int(item["user_id"]),
                    str(item["rate"]),
                    str(item["side"]),
                    bool(item["above"]),
                    float(item["target"]),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return alerts


def save(path: Path, alerts: list[Alert]) -> None:
    """Write to a temp file and rename, so a crash never leaves half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    data = [a.__dict__ for a in alerts]
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def add(alerts: list[Alert], new: Alert) -> list[Alert]:
    mine = [a for a in alerts if a.user_id == new.user_id]
    if new in alerts:
        return alerts
    if len(mine) >= MAX_ALERTS_PER_USER:
        raise ValueError(f"Máximo {MAX_ALERTS_PER_USER} alertas por persona. Borrá una con /borrar-alerta.")
    return [*alerts, new]


def remove(alerts: list[Alert], user_id: int, index: int) -> list[Alert]:
    """Remove the user's alert number `index` (1 based, as shown by /alertas)."""
    mine = [a for a in alerts if a.user_id == user_id]
    if not 1 <= index <= len(mine):
        raise ValueError("Ese número de alerta no existe. Mirá /alertas.")
    target = mine[index - 1]
    out, removed = [], False
    for a in alerts:
        if a == target and not removed:
            removed = True
            continue
        out.append(a)
    return out

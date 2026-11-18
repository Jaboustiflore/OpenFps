"""Préférences de l'utilisateur (profil choisi), dans %APPDATA%\\OpenFPS\\settings.json."""

from __future__ import annotations

import json
import os


def _path() -> str:
    return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                        "OpenFPS", "settings.json")


def load() -> dict:
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(**values) -> None:
    data = load()
    data.update(values)
    try:
        os.makedirs(os.path.dirname(_path()), exist_ok=True)
        with open(_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        pass

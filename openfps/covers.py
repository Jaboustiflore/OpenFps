"""Recherche des jaquettes de jeux, sans embarquer d'images protégées.

Ordre de recherche :
1. une image fournie par l'utilisateur : %APPDATA%\\OpenFPS\\covers\\<id>.png|jpg
2. la jaquette déjà présente dans le cache local de Steam (jeux avec "steam_appid")
3. sinon l'interface dessine une jaquette générée (couleur déduite de l'id).
"""

from __future__ import annotations

import colorsys
import glob
import hashlib
import os
import re

EXTS = ("png", "jpg", "jpeg")


def user_covers_dir() -> str:
    return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "OpenFPS", "covers")


def steam_roots() -> list:
    """Dossiers d'installation de Steam trouvés sur ce PC."""
    roots = []
    try:  # Windows : chemin lu dans le registre
        import winreg  # type: ignore

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            roots.append(winreg.QueryValueEx(k, "SteamPath")[0])
    except Exception:
        pass
    for var in ("ProgramFiles(x86)", "ProgramFiles"):
        base = os.environ.get(var)
        if base:
            roots.append(os.path.join(base, "Steam"))
    roots.append(os.path.expanduser("~/.steam/steam"))
    out = []
    for r in roots:
        r = os.path.normpath(r)
        if os.path.isdir(r) and r not in out:
            out.append(r)
    return out


def steam_cover(appid: int):
    """Jaquette verticale 600x900 dans le cache Steam (ancienne ou nouvelle disposition)."""
    for root in steam_roots():
        cache = os.path.join(root, "appcache", "librarycache")
        patterns = [
            os.path.join(cache, f"{appid}_library_600x900*.jpg"),
            os.path.join(cache, str(appid), "library_600x900*.jpg"),
            os.path.join(cache, str(appid), "**", "library_600x900*.jpg"),
        ]
        for pat in patterns:
            hits = sorted(glob.glob(pat, recursive=True))
            if hits:
                return hits[0]
    return None


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def find_cover(game):
    """Chemin d'une image existante pour ce jeu, ou None."""
    folder = user_covers_dir()
    keys = {_slug(game.id), _slug(game.name)}
    for key in keys:
        for ext in EXTS:
            p = os.path.join(folder, f"{key}.{ext}")
            if os.path.isfile(p):
                return p
    appid = getattr(game, "steam_appid", None)
    if appid:
        return steam_cover(int(appid))
    return None


def tile_colors(game_id: str):
    """Deux couleurs (haut, bas) stables pour une jaquette générée, en #rrggbb."""
    h = int(hashlib.md5(game_id.encode("utf-8")).hexdigest()[:6], 16) % 360 / 360
    top = colorsys.hsv_to_rgb(h, 0.65, 0.75)
    bottom = colorsys.hsv_to_rgb((h + 0.08) % 1, 0.8, 0.22)
    fmt = lambda c: "#%02x%02x%02x" % tuple(int(x * 255) for x in c)
    return fmt(top), fmt(bottom)

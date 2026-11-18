"""Recherche des jaquettes de jeux, sans embarquer d'images protégées.

Ordre de recherche :
1. une image fournie par l'utilisateur : %APPDATA%\\OpenFPS\\covers\\<id>.png|jpg
2. la jaquette déjà présente dans le cache local de Steam (jeux avec "steam_appid")
3. sinon téléchargée depuis le CDN officiel de Steam (dans le dossier ci-dessus)
4. sinon l'interface dessine une jaquette générée (couleur déduite de l'id).
"""

from __future__ import annotations

import colorsys
import glob
import hashlib
import json
import os
import re
import urllib.request

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
        hit = steam_cover(int(appid))
        if hit:
            return hit
        cached = os.path.join(user_covers_dir(), f"steam_{int(appid)}.jpg")
        if os.path.isfile(cached):
            return cached
    return None


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def _appid_cache_path() -> str:
    return os.path.join(os.path.dirname(user_covers_dir()), "appids.json")


def lookup_appid(name: str):
    """Retrouve l'appid Steam d'un jeu par son nom (correspondance EXACTE seulement,
    pour ne jamais afficher la jaquette d'un autre jeu). Résultat mis en cache."""
    key = _norm(name)
    if len(key) < 3:
        return None
    try:
        with open(_appid_cache_path(), encoding="utf-8") as f:
            cache = json.load(f)
    except (OSError, ValueError):
        cache = {}
    if key in cache:
        return cache[key] or None
    try:
        import urllib.parse
        url = ("https://store.steampowered.com/api/storesearch/?cc=fr&l=french&term="
               + urllib.parse.quote(name))
        req = urllib.request.Request(url, headers={"User-Agent": "OpenFPS"})
        with urllib.request.urlopen(req, timeout=10) as r:
            items = json.loads(r.read().decode("utf-8")).get("items", [])
    except Exception:
        return None  # réseau indisponible : on réessaiera plus tard (pas de cache)
    found = next((int(i["id"]) for i in items if _norm(i.get("name")) == key), 0)
    cache[key] = found
    try:
        os.makedirs(os.path.dirname(_appid_cache_path()), exist_ok=True)
        with open(_appid_cache_path(), "w", encoding="utf-8") as f:
            json.dump(cache, f)
    except OSError:
        pass
    return found or None


_FAILED: set = set()
CDN = ("https://cdn.cloudflare.steamstatic.com/steam/apps/{id}/library_600x900.jpg",
       "https://cdn.akamai.steamstatic.com/steam/apps/{id}/library_600x900.jpg")


def download_cover(appid: int):
    """Télécharge la jaquette officielle depuis le CDN de Steam dans le dossier de
    l'utilisateur (rien n'est embarqué dans le dépôt). Retourne le chemin ou None."""
    appid = int(appid)
    if appid in _FAILED:
        return None
    dest = os.path.join(user_covers_dir(), f"steam_{appid}.jpg")
    if os.path.isfile(dest):
        return dest
    for url in CDN:
        try:
            req = urllib.request.Request(url.format(id=appid), headers={"User-Agent": "OpenFPS"})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = r.read()
            if len(data) > 2000 and data[:2] == b"\xff\xd8":  # JPEG valide
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                tmp = dest + ".part"
                with open(tmp, "wb") as f:
                    f.write(data)
                os.replace(tmp, dest)
                return dest
        except Exception:
            continue
    _FAILED.add(appid)
    return None


def tile_colors(game_id: str):
    """Deux couleurs (haut, bas) stables pour une jaquette générée, en #rrggbb."""
    h = int(hashlib.md5(game_id.encode("utf-8")).hexdigest()[:6], 16) % 360 / 360
    top = colorsys.hsv_to_rgb(h, 0.65, 0.75)
    bottom = colorsys.hsv_to_rgb((h + 0.08) % 1, 0.8, 0.22)
    fmt = lambda c: "#%02x%02x%02x" % tuple(int(x * 255) for x in c)
    return fmt(top), fmt(bottom)

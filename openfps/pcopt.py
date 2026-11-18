"""Optimisation du PC (Windows) : réglages utiles aux jeux, au niveau de ton compte.

Tout est réversible : les valeurs d'origine sont sauvegardées dans
%APPDATA%\\OpenFPS\\pc_backup.json avant le moindre changement.

Réglages :
- plan d'alimentation « Performances élevées »
- Mode jeu de Windows activé
- carte graphique performante imposée à chaque jeu détecté (HKCU, par exécutable)
- optimisations plein écran désactivées pour chaque jeu détecté (HKCU, par exécutable)

Rien ici ne touche aux services Windows ni au registre système (HKLM).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from typing import Optional

HIGH_PERF_GUID = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
GPU_KEY = r"Software\Microsoft\DirectX\UserGpuPreferences"
LAYERS_KEY = r"Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"
GAMEBAR_KEY = r"Software\Microsoft\GameBar"
GPU_VALUE = "GpuPreference=2;"
FSO_FLAG = "~ DISABLEDXMAXIMIZEDWINDOWEDMODE"

IS_WINDOWS = os.name == "nt"


def backup_path() -> str:
    return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                        "OpenFPS", "pc_backup.json")


# ----------------------------------------------------------------- Steam / exe
def parse_library_paths(vdf_text: str) -> list:
    """Chemins des bibliothèques Steam d'après libraryfolders.vdf."""
    return [p.replace("\\\\", "\\") for p in re.findall(r'"path"\s+"([^"]+)"', vdf_text)]


def steam_libraries() -> list:
    from . import covers
    libs = []
    for root in covers.steam_roots():
        libs.append(root)
        vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
        try:
            with open(vdf, encoding="utf-8", errors="replace") as f:
                libs += parse_library_paths(f.read())
        except OSError:
            pass
    out = []
    for lib in libs:
        lib = os.path.normpath(lib)
        if lib not in out:
            out.append(lib)
    return out


def find_exe(install_dir: str, exe: str) -> Optional[str]:
    """Chemin complet de l'exécutable d'un jeu Steam, ou None."""
    if not install_dir or not exe:
        return None
    for lib in steam_libraries():
        for sub in ("steamapps", "SteamApps"):
            cand = os.path.join(lib, sub, "common", install_dir, exe)
            if os.path.isfile(cand):
                return cand
    return None


# -------------------------------------------------------------------- registre
def _reg_get(key: str, name: str):
    import winreg  # type: ignore
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def _reg_set(key: str, name: str, value, kind=None):
    import winreg  # type: ignore
    kind = kind or (winreg.REG_DWORD if isinstance(value, int) else winreg.REG_SZ)
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, name, 0, kind, value)


def _reg_delete(key: str, name: str):
    import winreg  # type: ignore
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, name)
    except OSError:
        pass


def _powercfg(*args) -> str:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    r = subprocess.run(["powercfg", *args], capture_output=True, text=True,
                       timeout=15, creationflags=flags)
    if r.returncode != 0:
        raise OSError((r.stderr or r.stdout or "powercfg a échoué").strip())
    return r.stdout


def active_scheme() -> Optional[str]:
    m = re.search(r"([0-9a-fA-F-]{36})", _powercfg("/getactivescheme"))
    return m.group(1).lower() if m else None


# ------------------------------------------------------------------- les tâches
@dataclass
class Tweak:
    id: str
    label: str
    why: str
    current: str = ""
    target: str = ""
    done: bool = False
    available: bool = True


def tweaks(games) -> list:
    """État actuel de chaque réglage. `games` : objets Game (avec .exe_path éventuel)."""
    out = []
    if not IS_WINDOWS:
        return out
    try:
        cur = active_scheme()
    except OSError:
        cur = None
    out.append(Tweak("power", "Plan d'alimentation : Performances élevées",
                     "Empêche le processeur de ralentir en pleine partie (micro-saccades).",
                     "Performances élevées" if cur == HIGH_PERF_GUID else "autre plan",
                     "Performances élevées", cur == HIGH_PERF_GUID))
    gm = _reg_get(GAMEBAR_KEY, "AutoGameModeEnabled")
    out.append(Tweak("gamemode", "Mode jeu de Windows",
                     "Donne la priorité au jeu et limite les tâches de fond pendant que tu joues.",
                     "activé" if gm == 1 else "désactivé / inconnu", "activé", gm == 1))
    for g in games:
        exe = getattr(g, "exe_path", None)
        if not exe:
            continue
        name = os.path.basename(exe)
        gpu = _reg_get(GPU_KEY, exe)
        out.append(Tweak(f"gpu:{exe}", f"{g.name.split(' (')[0]} : carte graphique performante",
                         "Force Windows à lancer le jeu sur ta carte NVIDIA/AMD dédiée.",
                         "performante" if gpu and "GpuPreference=2" in gpu else "automatique",
                         "performante", bool(gpu and "GpuPreference=2" in gpu)))
        lay = _reg_get(LAYERS_KEY, exe) or ""
        out.append(Tweak(f"fso:{exe}", f"{name} : optimisations plein écran désactivées",
                         "Évite la couche d'affichage de Windows qui peut ajouter des saccades.",
                         "désactivées" if "DISABLEDXMAXIMIZEDWINDOWEDMODE" in lay else "actives",
                         "désactivées", "DISABLEDXMAXIMIZEDWINDOWEDMODE" in lay))
    return out


def add_layer_flag(old: Optional[str]) -> str:
    """Ajoute l'indicateur « optimisations plein écran désactivées » à la valeur existante."""
    if not old:
        return FSO_FLAG
    if "DISABLEDXMAXIMIZEDWINDOWEDMODE" in old:
        return old
    old = old.strip()
    return old + " DISABLEDXMAXIMIZEDWINDOWEDMODE" if old.startswith("~") else "~ " + old + " DISABLEDXMAXIMIZEDWINDOWEDMODE"


def _load_backup() -> dict:
    try:
        with open(backup_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_backup(data: dict):
    os.makedirs(os.path.dirname(backup_path()), exist_ok=True)
    with open(backup_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def apply(games) -> list:
    """Applique les réglages manquants. Retourne la liste des libellés appliqués."""
    if not IS_WINDOWS:
        raise OSError("Disponible uniquement sous Windows.")
    backup = _load_backup()
    applied = []
    for t in tweaks(games):
        if t.done:
            continue
        if t.id == "power":
            backup.setdefault("power", active_scheme())
            _save_backup(backup)
            try:
                _powercfg("/setactive", HIGH_PERF_GUID)
            except OSError:  # plan absent (PC récent) : on le recrée à partir du modèle
                m = re.search(r"([0-9a-fA-F-]{36})", _powercfg("/duplicatescheme", HIGH_PERF_GUID))
                if not m:
                    raise
                _powercfg("/setactive", m.group(1))
        elif t.id == "gamemode":
            backup.setdefault("gamemode", _reg_get(GAMEBAR_KEY, "AutoGameModeEnabled"))
            _save_backup(backup)
            _reg_set(GAMEBAR_KEY, "AutoGameModeEnabled", 1)
        elif t.id.startswith("gpu:"):
            exe = t.id[4:]
            backup.setdefault("gpu", {}).setdefault(exe, _reg_get(GPU_KEY, exe))
            _save_backup(backup)
            _reg_set(GPU_KEY, exe, GPU_VALUE)
        elif t.id.startswith("fso:"):
            exe = t.id[4:]
            old = _reg_get(LAYERS_KEY, exe)
            backup.setdefault("fso", {}).setdefault(exe, old)
            _save_backup(backup)
            _reg_set(LAYERS_KEY, exe, add_layer_flag(old))
        applied.append(t.label)
    return applied


def restore() -> int:
    """Remet les valeurs d'origine sauvegardées. Retourne le nombre de réglages restaurés."""
    if not IS_WINDOWS:
        raise OSError("Disponible uniquement sous Windows.")
    b = _load_backup()
    n = 0
    if b.get("power"):
        try:
            _powercfg("/setactive", b["power"])
            n += 1
        except OSError:
            pass
    if "gamemode" in b:
        if b["gamemode"] is None:
            _reg_delete(GAMEBAR_KEY, "AutoGameModeEnabled")
        else:
            _reg_set(GAMEBAR_KEY, "AutoGameModeEnabled", int(b["gamemode"]))
        n += 1
    for exe, old in b.get("gpu", {}).items():
        _reg_delete(GPU_KEY, exe) if old is None else _reg_set(GPU_KEY, exe, old)
        n += 1
    for exe, old in b.get("fso", {}).items():
        _reg_delete(LAYERS_KEY, exe) if old is None else _reg_set(LAYERS_KEY, exe, old)
        n += 1
    try:
        os.remove(backup_path())
    except OSError:
        pass
    return n

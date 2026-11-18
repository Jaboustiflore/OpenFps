"""Catalogue de jeux (fichiers JSON) + lecture/écriture sûre des fichiers de config.

Format d'un fichier de jeu : voir games/minecraft_java.json et le README.
"""

from __future__ import annotations

import glob
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Optional

from . import formula

BACKUP_SUFFIX = ".openfps.bak"


def _resource_dir() -> str:
    # Dans l'exe PyInstaller, les données sont sous sys._MEIPASS/openfps/games
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, "openfps", "games")  # type: ignore[attr-defined]
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "games")


def render_tips(game, env: dict) -> list:
    """Remplace {{variable}} dans les conseils du jeu."""
    def sub(m):
        return str(env.get(m.group(1), m.group(0)))
    return [re.sub(r"\{\{(\w+)\}\}", sub, t) for t in game.tips]


def user_games_dir() -> str:
    return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "OpenFPS", "games")


@dataclass
class Setting:
    key: str
    formula: str
    label: str = ""
    section: str = ""


@dataclass
class Game:
    id: str
    name: str
    paths: list
    separator: str = ":"
    only_existing: bool = True
    settings: list = field(default_factory=list)
    tips: list = field(default_factory=list)
    status: str = "stable"
    custom_path: Optional[str] = None
    read_only_after: bool = False  # le jeu réécrase sa config : on la verrouille

    def candidate_paths(self):
        if self.custom_path:
            return [self.custom_path]
        return [expand(p) for p in self.paths]

    def find_all(self) -> list:
        """Tous les fichiers de config existants (plusieurs comptes/profils possibles)."""
        found = []
        for p in self.candidate_paths():
            hits = [p] if os.path.isfile(p) else sorted(glob.glob(p))
            found += [h for h in hits if os.path.isfile(h) and h not in found]
        return found

    def find_config(self) -> Optional[str]:
        for p in self.candidate_paths():
            if os.path.isfile(p):
                return p
            for hit in sorted(glob.glob(p)):  # chemins avec *
                if os.path.isfile(hit):
                    return hit
        return None


@dataclass
class Change:
    key: str
    label: str
    old: Optional[str]
    new: str


def expand(path: str) -> str:
    """Développe %VAR%, $VAR et ~ de façon portable, et normalise les séparateurs."""
    path = re.sub(r"%([^%]+)%", lambda m: os.environ.get(m.group(1), m.group(0)), path)
    path = os.path.expandvars(os.path.expanduser(path))
    return path.replace("\\", os.sep) if os.sep != "\\" else path


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def load_game_file(path: str) -> list:
    """Charge un fichier JSON. Retourne 1 jeu, ou N jeux si le fichier est un
    modèle de découverte ("discover") appliqué à tout ce qui est trouvé sur le PC."""
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    settings = [Setting(**s) for s in d["settings"]]
    common = dict(
        separator=d.get("separator", ":"),
        only_existing=d.get("only_existing", True),
        settings=settings,
        tips=d.get("tips", []),
        status=d.get("status", "stable"),
        read_only_after=d.get("read_only_after", False),
    )
    disc = d.get("discover")
    if not disc:
        return [Game(id=d["id"], name=d["name"], paths=d.get("paths", []), **common)]

    patterns = disc["glob"] if isinstance(disc["glob"], list) else [disc["glob"]]
    name_map = disc.get("name_map", {})
    grouped = {}  # nom -> fichiers (un jeu peut avoir un dossier par compte)
    for pat in patterns:
        for found in sorted(glob.glob(expand(pat))):
            m = re.search(disc["name_regex"], found.replace("\\", "/"))
            if m:
                grouped.setdefault(m.group(1), []).append(found)
    games = []
    for label, files in grouped.items():
        shown = name_map.get(label, label)
        games.append(Game(
            id=f"{d['id']}:{_slug(label)}",
            name=disc.get("name_format", "{name}").format(name=shown),
            paths=files, **common,
        ))
    return games


def load_game(path: str) -> Game:
    """Compat : premier jeu d'un fichier."""
    return load_game_file(path)[0]


def load_catalog() -> list:
    games, seen = [], set()
    for folder in (_resource_dir(), user_games_dir()):
        if not os.path.isdir(folder):
            continue
        for fn in sorted(os.listdir(folder)):
            if fn.endswith(".json"):
                try:
                    found = load_game_file(os.path.join(folder, fn))
                except (OSError, KeyError, ValueError, TypeError) as exc:
                    print(f"[openfps] jeu ignoré {fn}: {exc}", file=sys.stderr)
                    continue
                for g in found:
                    if g.id not in seen:
                        seen.add(g.id)
                        games.append(g)
    return games


# ----------------------------------------------------------------- formats

def fmt_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return f"{v:.2f}".rstrip("0").rstrip(".") if v != int(v) else str(int(v))
    return str(v)


def compute(game: Game, env: dict) -> list:
    """Évalue les formules -> liste (setting, valeur_str)."""
    out = []
    for s in game.settings:
        out.append((s, fmt_value(formula.evaluate(s.formula, env))))
    return out


def _split(line: str, sep: str):
    """Retourne (clé, valeur) si la ligne est de la forme clé<sep>valeur."""
    if sep == "vdf":  # "clé"  "valeur" (Source, Apex, CS2)
        m = re.match(r'^\s*"([^"]+)"\s+"([^"]*)"', line)
    elif sep == " ":
        m = re.match(r"^\s*(\S+)\s+(.*?)\s*$", line)
    else:
        m = re.match(rf"^\s*([^{re.escape(sep)}#;\s][^{re.escape(sep)}]*?)\s*{re.escape(sep)}\s*(.*?)\s*$", line)
    return (m.group(1), m.group(2)) if m else (None, None)


def plan(game: Game, path: str, env: dict) -> list:
    """Calcule les changements sans écrire."""
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    current = {}
    section = ""
    for line in lines:
        sm = re.match(r"^\s*\[(.+)\]\s*$", line)
        if sm:
            section = sm.group(1)
            continue
        k, v = _split(line, game.separator)
        if k is not None:
            current[(section, k)] = v
    changes = []
    for s, new in compute(game, env):
        old = current.get((s.section, s.key))
        if old is None and game.only_existing:
            continue
        shown = new
        if old is not None and old.startswith('"') and old.endswith('"'):
            shown = f'"{new}"'
        if old == shown:
            continue
        changes.append(Change(s.key, s.label or s.key, old, shown))
    return changes


def apply(game: Game, path: str, env: dict) -> list:
    """Sauvegarde puis écrit les réglages. Retourne la liste des changements."""
    changes = plan(game, path, env)
    if not changes:
        return changes
    backup = path + BACKUP_SUFFIX
    if not os.path.exists(backup):  # on garde toujours l'original d'avant OpenFPS
        shutil.copy2(path, backup)

    by_key = {}
    secs = {s.key: s.section for s in game.settings}
    for c in changes:
        by_key[(secs.get(c.key, ""), c.key)] = c

    with open(path, encoding="utf-8", errors="replace", newline="") as f:
        raw = f.read()
    nl = "\r\n" if "\r\n" in raw else "\n"
    lines = raw.splitlines()
    section, done, out = "", set(), []
    for line in lines:
        sm = re.match(r"^\s*\[(.+)\]\s*$", line)
        if sm:
            section = sm.group(1)
        k, _ = _split(line, game.separator)
        if k is not None and (section, k) in by_key:
            c = by_key[(section, k)]
            sep = game.separator
            if sep == "vdf":
                line = f'"{k}"\t\t"{c.new}"'
            else:
                line = f"{k}{sep}{c.new}" if sep != " " else f"{k} {c.new}"
            done.add((section, k))
        out.append(line)
    if not game.only_existing:
        for key, c in by_key.items():
            if key not in done:
                out.append(f"{c.key}{game.separator}{c.new}")
    _make_writable(path)

    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".openfps-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(nl.join(out) + nl)
        os.replace(tmp, path)
        if game.read_only_after:
            os.chmod(path, stat.S_IREAD)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return changes


def _make_writable(path: str):
    try:
        os.chmod(path, os.stat(path).st_mode | stat.S_IWRITE)
    except OSError:
        pass


def restore(path: str) -> bool:
    backup = path + BACKUP_SUFFIX
    if not os.path.exists(backup):
        return False
    _make_writable(path)
    shutil.copy2(backup, path)
    _make_writable(path)
    return True


def apply_all(game: Game, env: dict) -> list:
    """Optimise tous les fichiers de config trouvés pour ce jeu."""
    changes = []
    for p in game.find_all():
        changes += apply(game, p, env)
    return changes


def restore_all(game: Game) -> int:
    return sum(1 for p in game.find_all() if restore(p))

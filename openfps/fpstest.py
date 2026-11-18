"""Test FPS avant / après, à partir d'un enregistrement de temps d'image.

OpenFPS ne capture pas les images lui-même : tu enregistres une partie avec un outil gratuit
(CapFrameX, PresentMon, NVIDIA FrameView, MSI Afterburner...) puis tu importes le fichier CSV.
OpenFPS calcule FPS moyen, 1 % bas, 0,1 % bas et nombre de saccades, et compare les deux
enregistrements (avant optimisation / après).
"""

from __future__ import annotations

import csv
import json
import os
import statistics
import time
from dataclasses import asdict, dataclass

# noms de colonnes courants (comparaison insensible à la casse et aux séparateurs)
FRAMETIME_COLUMNS = ("msbetweenpresents", "msbetweendisplaychange", "frametime", "frametimems",
                     "frametime(ms)", "msframetime", "cpuframetime", "ms/frame", "msperframe")
TIME_COLUMNS = ("timeinseconds", "time", "timestamp", "presentstarttime", "timems")


@dataclass
class Stats:
    frames: int
    duration_s: float
    fps_avg: float
    fps_1_low: float
    fps_01_low: float
    stutters: int  # images plus de 2,5x plus longues que la médiane
    label: str = ""
    when: str = ""


def _key(name: str) -> str:
    return "".join(c for c in name.lower() if c.isalnum() or c in "()/")


def _num(text):
    try:
        return float(str(text).strip().replace(",", "."))
    except ValueError:
        return None


def read_frametimes(path: str) -> list:
    """Temps d'image en millisecondes, depuis un CSV (virgule ou point-virgule)."""
    with open(path, encoding="utf-8-sig", errors="replace", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        delim = ";" if sample.count(";") > sample.count(",") else ","
        rows = list(csv.reader(f, delimiter=delim))
    if not rows:
        raise ValueError("fichier vide")
    header = [_key(h) for h in rows[0]]
    col, is_time = None, False
    for cand in FRAMETIME_COLUMNS:
        if _key(cand) in header:
            col = header.index(_key(cand))
            break
    if col is None:
        for cand in TIME_COLUMNS:
            if cand in header:
                col, is_time = header.index(cand), True
                break
    if col is None:
        raise ValueError("colonne de temps d'image introuvable (attendu : MsBetweenPresents, "
                         "FrameTime ou TimeInSeconds)")
    values = [_num(r[col]) for r in rows[1:] if len(r) > col]
    values = [v for v in values if v is not None]
    if is_time:  # horodatage cumulé -> différences
        scale = 1000.0 if header[col] in ("timeinseconds", "time", "timestamp") else 1.0
        values = [(b - a) * scale for a, b in zip(values, values[1:])]
    values = [v for v in values if 0 < v < 2000]  # écarte les valeurs aberrantes
    if len(values) < 30:
        raise ValueError("enregistrement trop court (au moins 30 images)")
    return values


def stats(frametimes_ms: list, label: str = "") -> Stats:
    ft = sorted(frametimes_ms)
    n = len(ft)
    mean = sum(ft) / n

    def low(frac):
        worst = ft[max(0, int(n * (1 - frac))):]
        return 1000.0 / (sum(worst) / len(worst))

    med = statistics.median(ft)
    return Stats(
        frames=n,
        duration_s=round(sum(ft) / 1000.0, 1),
        fps_avg=round(1000.0 / mean, 1),
        fps_1_low=round(low(0.01), 1),
        fps_01_low=round(low(0.001), 1),
        stutters=sum(1 for v in ft if v > 2.5 * med),
        label=label,
        when=time.strftime("%Y-%m-%d %H:%M"),
    )


def compare(before: Stats, after: Stats) -> dict:
    """Variation en % de chaque mesure (positif = mieux ; pour les saccades, négatif = mieux)."""
    def pct(a, b):
        return round((b - a) / a * 100, 1) if a else 0.0
    return {
        "fps_avg": pct(before.fps_avg, after.fps_avg),
        "fps_1_low": pct(before.fps_1_low, after.fps_1_low),
        "fps_01_low": pct(before.fps_01_low, after.fps_01_low),
        "stutters": after.stutters - before.stutters,
    }


def _path() -> str:
    return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                        "OpenFPS", "benchmarks.json")


def load_all() -> dict:
    try:
        with open(_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_result(game_id: str, slot: str, st: Stats) -> None:
    """slot : « before » ou « after »."""
    data = load_all()
    data.setdefault(game_id, {})[slot] = asdict(st)
    os.makedirs(os.path.dirname(_path()), exist_ok=True)
    with open(_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_result(game_id: str, slot: str):
    d = load_all().get(game_id, {}).get(slot)
    return Stats(**d) if d else None

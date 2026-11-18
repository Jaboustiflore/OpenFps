"""Calcul des scores de performance (0-100) à partir du matériel détecté.

Tout est déterministe : tables de motifs + formules. Aucune IA.
Les scores sont des estimations *relatives* pour choisir des réglages,
pas des benchmarks.
"""

from __future__ import annotations

import math
import re

# (motif regex sur le nom du GPU, score 0-100). Premier motif qui correspond gagne :
# on liste donc du plus spécifique au plus général.
GPU_TABLE = [
    # NVIDIA RTX 50 / 40 / 30 / 20
    (r"RTX\s*5090", 100), (r"RTX\s*5080", 97), (r"RTX\s*5070\s*Ti", 93), (r"RTX\s*5070", 88),
    (r"RTX\s*5060", 78), (r"RTX\s*5050", 62),
    (r"RTX\s*4090", 100), (r"RTX\s*4080", 94), (r"RTX\s*4070\s*Ti", 88), (r"RTX\s*4070", 82),
    (r"RTX\s*4060\s*Ti", 74), (r"RTX\s*4060", 68), (r"RTX\s*4050", 55),
    (r"RTX\s*3090", 92), (r"RTX\s*3080", 88), (r"RTX\s*3070", 78), (r"RTX\s*3060\s*Ti", 72),
    (r"RTX\s*3060", 64), (r"RTX\s*3050", 50),
    (r"RTX\s*2080", 74), (r"RTX\s*2070", 66), (r"RTX\s*2060", 58),
    (r"GTX\s*16[56]0\s*Ti|GTX\s*1660", 48), (r"GTX\s*1650", 38),
    (r"GTX\s*1080", 62), (r"GTX\s*1070", 54), (r"GTX\s*1060", 44), (r"GTX\s*1050", 30),
    (r"GTX\s*9[78]0", 40), (r"GTX\s*[67]\d0", 22), (r"GT\s*1030", 14), (r"GT\s*\d+", 10),
    # AMD RX
    (r"RX\s*9070", 90), (r"RX\s*9060", 74),
    (r"RX\s*7900", 92), (r"RX\s*7800", 82), (r"RX\s*7700", 74), (r"RX\s*7600", 62),
    (r"RX\s*6900|RX\s*6950", 86), (r"RX\s*6800", 80), (r"RX\s*6700", 68), (r"RX\s*6600", 58),
    (r"RX\s*6500", 36), (r"RX\s*6400", 28),
    (r"RX\s*5700", 62), (r"RX\s*5600", 54), (r"RX\s*5500", 40),
    (r"RX\s*(590|580|570)", 40), (r"RX\s*(560|550)", 24), (r"RX\s*4\d0", 30),
    # Intel Arc
    (r"Arc\s*B5\d0", 66), (r"Arc\s*B5\d0|Arc\s*B3\d0", 52),
    (r"Arc\s*A7\d0", 62), (r"Arc\s*A5\d0", 52), (r"Arc\s*A3\d0", 34),
    # Apple Silicon
    (r"M[1-4]\s*(Max|Ultra)", 80), (r"M[1-4]\s*Pro", 62), (r"Apple\s*M[1-4]|\bM[1-4]\b", 48),
    # iGPU
    (r"Radeon\W*(8[0-9]0M|780M|890M)", 34), (r"Radeon\W*(680M|660M|760M|740M)", 26),
    (r"Radeon\W*Graphics|Vega\s*\d+", 20),
    (r"Iris\s*Xe|Iris\s*Plus", 18), (r"UHD|HD\s*Graphics|Intel.*Graphics", 10),
    (r"llvmpipe|basic render|vmware|virtio|svga", 4),
]


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def gpu_score(name: str, vram_gb: float = 0.0) -> float:
    """Score GPU 0-100 via la table ; à défaut, estimation par la VRAM."""
    for pat, score in GPU_TABLE:
        if re.search(pat, name or "", re.I):
            return float(score)
    if vram_gb > 0:
        # 2 Go -> 24, 4 Go -> 36, 8 Go -> 60, 16 Go -> 84
        return clamp(12 * math.log2(vram_gb) + 12, 8, 90)
    return 15.0  # inconnu : prudent


def cpu_score(threads: int, name: str = "") -> float:
    """25 * log2(threads) : 2->25, 4->50, 8->75, 16->100."""
    return clamp(25 * math.log2(max(threads, 1)), 5, 100)


def ram_score(ram_gb: float) -> float:
    """4 Go -> 25, 8 Go -> 50, 16 Go -> 100."""
    return clamp(ram_gb / 16 * 100, 5, 100) if ram_gb > 0 else 30.0


def variables(hw, target_fps: int = 144) -> dict:
    """Variables disponibles dans les formules des fichiers de jeu."""
    px = hw.screen_w * hw.screen_h
    res_ratio = px / (1920 * 1080)
    vram = hw.vram_gb if hw.vram_gb > 0 else (2.0 if hw.gpu_integrated else 4.0)
    return {
        "gpu": round(gpu_score(hw.gpu_name, hw.vram_gb), 1),
        "cpu": round(cpu_score(hw.cpu_threads, hw.cpu_name), 1),
        "ram": round(ram_score(hw.ram_gb), 1),
        "threads": hw.cpu_threads,
        "ram_gb": hw.ram_gb or 8.0,
        "vram_gb": vram,
        "width": hw.screen_w,
        "height": hw.screen_h,
        # >1 : plus de pixels que le Full HD, le GPU souffre davantage
        "res_ratio": round(res_ratio, 2),
        "integrated": 1 if hw.gpu_integrated else 0,
        # mémoire conseillée pour un jeu Java (≈40 % de la RAM, entre 2 et 8 Go)
        "ram_alloc": int(clamp(round((hw.ram_gb or 8.0) * 0.4), 2, 8)),
        "target_fps": target_fps,
    }

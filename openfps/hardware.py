"""Détection de la configuration (CPU, RAM, GPU, écran) sans dépendance externe."""

from __future__ import annotations

import ctypes
import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Hardware:
    os_name: str = ""
    cpu_name: str = "inconnu"
    cpu_threads: int = 1
    ram_gb: float = 0.0
    gpu_name: str = "inconnu"
    vram_gb: float = 0.0
    gpu_integrated: bool = False
    screen_w: int = 1920
    screen_h: int = 1080
    notes: list = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


def _run(cmd, timeout=6) -> str:
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
        return out.stdout or ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _ps(script: str) -> str:
    exe = shutil.which("powershell") or shutil.which("pwsh")
    if not exe:
        return ""
    return _run([exe, "-NoProfile", "-Command", script], timeout=12)


# ---------------------------------------------------------------- CPU / RAM

def detect_cpu():
    threads = os.cpu_count() or 1
    name = platform.processor() or "inconnu"
    system = platform.system()
    if system == "Linux":
        try:
            with open("/proc/cpuinfo", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.lower().startswith("model name"):
                        name = line.split(":", 1)[1].strip()
                        break
        except OSError:
            pass
    elif system == "Darwin":
        name = _run(["sysctl", "-n", "machdep.cpu.brand_string"]).strip() or name
    elif system == "Windows":
        out = _ps("(Get-CimInstance Win32_Processor | Select-Object -First 1).Name").strip()
        name = out or name
    return name, threads


def detect_ram_gb() -> float:
    system = platform.system()
    try:
        if system == "Linux":
            with open("/proc/meminfo", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        return int(line.split()[1]) / 1024 / 1024
        elif system == "Darwin":
            return int(_run(["sysctl", "-n", "hw.memsize"]).strip()) / 1024 ** 3
        elif system == "Windows":

            class MEMSTATUS(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            st = MEMSTATUS()
            st.dwLength = ctypes.sizeof(MEMSTATUS)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))  # type: ignore[attr-defined]
            return st.ullTotalPhys / 1024 ** 3
    except (OSError, ValueError, AttributeError):
        pass
    return 0.0


# ---------------------------------------------------------------------- GPU

_INTEGRATED = re.compile(
    r"intel.*(uhd|hd graphics|iris|graphics)|radeon(\(tm\))? graphics$|vega \d+ graphics|"
    r"radeon 7[0-9]0m|radeon 6[0-9]0m|microsoft basic|llvmpipe|virtio|vmware|svga",
    re.I,
)


def _nvidia_smi():
    if not shutil.which("nvidia-smi"):
        return None
    out = _run(
        ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"]
    )
    best = None
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2:
            try:
                vram = float(parts[1]) / 1024
            except ValueError:
                continue
            if best is None or vram > best[1]:
                best = (parts[0], vram)
    return best


def detect_gpu():
    """Retourne (nom, vram_go, intégré). Prend le GPU le plus puissant trouvé."""
    nv = _nvidia_smi()
    if nv:
        return nv[0], nv[1], False

    system = platform.system()
    candidates = []  # (nom, vram_go)

    if system == "Linux":
        out = _run(["lspci"])
        for line in out.splitlines():
            if re.search(r"VGA|3D controller|Display controller", line):
                candidates.append((line.split(": ", 1)[-1].strip(), 0.0))
        # VRAM AMD/Intel via sysfs quand disponible
        vram = 0.0
        try:
            for card in os.listdir("/sys/class/drm"):
                p = f"/sys/class/drm/{card}/device/mem_info_vram_total"
                if os.path.exists(p):
                    vram = max(vram, int(open(p).read().strip()) / 1024 ** 3)
        except (OSError, ValueError):
            pass
        if vram and candidates:
            candidates = [(n, vram) for n, _ in candidates]
    elif system == "Windows":
        out = _ps(
            "Get-CimInstance Win32_VideoController | "
            "ForEach-Object { $_.Name + '|' + $_.AdapterRAM }"
        )
        for line in out.splitlines():
            if "|" in line:
                n, _, r = line.partition("|")
                try:
                    v = int(r) / 1024 ** 3
                except ValueError:
                    v = 0.0
                candidates.append((n.strip(), v))
    elif system == "Darwin":
        out = _run(["system_profiler", "SPDisplaysDataType"])
        name = None
        for line in out.splitlines():
            m = re.match(r"\s+Chipset Model:\s*(.+)", line)
            if m:
                name = m.group(1).strip()
                candidates.append((name, 0.0))
            m = re.match(r"\s+VRAM.*:\s*(\d+)\s*(MB|GB)", line)
            if m and candidates:
                v = int(m.group(1)) / (1024 if m.group(2) == "MB" else 1)
                candidates[-1] = (candidates[-1][0], v)

    if not candidates:
        return "inconnu", 0.0, False

    from .scoring import gpu_score  # import tardif pour éviter le cycle

    name, vram = max(candidates, key=lambda c: gpu_score(c[0], c[1]))
    integrated = bool(_INTEGRATED.search(name)) and not re.search(r"\bRTX?|GTX|RX \d", name)
    return name, vram, integrated


# -------------------------------------------------------------------- Écran

def detect_screen(tk_root=None):
    """Résolution de l'écran principal. Utilise tkinter s'il est disponible."""
    try:
        if tk_root is not None:
            return tk_root.winfo_screenwidth(), tk_root.winfo_screenheight()
        import tkinter

        root = tkinter.Tk()
        root.withdraw()
        w, h = root.winfo_screenwidth(), root.winfo_screenheight()
        root.destroy()
        return w, h
    except Exception:
        pass
    if platform.system() == "Linux":
        m = re.search(r"current (\d+) x (\d+)", _run(["xrandr"]))
        if m:
            return int(m.group(1)), int(m.group(2))
    return 1920, 1080


def detect(tk_root=None, screen: bool = True) -> Hardware:
    hw = Hardware(os_name=platform.system())
    hw.cpu_name, hw.cpu_threads = detect_cpu()
    hw.ram_gb = round(detect_ram_gb(), 1)
    hw.gpu_name, hw.vram_gb, hw.gpu_integrated = detect_gpu()
    hw.vram_gb = round(hw.vram_gb, 1)
    if screen:
        hw.screen_w, hw.screen_h = detect_screen(tk_root)
    if hw.gpu_name == "inconnu":
        hw.notes.append("GPU non détecté : profil prudent appliqué.")
    if hw.ram_gb == 0:
        hw.notes.append("RAM non détectée : valeur par défaut utilisée.")
    return hw

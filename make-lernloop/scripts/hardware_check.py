#!/usr/bin/env python3
"""Liest Hardwaredaten des Laptops aus, um die Modellentscheidung (lokal vs. API) zu treffen.

Nur Standardbibliothek. Kein Netzwerkzugriff, schreibt keine Dateien.
Ausgabe: JSON auf stdout.
"""

import json
import os
import platform
import shutil
import subprocess
import sys


def _run(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def total_ram_bytes():
    system = platform.system()
    if system == "Linux":
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        return int(line.split()[1]) * 1024
        except OSError:
            return None
    if system == "Darwin":
        out = _run(["sysctl", "-n", "hw.memsize"])
        return int(out) if out.isdigit() else None
    if system == "Windows":
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MemoryStatus()
        status.dwLength = ctypes.sizeof(MemoryStatus)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return status.ullTotalPhys
    return None


def cpu_name():
    system = platform.system()
    if system == "Darwin":
        return _run(["sysctl", "-n", "machdep.cpu.brand_string"]) or platform.processor()
    if system == "Linux":
        try:
            with open("/proc/cpuinfo") as f:
                for line in f:
                    if line.startswith("model name"):
                        return line.split(":", 1)[1].strip()
        except OSError:
            pass
    return platform.processor() or platform.machine()


def gpu_hint():
    system = platform.system()
    if system == "Darwin":
        out = _run(["system_profiler", "SPDisplaysDataType"])
        return [l.strip() for l in out.splitlines() if "Chipset Model" in l or "Total Number of Cores" in l]
    if shutil.which("nvidia-smi"):
        out = _run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"])
        return out.splitlines()
    if system == "Windows":
        out = _run(["powershell", "-NoProfile", "-Command",
                    "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"])
        return out.splitlines()
    return []


def gib(value):
    return round(value / 1024**3, 1) if value else None


def main():
    home = os.path.expanduser("~")
    disk = shutil.disk_usage(home)
    ram = total_ram_bytes()
    ram_gib = gib(ram)

    if ram_gib is None:
        local_model = "unbekannt"
    elif ram_gib >= 46:
        local_model = "bis ~30B-Modelle (quantisiert) denkbar"
    elif ram_gib >= 23:
        local_model = "bis ~14B-Modelle (quantisiert) denkbar"
    elif ram_gib >= 15:
        local_model = "~7-8B-Modelle (quantisiert) denkbar"
    else:
        local_model = "lokales Modell nicht empfohlen – API nutzen"

    report = {
        "betriebssystem": f"{platform.system()} {platform.release()}",
        "os_version": platform.version(),
        "architektur": platform.machine(),
        "prozessor": cpu_name(),
        "logische_kerne": os.cpu_count(),
        "ram_gib": ram_gib,
        "speicher_home_frei_gib": gib(disk.free),
        "speicher_home_gesamt_gib": gib(disk.total),
        "gpu_hinweise": gpu_hint(),
        "python": sys.version.split()[0],
        "einschaetzung_lokales_modell": local_model,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

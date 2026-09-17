"""
F.E.D.O Core — System Monitor (v1.4)

Кроссплатформенный мониторинг состояния компьютера (Linux-first, Windows совместимо).

Даёт два уровня доступа:
  - get_system_snapshot() — структурные данные (dict) для модулей и Developer Mode;
  - get_system_summary()  — человекочитаемая сводка (текст) для LLM и ответа пользователю.
"""
import os
import platform
import time
from datetime import datetime

import psutil

try:
    import GPUtil
except Exception:
    GPUtil = None

IS_WINDOWS = os.name == "nt"


def get_primary_disk_path() -> str:
    """Основной диск: системный раздел на Windows, "/" на Linux."""
    if IS_WINDOWS:
        return os.environ.get("SystemDrive", "C:") + "\\"
    return "/"


def _get_cpu_temperature():
    """Температура CPU, если доступна в этой системе. Иначе None."""
    try:
        temps = psutil.sensors_temperatures()
    except Exception:
        return None

    if not temps:
        return None

    # Приоритет — ключевые источники (Intel/AMD), потом любой доступный
    for key in ("coretemp", "k10temp", "cpu_thermal", "cpu-thermal", "it87", "acpitz", "cpu_thermal_zone"):
        entries = temps.get(key)
        if entries:
            values = [e.current for e in entries if e.current]
            if values:
                return max(values)

    for entries in temps.values():
        values = [e.current for e in entries if e.current]
        if values:
            return max(values)

    return None


def _get_gpu_info() -> dict:
    """Информация о GPU через GPUtil (если доступен)."""
    info = {"available": False}

    if GPUtil is None:
        info["note"] = "GPUtil not installed"
        return info

    try:
        gpus = GPUtil.getGPUs()
        if not gpus:
            info["note"] = "GPU not found"
            return info

        gpu = gpus[0]
        info = {
            "available": True,
            "name": gpu.name or "GPU",
            "load": gpu.load or 0.0,
            "temperature": gpu.temperature or 0,
            "vram_used": round((gpu.memoryUsed or 0) / 1024, 1),
            "vram_total": round((gpu.memoryTotal or 0) / 1024, 1),
            "vram_free": round((gpu.memoryFree or 0) / 1024, 1),
        }
    except Exception as e:
        info["note"] = f"GPU error: {e}"

    return info


def get_top_processes(limit: int = 5) -> list:
    """Топ процессов по загрузке CPU (с краткой стабилизацией CPU-счётчиков)."""
    try:
        # Первичный проход — запустить CPU-счётчики
        for proc in psutil.process_iter(["pid", "cpu_percent"]):
            try:
                proc.cpu_percent(None)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        time.sleep(0.25)

        rows = []
        for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
            try:
                rows.append({
                    "pid": proc.info["pid"],
                    "name": (proc.info["name"] or "?")[:40],
                    "cpu": proc.info["cpu_percent"] or 0.0,
                    "mem": proc.info["memory_percent"] or 0.0,
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        rows.sort(key=lambda r: (r["cpu"], r["mem"]), reverse=True)
        return rows[:limit]
    except Exception:
        return []


def get_system_snapshot(cpu_interval: float = 0.3) -> dict:
    """
    Полный снимок состояния системы.

    :param cpu_interval: время усреднения CPU (сек). 0.3 — баланс точности и скорости.
    """
    try:
        cpu = psutil.cpu_percent(interval=cpu_interval)
    except Exception:
        cpu = 0.0

    try:
        ram = psutil.virtual_memory()
    except Exception:
        ram = None

    disk_path = get_primary_disk_path()
    try:
        disk = psutil.disk_usage(disk_path)
    except Exception:
        disk = None

    snapshot = {
        "platform": platform.platform(),
        "system": platform.system(),
        "hostname": platform.node(),
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "cpu_percent": cpu,
        "cpu_count": psutil.cpu_count(logical=True) or 0,
        "ram_percent": round(ram.percent, 1) if ram else 0.0,
        "ram_used_gb": round(ram.used / 1024 ** 3, 1) if ram else 0.0,
        "ram_total_gb": round(ram.total / 1024 ** 3, 1) if ram else 0.0,
        "disk_path": disk_path,
        "disk_percent": round(disk.percent, 1) if disk else 0.0,
        "disk_used_gb": round(disk.used / 1024 ** 3, 1) if disk else 0.0,
        "disk_total_gb": round(disk.total / 1024 ** 3, 1) if disk else 0.0,
        "cpu_temperature": _get_cpu_temperature(),
        "gpu": _get_gpu_info(),
        "top_processes": get_top_processes(5),
    }

    return snapshot


def get_system_summary(snapshot: dict | None = None) -> str:
    """Человекочитаемая сводка состояния системы (для LLM-контекста и прямого ответа)."""
    if snapshot is None:
        snapshot = get_system_snapshot()

    gpu = snapshot.get("gpu", {})
    temp = snapshot.get("cpu_temperature")

    lines = ["Состояние системы (монитор F.E.D.O):"]
    lines.append(f"Платформа: {snapshot.get('platform', 'unknown')}")

    cpu_line = f"CPU: {snapshot.get('cpu_percent', 0):.0f}% ({snapshot.get('cpu_count', 0)} ядер)"
    if temp:
        cpu_line += f", температура {temp:.0f}°C"
    lines.append(cpu_line)

    lines.append(
        f"RAM: {snapshot.get('ram_percent', 0):.0f}% "
        f"({snapshot.get('ram_used_gb', 0)} / {snapshot.get('ram_total_gb', 0)} GB)"
    )

    lines.append(
        f"Диск {snapshot.get('disk_path', '/')}: {snapshot.get('disk_percent', 0):.0f}% "
        f"({snapshot.get('disk_used_gb', 0)} / {snapshot.get('disk_total_gb', 0)} GB)"
    )

    if gpu.get("available"):
        gpu_line = (
            f"GPU: {gpu.get('name')}, загрузка {gpu.get('load', 0) * 100:.0f}%, "
            f"VRAM {gpu.get('vram_used', 0)} / {gpu.get('vram_total', 0)} GB"
        )
        if gpu.get("temperature"):
            gpu_line += f", температура {gpu.get('temperature'):.0f}°C"
        lines.append(gpu_line)
    else:
        lines.append(f"GPU: {gpu.get('note', 'не обнаружен')}")

    procs = snapshot.get("top_processes") or []
    if procs:
        top = ", ".join(
            f"{p['name']} ({p['cpu']:.0f}% CPU, {p['mem']:.0f}% RAM)" for p in procs[:3]
        )
        lines.append(f"Топ процессов: {top}")

    return "\n".join(lines)

"""Static, Fastfetch-style hardware summary for the left panel."""

from __future__ import annotations

import platform
import socket

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore[assignment]

from .telemetry import collect_battery


def _os_release() -> dict:
    data: dict = {}
    try:
        with open("/etc/os-release", encoding="utf-8") as fh:
            for line in fh:
                if "=" in line:
                    key, value = line.rstrip().split("=", 1)
                    data[key] = value.strip().strip('"')
    except OSError:
        pass
    return data


def _cpu_model() -> str:
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown CPU"


def _meminfo_kib() -> dict:
    out: dict = {}
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                key, value = line.split(":", 1)
                out[key] = int(value.strip().split()[0])
    except (OSError, ValueError, IndexError):
        pass
    return out


def _uptime_seconds() -> float | None:
    try:
        with open("/proc/uptime", encoding="utf-8") as fh:
            return float(fh.read().split()[0])
    except (OSError, IndexError, ValueError):
        return None


def _human_uptime(seconds: float) -> str:
    minutes = int(seconds // 60)
    days, minutes = divmod(minutes, 1440)
    hours, minutes = divmod(minutes, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _row(label: str, value: str) -> str:
    return f"[b #bd93f9]{label:<9}[/] {value}"


def static_info_lines(ps_root: str = "/sys/class/power_supply") -> str:
    release = _os_release()
    mem = _meminfo_kib()

    cores = threads = "?"
    if psutil is not None:
        try:
            cores = str(psutil.cpu_count(logical=False) or "?")
            threads = str(psutil.cpu_count(logical=True) or "?")
        except Exception:
            pass

    total = mem.get("MemTotal")
    swap = mem.get("SwapTotal")
    swap_free = mem.get("SwapFree")
    gib = 1024 * 1024
    ram_s = f"{total / gib:.1f} GiB" if total else "?"
    if swap:
        used = swap - (swap_free or 0)
        swap_s = f"{swap / gib:.1f} GiB ({used / gib:.2f} GiB active)"
    else:
        swap_s = "none"

    lines = [
        _row("OS", f"{release.get('PRETTY_NAME', 'Linux')} ({platform.machine()})"),
        _row("Host", socket.gethostname()),
        _row("Kernel", platform.release()),
        _row("Uptime", _human_uptime(u) if (u := _uptime_seconds()) is not None else "?"),
        _row("CPU", _cpu_model()),
        _row("Cores", f"{cores}C / {threads}T"),
        _row("Memory", ram_s),
        _row("Swap", swap_s),
    ]

    bat = collect_battery(ps_root)
    if bat is not None:
        health = bat.get("health_percent")
        health_s = f"{health:.0f}%" if health is not None else "?"
        cycles = bat.get("cycle_count")
        detail = f"{health_s} health"
        if cycles is not None:
            detail += f" · {cycles} cycles"
        lines.append(_row("Battery", detail))

    return "\n".join(lines)

"""Passive readers for /sys and /proc.

Design rules (performance & safety):
- never write to sysfs;
- never open NVIDIA device nodes or NVML unless the card is *already* active
  (reading ``power/runtime_status`` is a plain sysfs read and never wakes it);
- every reader accepts an injectable root path so tests can build fake trees;
- any missing / unreadable file degrades to ``None`` instead of raising.
"""

from __future__ import annotations

import glob
import os
import time

NVIDIA_VENDOR_ID = "0x10de"


def read_sys(path: str) -> str | None:
    """Read a sysfs/procfs text file; return None on any error (e.g. EPERM)."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read().strip()
    except (OSError, ValueError):
        return None


def read_int(path: str) -> int | None:
    """Read an integer sysfs/procfs value; None when absent or unreadable."""
    raw = read_sys(path)
    if raw is None:
        return None
    try:
        return int(raw.split()[0])
    except (IndexError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# Intel RAPL — CPU package power                                              #
# --------------------------------------------------------------------------- #

class RaplReader:
    """CPU package power from Intel RAPL energy counters (µJ, wrapping).

    Only top-level ``intel-rapl:N`` (package) domains are tracked; the nested
    ``intel-rapl:N:M`` subdomains (core/uncore/psys) are skipped so their
    energy is not double-counted inside the package total.
    """

    def __init__(self, root: str = "/sys/class/powercap") -> None:
        self._domains: list[tuple[str, str]] = []  # (name, domain dir)
        try:
            entries = sorted(os.listdir(root))
        except OSError:
            entries = []
        for entry in entries:
            if not entry.startswith("intel-rapl:"):
                continue
            suffix = entry[len("intel-rapl:"):]
            if ":" in suffix:
                continue  # subdomain — already included in the package counter
            name = read_sys(os.path.join(root, entry, "name"))
            if name:
                self._domains.append((name, os.path.join(root, entry)))
        self._prev: dict[str, tuple[float, int]] = {}

    @property
    def available(self) -> bool:
        return bool(self._domains)

    def package_power(self, now: float | None = None) -> float | None:
        """Aggregate package power in watts since the previous call.

        The first call only primes the counters and returns None.
        ``now`` (monotonic seconds) is injectable for tests.
        """
        now = time.monotonic() if now is None else now
        total = 0.0
        counted = 0
        for name, path in self._domains:
            energy = read_int(os.path.join(path, "energy_uj"))
            if energy is None:
                continue  # needs root / udev rule — graceful fallback
            prev = self._prev.get(name)
            self._prev[name] = (now, energy)
            if prev is None:
                continue
            dt = now - prev[0]
            if dt <= 0:
                continue
            delta = energy - prev[1]
            if delta < 0:  # counter wrapped past max_energy_range_uj
                max_energy = read_int(os.path.join(path, "max_energy_range_uj"))
                if max_energy is None or max_energy <= 0:
                    continue
                delta += max_energy
            total += (delta / 1e6) / dt  # µJ → J, over dt seconds → W
            counted += 1
        return total if counted else None


# --------------------------------------------------------------------------- #
# CPU aggregate usage (/proc/stat delta)                                      #
# --------------------------------------------------------------------------- #

class CpuUsage:
    """Aggregate CPU usage (%) from /proc/stat deltas — no psutil needed."""

    def __init__(self, proc_root: str = "/proc") -> None:
        self._path = os.path.join(proc_root, "stat")
        self._prev: tuple[int, int] | None = None

    @staticmethod
    def _sample(text: str) -> tuple[int, int]:
        fields = [int(v) for v in text.splitlines()[0].split()[1:]]
        idle = fields[3] + (fields[4] if len(fields) > 4 else 0)  # idle + iowait
        return idle, sum(fields)

    def percent(self) -> float | None:
        try:
            with open(self._path, encoding="utf-8") as fh:
                cur = self._sample(fh.read())
        except (OSError, IndexError, ValueError):
            return None
        if self._prev is None:
            self._prev = cur
            return None  # first call primes the counters
        prev = self._prev
        self._prev = cur
        d_idle = cur[0] - prev[0]
        d_total = cur[1] - prev[1]
        if d_total <= 0:
            return None
        return max(0.0, min(100.0, 100.0 * (1.0 - d_idle / d_total)))


# --------------------------------------------------------------------------- #
# Thermal zones                                                               #
# --------------------------------------------------------------------------- #

def collect_temps(root: str = "/sys/class/thermal") -> list[tuple[str, float]]:
    """[(zone type, °C), …]; x86_pkg_temp sorted first, hottest next."""
    zones: list[tuple[str, float]] = []
    for path in sorted(glob.glob(os.path.join(root, "thermal_zone*"))):
        ztype = read_sys(os.path.join(path, "type"))
        milli = read_int(os.path.join(path, "temp"))
        if ztype and milli is not None:
            zones.append((ztype, milli / 1000.0))
    zones.sort(key=lambda z: (z[0] != "x86_pkg_temp", -z[1], z[0]))
    return zones


# --------------------------------------------------------------------------- #
# Battery (/sys/class/power_supply/BAT*)                                      #
# --------------------------------------------------------------------------- #

def collect_battery(root: str = "/sys/class/power_supply") -> dict | None:
    """First battery: status, capacity, draw W (power_now or U·I), health."""
    for path in sorted(glob.glob(os.path.join(root, "BAT*"))):
        status = read_sys(os.path.join(path, "status"))
        if status is None:
            continue  # not a usable battery device
        data: dict = {"status": status}
        data["capacity"] = read_int(os.path.join(path, "capacity"))

        power_uw = read_int(os.path.join(path, "power_now"))
        if power_uw is None:
            volts = read_int(os.path.join(path, "voltage_now"))   # µV
            amps = read_int(os.path.join(path, "current_now"))    # µA
            if volts is not None and amps is not None:
                power_uw = volts * amps // 1_000_000              # µV·µA → µW
        data["power_w"] = None if power_uw is None else abs(power_uw) / 1e6

        full = read_int(os.path.join(path, "energy_full"))
        design = read_int(os.path.join(path, "energy_full_design"))
        if full is None or design is None:
            full = read_int(os.path.join(path, "charge_full"))
            design = read_int(os.path.join(path, "charge_full_design"))
        data["health_percent"] = (
            100.0 * full / design if full and design and design > 0 else None
        )
        data["cycle_count"] = read_int(os.path.join(path, "cycle_count"))
        return data
    return None


# --------------------------------------------------------------------------- #
# Hybrid graphics — NVIDIA dGPU, strictly passive                             #
# --------------------------------------------------------------------------- #

def find_nvidia_gpu(pci_root: str = "/sys/bus/pci/devices") -> str | None:
    """sysfs path of the first NVIDIA (0x10de) VGA/3D device, or None."""
    try:
        entries = sorted(os.listdir(pci_root))
    except OSError:
        return None
    for entry in entries:
        path = os.path.join(pci_root, entry)
        vendor = read_sys(os.path.join(path, "vendor"))
        dev_class = read_sys(os.path.join(path, "class"))
        if (
            vendor
            and vendor.lower() == NVIDIA_VENDOR_ID
            and dev_class
            and dev_class.lower().startswith("0x03")
        ):
            return path
    return None


def nvidia_report(dev_path: str | None, allow_nvml: bool = True) -> dict | None:
    """Passive dGPU report — the core safety gate.

    ``suspended`` → {"state": "suspended", "power_w": 0.0} and *nothing else
    is touched*: no NVML, no device nodes. NVML / hwmon only run when the
    card is already ``active``.
    """
    if not dev_path:
        return None
    status = read_sys(os.path.join(dev_path, "power", "runtime_status"))
    if status == "suspended":
        return {"state": "suspended", "power_w": 0.0}
    if status != "active":
        return {"state": "unknown"}
    stats: dict = {"state": "active"}
    if allow_nvml:
        stats.update(_nvml_stats() or {})
    if "power_w" not in stats or "temp_c" not in stats:
        stats.update(_hwmon_stats(dev_path))
    return stats


def _nvml_stats() -> dict | None:
    """Power / temp / VRAM via pynvml (optional dependency)."""
    try:
        import pynvml  # type: ignore[import-untyped]
    except ImportError:
        return None
    out: dict = {}
    try:
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        out["power_w"] = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0
        try:
            out["temp_c"] = pynvml.nvmlDeviceGetTemperature(
                handle, pynvml.NVML_TEMPERATURE_GPU
            )
        except pynvml.NVMLError:
            pass
        try:
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            out["vram_used_mb"] = mem.used / (1024 * 1024)
        except pynvml.NVMLError:
            pass
        return out
    except Exception:
        return out or None
    finally:
        try:
            pynvml.nvmlShutdown()
        except Exception:
            pass


def _hwmon_stats(dev_path: str) -> dict:
    """Fallback while active: hwmon power_average (µW) + temp1_input (m°C)."""
    out: dict = {}
    for hw in sorted(glob.glob(os.path.join(dev_path, "hwmon", "hwmon*"))):
        if "power_w" not in out:
            micro = read_int(os.path.join(hw, "power_average"))
            if micro is not None:
                out["power_w"] = micro / 1e6
        if "temp_c" not in out:
            milli = read_int(os.path.join(hw, "temp1_input"))
            if milli is not None:
                out["temp_c"] = milli / 1000.0
    return out

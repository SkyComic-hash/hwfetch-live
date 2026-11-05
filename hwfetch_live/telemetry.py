"""Passive readers for /sys and /proc.

Design rules (performance & safety):
- never write to sysfs;
- never open GPU device nodes or NVML unless the card is *already* active
  (reading ``power/runtime_status`` is a plain sysfs read and never wakes it);
- every reader accepts an injectable root path so tests can build fake trees;
- any missing / unreadable file degrades to ``None`` instead of raising.
"""

from __future__ import annotations

import glob
import os
import time

NVIDIA_VENDOR_ID = "0x10de"
AMD_VENDOR_ID = "0x1002"


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
# CPU Package Power — Intel & AMD RAPL + AMD hwmon fallback                  #
# --------------------------------------------------------------------------- #

class RaplReader:
    """CPU package power from Intel/AMD RAPL energy counters or AMD hwmon.

    Supports:
    - Intel RAPL (sysfs /sys/class/powercap/intel-rapl:*)
    - AMD RAPL (sysfs /sys/class/powercap/*rapl:*)
    - AMD energy sensors in hwmon (amd_energy driver)
    - AMD/Zen direct power sensors in hwmon (zenpower / k10temp)
    """

    def __init__(
        self,
        root: str = "/sys/class/powercap",
        hwmon_root: str | None = None,
    ) -> None:
        self._domains: list[tuple[str, str]] = []  # (name, domain dir)
        self._hwmon_energy: list[tuple[str, str]] = []  # (name, energy_file)
        self._hwmon_direct: list[str] = []  # direct power files (µW)
        self._prev: dict[str, tuple[float, int]] = {}

        # 1. Discover powercap domains (intel-rapl, amd-rapl, etc.)
        try:
            entries = sorted(os.listdir(root))
        except OSError:
            entries = []
        for entry in entries:
            if "rapl:" not in entry:
                continue
            suffix = entry.split("rapl:", 1)[1]
            if ":" in suffix:
                continue  # subdomain — already included in the package counter
            name = read_sys(os.path.join(root, entry, "name")) or entry
            self._domains.append((name, os.path.join(root, entry)))

        # 2. Hwmon fallback (primarily AMD amd_energy or zenpower)
        if hwmon_root is None:
            if root == "/sys/class/powercap":
                hwmon_root = "/sys/class/hwmon"
            elif os.path.exists(os.path.join(root, "hwmon")):
                hwmon_root = os.path.join(root, "hwmon")

        if not self._domains and hwmon_root and os.path.isdir(hwmon_root):
            for hw in sorted(glob.glob(os.path.join(hwmon_root, "hwmon*"))):
                driver = read_sys(os.path.join(hw, "name")) or ""
                if driver in ("amd_energy", "k10temp", "zenpower"):
                    for ef in sorted(glob.glob(os.path.join(hw, "energy*_input"))):
                        lbl = read_sys(ef.replace("_input", "_label")) or os.path.basename(ef)
                        if "core" not in lbl.lower():
                            self._hwmon_energy.append((f"{driver}_{lbl}", ef))
                    if not self._hwmon_energy:
                        for pwr in ("power1_average", "power1_input", "power_average"):
                            p = os.path.join(hw, pwr)
                            if os.path.isfile(p):
                                self._hwmon_direct.append(p)
                                break

    @property
    def available(self) -> bool:
        return bool(self._domains or self._hwmon_energy or self._hwmon_direct)

    def package_power(self, now: float | None = None) -> float | None:
        """Aggregate package power in watts since the previous call."""
        now = time.monotonic() if now is None else now

        # A. Powercap RAPL domains (Intel / AMD Zen via intel_rapl_msr)
        if self._domains:
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
                total += (delta / 1e6) / dt
                counted += 1
            return total if counted else None

        # B. AMD amd_energy in hwmon (cumulative µJ)
        if self._hwmon_energy:
            total = 0.0
            counted = 0
            for name, path in self._hwmon_energy:
                energy = read_int(path)
                if energy is None:
                    continue
                prev = self._prev.get(name)
                self._prev[name] = (now, energy)
                if prev is None:
                    continue
                dt = now - prev[0]
                if dt <= 0:
                    continue
                delta = energy - prev[1]
                if delta < 0:
                    delta += (1 << 32)
                total += (delta / 1e6) / dt
                counted += 1
            return total if counted else None

        # C. Direct power sensor (zenpower / k10temp) in µW
        if self._hwmon_direct:
            for p in self._hwmon_direct:
                val = read_int(p)
                if val is not None:
                    return val / 1e6

        return None


# Backward-compatible alias
CpuPowerReader = RaplReader


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
# Thermal zones (ACPI thermal + AMD k10temp / Intel coretemp hwmon)           #
# --------------------------------------------------------------------------- #

def _temp_priority(name: str) -> int:
    low = name.lower()
    if "tctl" in low:
        return 0
    if "tdie" in low:
        return 1
    if "x86_pkg_temp" in low or "package id" in low:
        return 2
    if "k10temp" in low or "zenpower" in low or "coretemp" in low:
        return 3
    return 10


def collect_temps(
    root: str = "/sys/class/thermal",
    hwmon_root: str | None = None,
) -> list[tuple[str, float]]:
    """[(zone type/label, °C), …]; Tctl/Tdie/x86_pkg_temp sorted first, hottest next."""
    zones: list[tuple[str, float]] = []

    # 1. Thermal zones (/sys/class/thermal)
    for path in sorted(glob.glob(os.path.join(root, "thermal_zone*"))):
        ztype = read_sys(os.path.join(path, "type"))
        milli = read_int(os.path.join(path, "temp"))
        if ztype and milli is not None:
            zones.append((ztype, milli / 1000.0))

    # 2. Hwmon zones for AMD k10temp / zenpower or Intel coretemp
    if hwmon_root is None:
        if root == "/sys/class/thermal":
            hwmon_root = "/sys/class/hwmon"
        elif os.path.exists(os.path.join(root, "hwmon")):
            hwmon_root = os.path.join(root, "hwmon")

    if hwmon_root and os.path.isdir(hwmon_root):
        for hw in sorted(glob.glob(os.path.join(hwmon_root, "hwmon*"))):
            driver_name = read_sys(os.path.join(hw, "name")) or ""
            if driver_name in ("k10temp", "zenpower", "coretemp"):
                for temp_input in sorted(glob.glob(os.path.join(hw, "temp*_input"))):
                    milli = read_int(temp_input)
                    if milli is None:
                        continue
                    lbl_file = temp_input.replace("_input", "_label")
                    label = read_sys(lbl_file)
                    tag = f"{label}" if label else f"{driver_name}: {os.path.basename(temp_input)}"
                    zones.append((tag, milli / 1000.0))

    zones.sort(key=lambda z: (_temp_priority(z[0]), -z[1], z[0]))
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
# Discrete Graphics — NVIDIA & AMD dGPU, strictly passive                     #
# --------------------------------------------------------------------------- #

def find_gpu(
    pci_root: str = "/sys/bus/pci/devices",
    vendor_filter: str | None = None,
) -> dict | None:
    """Find discrete GPU (NVIDIA or AMD) or primary GPU.

    Returns dict with {"path": str, "vendor": "nvidia" | "amd"} or None.
    """
    try:
        entries = sorted(os.listdir(pci_root))
    except OSError:
        return None

    nvidia_candidates: list[str] = []
    amd_candidates: list[str] = []

    for entry in entries:
        path = os.path.join(pci_root, entry)
        vendor = (read_sys(os.path.join(path, "vendor")) or "").lower()
        dev_class = (read_sys(os.path.join(path, "class")) or "").lower()
        if not dev_class.startswith("0x03"):
            continue

        if vendor == NVIDIA_VENDOR_ID:
            nvidia_candidates.append(path)
        elif vendor == AMD_VENDOR_ID:
            amd_candidates.append(path)

    # 1. NVIDIA dGPU
    if (vendor_filter is None or vendor_filter == "nvidia") and nvidia_candidates:
        return {"path": nvidia_candidates[0], "vendor": "nvidia"}

    # 2. AMD dGPU (prioritize 3D controller 0x0302 or boot_vga == 0)
    if (vendor_filter is None or vendor_filter == "amd") and amd_candidates:
        for path in amd_candidates:
            dev_class = (read_sys(os.path.join(path, "class")) or "").lower()
            boot_vga = read_sys(os.path.join(path, "boot_vga"))
            if dev_class.startswith("0x0302") or boot_vga == "0":
                return {"path": path, "vendor": "amd"}
        return {"path": amd_candidates[0], "vendor": "amd"}

    return None


def find_nvidia_gpu(pci_root: str = "/sys/bus/pci/devices") -> str | None:
    """sysfs path of the first NVIDIA (0x10de) VGA/3D device, or None."""
    gpu = find_gpu(pci_root, vendor_filter="nvidia")
    return gpu["path"] if gpu else None


def find_gpu_path(pci_root: str = "/sys/bus/pci/devices") -> str | None:
    """sysfs path of any discrete GPU (NVIDIA or AMD), or None."""
    gpu = find_gpu(pci_root)
    return gpu["path"] if gpu else None


def gpu_report(dev_path: str | None, allow_nvml: bool = True) -> dict | None:
    """Passive GPU report — the core safety gate for NVIDIA & AMD.

    ``suspended`` → {"state": "suspended", "power_w": 0.0} and *nothing else
    is touched*: no NVML, no device nodes. NVML / hwmon only run when the
    card is already ``active``.
    """
    if not dev_path:
        return None
    vendor = (read_sys(os.path.join(dev_path, "vendor")) or "").lower()

    status = read_sys(os.path.join(dev_path, "power", "runtime_status"))
    if status == "suspended":
        res: dict = {"state": "suspended", "power_w": 0.0}
        if vendor == AMD_VENDOR_ID:
            res["vendor"] = "amd"
        elif vendor == NVIDIA_VENDOR_ID:
            res["vendor"] = "nvidia"
        return res
    if status != "active":
        res = {"state": "unknown"}
        if vendor == AMD_VENDOR_ID:
            res["vendor"] = "amd"
        elif vendor == NVIDIA_VENDOR_ID:
            res["vendor"] = "nvidia"
        return res

    stats: dict = {"state": "active"}
    if vendor == AMD_VENDOR_ID:
        stats["vendor"] = "amd"
    elif vendor == NVIDIA_VENDOR_ID:
        stats["vendor"] = "nvidia"
    if vendor == NVIDIA_VENDOR_ID and allow_nvml:
        stats.update(_nvml_stats() or {})
    if "power_w" not in stats or "temp_c" not in stats:
        stats.update(_hwmon_stats(dev_path))
    return stats


def nvidia_report(dev_path: str | None, allow_nvml: bool = True) -> dict | None:
    """Backward-compatible alias for gpu_report."""
    return gpu_report(dev_path, allow_nvml=allow_nvml)


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
    """Fallback while active: hwmon power (µW), temp (m°C), and VRAM (bytes)."""
    out: dict = {}
    for hw in sorted(glob.glob(os.path.join(dev_path, "hwmon", "hwmon*"))):
        if "power_w" not in out:
            for pwr_name in ("power1_average", "power_average", "power1_input", "power_input"):
                micro = read_int(os.path.join(hw, pwr_name))
                if micro is not None:
                    out["power_w"] = micro / 1e6
                    break
        if "temp_c" not in out:
            for temp_name in ("temp1_input", "temp2_input"):
                milli = read_int(os.path.join(hw, temp_name))
                if milli is not None:
                    out["temp_c"] = milli / 1000.0
                    break

    # VRAM for AMD (amdgpu sysfs attribute)
    vram_path = os.path.join(dev_path, "mem_info_vram_used")
    vram_bytes = read_int(vram_path)
    if vram_bytes is not None:
        out["vram_used_mb"] = vram_bytes / (1024 * 1024)

    return out

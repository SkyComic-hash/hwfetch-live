"""Automated tests for the /sys + /proc power/telemetry parsers.

Every test builds a fake sysfs/procfs tree in tmp_path and injects it into
the readers, so no real hardware is touched.
"""

import pytest

import hwfetch_live.telemetry as tel
from hwfetch_live.telemetry import (
    CpuUsage,
    RaplReader,
    collect_battery,
    collect_temps,
    find_gpu,
    find_gpu_path,
    find_nvidia_gpu,
    gpu_report,
    nvidia_report,
)


def make_file(base, rel, content):
    path = base / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content + "\n")
    return path


# --------------------------------------------------------------------------- #
# Intel RAPL                                                                  #
# --------------------------------------------------------------------------- #

class TestRapl:
    def _build(self, root, energy=1_000_000_000):
        make_file(root, "intel-rapl:0/name", "package-0")
        make_file(root, "intel-rapl:0/energy_uj", str(energy))
        make_file(root, "intel-rapl:0/max_energy_range_uj", "262143000000")

    def test_delta_to_watts(self, tmp_path):
        self._build(tmp_path)
        reader = RaplReader(str(tmp_path))
        assert reader.available
        assert reader.package_power(now=0.0) is None  # first read primes
        make_file(tmp_path, "intel-rapl:0/energy_uj", str(1_000_000_000 + 5_000_000))
        assert reader.package_power(now=1.0) == pytest.approx(5.0)

    def test_counter_wraparound(self, tmp_path):
        make_file(tmp_path, "intel-rapl:0/name", "package-0")
        make_file(tmp_path, "intel-rapl:0/energy_uj", "1000000")
        make_file(tmp_path, "intel-rapl:0/max_energy_range_uj", "2000000")
        reader = RaplReader(str(tmp_path))
        reader.package_power(now=0.0)
        # counter wrapped: real delta = (2000000 - 1000000) + 500000 µJ = 1.5 J
        make_file(tmp_path, "intel-rapl:0/energy_uj", "500000")
        assert reader.package_power(now=1.0) == pytest.approx(1.5)

    def test_permission_fallback(self, tmp_path):
        # no readable files at all → available=False, power=None (no crash)
        reader = RaplReader(str(tmp_path / "missing"))
        assert not reader.available
        assert reader.package_power() is None

    def test_subdomains_skipped(self, tmp_path):
        make_file(tmp_path, "intel-rapl:0/name", "package-0")
        make_file(tmp_path, "intel-rapl:0/energy_uj", "1000")
        make_file(tmp_path, "intel-rapl:0:0/name", "core")
        make_file(tmp_path, "intel-rapl:0:0/energy_uj", "999")
        make_file(tmp_path, "intel-rapl:0:1/name", "uncore")
        make_file(tmp_path, "intel-rapl:0:1/energy_uj", "888")
        reader = RaplReader(str(tmp_path))
        assert len(reader._domains) == 1  # only the package domain counts


# --------------------------------------------------------------------------- #
# CPU usage (/proc/stat)                                                      #
# --------------------------------------------------------------------------- #

def test_cpu_percent_delta(tmp_path):
    (tmp_path / "stat").write_text("cpu  100 0 100 800 0 0 0 0 0 0\n")
    cpu = CpuUsage(str(tmp_path))
    assert cpu.percent() is None  # first call primes the counters
    # total +200, idle +100 → 50 % busy
    (tmp_path / "stat").write_text("cpu  200 0 100 900 0 0 0 0 0 0\n")
    assert cpu.percent() == pytest.approx(50.0)


def test_cpu_percent_missing_file(tmp_path):
    assert CpuUsage(str(tmp_path / "nope")).percent() is None


# --------------------------------------------------------------------------- #
# Battery                                                                     #
# --------------------------------------------------------------------------- #

def test_battery_power_now(tmp_path):
    bat = tmp_path / "BAT0"
    make_file(bat, "status", "Discharging")
    make_file(bat, "capacity", "88")
    make_file(bat, "power_now", "12000000")          # µW → 12 W
    make_file(bat, "energy_full", "50000000")        # µWh
    make_file(bat, "energy_full_design", "80000000")
    make_file(bat, "cycle_count", "300")
    data = collect_battery(str(tmp_path))
    assert data["power_w"] == pytest.approx(12.0)
    assert data["health_percent"] == pytest.approx(62.5)
    assert data["capacity"] == 88
    assert data["cycle_count"] == 300


def test_battery_current_voltage_fallback(tmp_path):
    bat = tmp_path / "BAT1"
    make_file(bat, "status", "Discharging")
    make_file(bat, "current_now", "1500000")    # µA → 1.5 A
    make_file(bat, "voltage_now", "11000000")   # µV → 11 V → 16.5 W
    make_file(bat, "charge_full", "4000000")    # µAh
    make_file(bat, "charge_full_design", "5000000")
    data = collect_battery(str(tmp_path))
    assert data["power_w"] == pytest.approx(16.5)
    assert data["health_percent"] == pytest.approx(80.0)


def test_battery_absent(tmp_path):
    assert collect_battery(str(tmp_path)) is None


# --------------------------------------------------------------------------- #
# Thermal zones                                                               #
# --------------------------------------------------------------------------- #

def test_collect_temps_sorted(tmp_path):
    make_file(tmp_path, "thermal_zone0/type", "acpitz")
    make_file(tmp_path, "thermal_zone0/temp", "45000")
    make_file(tmp_path, "thermal_zone1/type", "x86_pkg_temp")
    make_file(tmp_path, "thermal_zone1/temp", "62000")
    zones = collect_temps(str(tmp_path))
    assert zones == [("x86_pkg_temp", 62.0), ("acpitz", 45.0)]


# --------------------------------------------------------------------------- #
# NVIDIA dGPU — the safety gate                                               #
# --------------------------------------------------------------------------- #

def test_find_nvidia_gpu(tmp_path):
    make_file(tmp_path, "0000:00:02.0/vendor", "0x8086")
    make_file(tmp_path, "0000:00:02.0/class", "0x030000")
    make_file(tmp_path, "0000:01:00.0/vendor", "0x10DE")
    make_file(tmp_path, "0000:01:00.0/class", "0x030200")
    found = find_nvidia_gpu(str(tmp_path))
    assert found is not None and found.endswith("0000:01:00.0")


def test_find_nvidia_gpu_absent(tmp_path):
    make_file(tmp_path, "0000:00:02.0/vendor", "0x8086")
    make_file(tmp_path, "0000:00:02.0/class", "0x030000")
    assert find_nvidia_gpu(str(tmp_path)) is None


def test_suspended_never_touches_nvml(tmp_path, monkeypatch):
    """The core safety contract: suspended dGPU → zero side effects."""
    dev = tmp_path / "0000:01:00.0"
    make_file(dev, "power/runtime_status", "suspended")

    def _boom():
        raise AssertionError("NVML must not be touched while the dGPU sleeps")

    monkeypatch.setattr(tel, "_nvml_stats", _boom)
    report = nvidia_report(str(dev), allow_nvml=True)
    assert report == {"state": "suspended", "power_w": 0.0}


def test_active_uses_hwmon_fallback(tmp_path, monkeypatch):
    dev = tmp_path / "0000:01:00.0"
    make_file(dev, "power/runtime_status", "active")
    make_file(dev, "hwmon/hwmon2/power_average", "8500000")  # µW → 8.5 W
    make_file(dev, "hwmon/hwmon2/temp1_input", "57000")      # m°C → 57 °C
    monkeypatch.setattr(tel, "_nvml_stats", lambda: None)    # NVML absent
    report = nvidia_report(str(dev), allow_nvml=True)
    assert report["state"] == "active"
    assert report["power_w"] == pytest.approx(8.5)
    assert report["temp_c"] == pytest.approx(57.0)


def test_unknown_runtime_status(tmp_path, monkeypatch):
    dev = tmp_path / "0000:01:00.0"
    make_file(dev, "power/runtime_status", "unsupport")
    monkeypatch.setattr(tel, "_nvml_stats", lambda: None)
    assert nvidia_report(str(dev)) == {"state": "unknown"}


def test_no_gpu_at_all(tmp_path):
    assert nvidia_report(None) is None


# --------------------------------------------------------------------------- #
# AMD specific integration tests                                              #
# --------------------------------------------------------------------------- #

def test_amd_rapl_powercap(tmp_path):
    make_file(tmp_path, "amd-rapl:0/name", "package-0")
    make_file(tmp_path, "amd-rapl:0/energy_uj", "10000000")
    make_file(tmp_path, "amd-rapl:0/max_energy_range_uj", "262143000000")
    reader = RaplReader(str(tmp_path))
    assert reader.available
    assert reader.package_power(now=0.0) is None
    make_file(tmp_path, "amd-rapl:0/energy_uj", "18000000")  # +8 J in 1 s -> 8.0 W
    assert reader.package_power(now=1.0) == pytest.approx(8.0)


def test_amd_energy_hwmon(tmp_path):
    hw = tmp_path / "hwmon" / "hwmon0"
    make_file(hw, "name", "amd_energy")
    make_file(hw, "energy1_input", "5000000")
    make_file(hw, "energy1_label", "Esocket0")
    reader = RaplReader(root=str(tmp_path / "empty_powercap"), hwmon_root=str(tmp_path / "hwmon"))
    assert reader.available
    assert reader.package_power(now=0.0) is None
    make_file(hw, "energy1_input", "15000000")  # +10 J in 1 s -> 10.0 W
    assert reader.package_power(now=1.0) == pytest.approx(10.0)


def test_amd_zenpower_direct_watts(tmp_path):
    hw = tmp_path / "hwmon" / "hwmon1"
    make_file(hw, "name", "zenpower")
    make_file(hw, "power1_average", "25000000")  # 25 W
    reader = RaplReader(root=str(tmp_path / "empty"), hwmon_root=str(tmp_path / "hwmon"))
    assert reader.available
    assert reader.package_power() == pytest.approx(25.0)


def test_amd_k10temp_thermals_prioritized(tmp_path):
    # ACPI thermal zone at 50 °C
    make_file(tmp_path, "thermal/thermal_zone0/type", "acpitz")
    make_file(tmp_path, "thermal/thermal_zone0/temp", "50000")

    # AMD k10temp in hwmon: Tctl at 68 °C and Tdie at 65 °C
    hw = tmp_path / "hwmon" / "hwmon0"
    make_file(hw, "name", "k10temp")
    make_file(hw, "temp1_input", "68000")
    make_file(hw, "temp1_label", "Tctl")
    make_file(hw, "temp2_input", "65000")
    make_file(hw, "temp2_label", "Tdie")

    zones = collect_temps(root=str(tmp_path / "thermal"), hwmon_root=str(tmp_path / "hwmon"))
    # Tctl must be sorted first, then Tdie, then other zones
    assert zones[0] == ("Tctl", 68.0)
    assert zones[1] == ("Tdie", 65.0)
    assert zones[2] == ("acpitz", 50.0)


def test_find_amd_dgpu_and_report(tmp_path):
    # Integrated Intel/AMD VGA card
    make_file(tmp_path, "0000:00:02.0/vendor", "0x8086")
    make_file(tmp_path, "0000:00:02.0/class", "0x030000")
    make_file(tmp_path, "0000:00:02.0/boot_vga", "1")

    # Discrete AMD Radeon GPU
    dev = tmp_path / "0000:03:00.0"
    make_file(dev, "vendor", "0x1002")
    make_file(dev, "class", "0x030000")
    make_file(dev, "boot_vga", "0")
    make_file(dev, "power/runtime_status", "suspended")

    found = find_gpu(str(tmp_path))
    assert found is not None
    assert found["vendor"] == "amd"
    assert found["path"].endswith("0000:03:00.0")

    # Passive sleep report for AMD dGPU
    report = gpu_report(str(dev))
    assert report["state"] == "suspended"
    assert report["power_w"] == 0.0
    assert report["vendor"] == "amd"

    # Active report with AMD hwmon and VRAM
    make_file(dev, "power/runtime_status", "active")
    make_file(dev, "hwmon/hwmon4/power1_average", "45000000")  # 45 W
    make_file(dev, "hwmon/hwmon4/temp1_input", "62000")       # 62 °C
    make_file(dev, "mem_info_vram_used", str(2048 * 1024 * 1024))  # 2048 MiB

    active_report = gpu_report(str(dev))
    assert active_report["state"] == "active"
    assert active_report["power_w"] == pytest.approx(45.0)
    assert active_report["temp_c"] == pytest.approx(62.0)
    assert active_report["vram_used_mb"] == pytest.approx(2048.0)
    assert active_report["vendor"] == "amd"


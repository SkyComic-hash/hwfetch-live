"""hwfetch-live — Textual TUI application and console entry point."""

from __future__ import annotations

import os
import signal

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Input, Static

from .procs import ProcessSampler
from .staticinfo import static_info_lines
from .telemetry import (
    CpuUsage,
    RaplReader,
    collect_battery,
    collect_temps,
    find_gpu_path,
    find_nvidia_gpu,
    gpu_report,
    nvidia_report,
)

GPU_POLL_FAST = 1.0
GPU_POLL_SLOW = 5.0


def _bar(pct: float, width: int = 20) -> str:
    filled = max(0, min(width, int(round(pct / 100 * width))))
    return "[#ff79c6]" + "█" * filled + "[/][#3b4252]" + "░" * (width - filled) + "[/]"


class KillConfirm(ModalScreen[bool]):
    """Confirmation dialog before SIGTERM-ing a process."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, pid: int, name: str) -> None:
        super().__init__()
        self._pid = pid
        self._name = name

    def compose(self) -> ComposeResult:
        with Vertical(id="kill-dialog"):
            yield Static(
                f"Kill [b #ff5555]{self._name}[/b] (PID {self._pid}) with SIGTERM?"
            )
            yield Static(
                "[dim]Type y / yes to confirm — Esc or anything else cancels.[/dim]"
            )
            yield Input(placeholder="y")

    @on(Input.Submitted)
    def _submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip().lower() in ("y", "yes"))

    def action_cancel(self) -> None:
        self.dismiss(False)


class HWFetchLive(App[None]):
    CSS_PATH = "styles.tcss"
    TITLE = "hwfetch-live"

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("ctrl+c", "quit", "Quit"),
        ("k", "kill_process", "Kill process"),
        ("p", "toggle_gpu_poll", "dGPU poll 1s/5s"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._rapl = RaplReader()
        self._cpu = CpuUsage()
        self._gpu_path = find_gpu_path()
        self._proc_sampler = ProcessSampler(top_n=5)
        self._gpu_interval = GPU_POLL_FAST
        self._gpu_timer = None
        self._top_procs: list[dict] = []

    # ---- layout ---------------------------------------------------------- #

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main"):
            yield Static("", id="left", markup=True)
            with Vertical(id="right"):
                yield Static("", id="gpu", markup=True)
                yield Static("", id="cpu-live", markup=True)
                yield Static("", id="battery", markup=True)
        yield DataTable(id="hogs")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#hogs", DataTable)
        table.add_columns("PID", "USER", "PROCESS", "CPU %", "MEM %")
        self.query_one("#left", Static).update(static_info_lines())
        self.query_one("#gpu", Static).update("[dim]dGPU: probing …[/dim]")
        self.tick_telemetry()
        self.tick_gpu()
        self.set_interval(1.0, self.tick_telemetry)
        self._gpu_timer = self.set_interval(self._gpu_interval, self.tick_gpu)

    # ---- background collection (never blocks the UI thread) --------------- #

    @work(thread=True, exclusive=True, group="telemetry")
    def tick_telemetry(self) -> None:
        power = self._rapl.package_power()
        cpu_pct = self._cpu.percent()
        temps = collect_temps()
        battery = collect_battery()
        procs = self._proc_sampler.sample()
        try:
            self.call_from_thread(
                self.apply_telemetry, power, cpu_pct, temps, battery, procs
            )
        except RuntimeError:
            pass  # app shutting down

    @work(thread=True, exclusive=True, group="gpu")
    def tick_gpu(self) -> None:
        report = gpu_report(self._gpu_path)
        try:
            self.call_from_thread(self.apply_gpu, report)
        except RuntimeError:
            pass

    # ---- rendering -------------------------------------------------------- #

    def apply_telemetry(self, power, cpu_pct, temps, battery, procs) -> None:
        if cpu_pct is None:
            cpu_line = "[b #ff79c6]CPU[/] [dim]sampling …[/dim]"
        else:
            cpu_line = f"[b #ff79c6]CPU[/] {_bar(cpu_pct)} [#8be9fd]{cpu_pct:5.1f}%[/]"
        if power is None:
            power_line = (
                "[b #ff79c6]PKG PWR[/] [dim]n/a — RAPL/hwmon unreadable "
                "(install packaging/99-intel-rapl.rules or run as root)[/dim]"
            )
        else:
            power_line = f"[b #ff79c6]PKG PWR[/] [#f1fa8c]{power:6.2f} W[/]"
        temp_line = (
            "  ·  ".join(f"{name} [#50fa7b]{t:.0f}°C[/]" for name, t in temps[:4])
            or "[dim]no thermal zones[/dim]"
        )
        self.query_one("#cpu-live", Static).update(
            "\n".join([cpu_line, power_line, temp_line])
        )

        if battery is None:
            bat_text = "[dim]no battery — AC-only machine[/dim]"
        else:
            cap = battery.get("capacity")
            cap_s = f"{cap:.0f}%" if cap is not None else "?"
            status = battery.get("status") or "?"
            color = (
                "#50fa7b" if status == "Charging"
                else "#f1fa8c" if status == "Discharging"
                else "#8be9fd"
            )
            arrow = (
                "↓" if status == "Discharging"
                else "↑" if status == "Charging"
                else "•"
            )
            draw = battery.get("power_w")
            draw_s = f"{draw:.2f} W" if draw is not None else "n/a"
            health = battery.get("health_percent")
            health_s = f"{health:.0f}%" if health is not None else "?"
            cycles = battery.get("cycle_count")
            bat_text = "\n".join(
                [
                    f"[b #ff79c6]BAT[/] [#8be9fd]{cap_s}[/] [{color}]{status} {arrow}[/]",
                    f"[b #ff79c6]DRAW[/] [#f1fa8c]{draw_s}[/]   "
                    f"[b #ff79c6]HEALTH[/] {health_s}   "
                    f"[b #ff79c6]CYCLES[/] {cycles if cycles is not None else '?'}",
                ]
            )
        self.query_one("#battery", Static).update(bat_text)

        table = self.query_one("#hogs", DataTable)
        table.clear(columns=False)
        self._top_procs = procs
        for p in procs:
            table.add_row(
                str(p["pid"]), p["user"], p["name"], f"{p['cpu']:.1f}", f"{p['mem']:.1f}"
            )

    def apply_gpu(self, report) -> None:
        if report is None:
            text = "[b #ff79c6]dGPU[/] [dim]none detected — iGPU only[/dim]"
        elif report["state"] == "suspended":
            v_name = report.get("vendor", "dGPU").upper()
            text = (
                f"[b #ff79c6]dGPU ({v_name})[/] [#50fa7b][ SLEEP / 0.0 W ][/]"
                " [dim]runtime_status=suspended (D3cold) — left untouched[/dim]"
            )
        elif report["state"] == "unknown":
            v_name = report.get("vendor", "dGPU").upper()
            text = f"[b #ff79c6]dGPU ({v_name})[/] [dim]runtime_status unavailable[/dim]"
        else:
            v_name = report.get("vendor", "dGPU").upper()
            watts = report.get("power_w")
            temp = report.get("temp_c")
            vram = report.get("vram_used_mb")
            parts = [f"[b #ff79c6]dGPU ({v_name})[/] [#f1fa8c][ ACTIVE ][/]"]
            parts.append(
                f"[#f1fa8c]{watts:.2f} W[/]" if watts is not None
                else "[dim]power n/a[/dim]"
            )
            parts.append(
                f"{temp:.0f}°C" if temp is not None else "[dim]temp n/a[/dim]"
            )
            parts.append(
                f"VRAM {vram:.0f} MiB" if vram is not None else "[dim]vram n/a[/dim]"
            )
            text = "   ".join(parts)
        self.query_one("#gpu", Static).update(text)

    # ---- actions ----------------------------------------------------------- #

    def action_kill_process(self) -> None:
        row = self.query_one("#hogs", DataTable).cursor_row
        if not (0 <= row < len(self._top_procs)):
            self.notify("Highlight a process in the table first (↑/↓).", severity="warning")
            return
        proc = self._top_procs[row]
        pid, name = proc["pid"], proc["name"]
        self.push_screen(
            KillConfirm(pid, name), lambda ok: self._do_kill(pid, name, ok)
        )

    def _do_kill(self, pid: int, name: str, confirmed: bool) -> None:
        if not confirmed:
            return
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            self.notify(f"{name} ({pid}) already exited.", severity="warning")
        except PermissionError:
            self.notify(f"Not allowed to kill {name} ({pid}).", severity="error")
        else:
            self.notify(f"SIGTERM sent to {name} ({pid}).")

    def action_toggle_gpu_poll(self) -> None:
        self._gpu_interval = (
            GPU_POLL_SLOW if self._gpu_interval == GPU_POLL_FAST else GPU_POLL_FAST
        )
        if self._gpu_timer is not None:
            self._gpu_timer.stop()
        self._gpu_timer = self.set_interval(self._gpu_interval, self.tick_gpu)
        self.notify(f"dGPU polling interval: {self._gpu_interval:.0f} s")


def main() -> None:
    try:
        HWFetchLive().run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

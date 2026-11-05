"""hwfetch-live — Textual TUI application and console entry point."""

from __future__ import annotations

import os
import signal

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Input, OptionList, Static
from textual.widgets.option_list import Option

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
from .themes import THEMES, Theme, get_theme, load_saved_theme, save_theme

GPU_POLL_FAST = 1.0
GPU_POLL_SLOW = 5.0


def _bar(pct: float, width: int = 20, theme: Theme | None = None) -> str:
    filled = max(0, min(width, int(round(pct / 100 * width))))
    color_fill = theme.bar_filled if theme else "#ff79c6"
    color_empty = theme.bar_empty if theme else "#3b4252"
    return f"[{color_fill}]" + "█" * filled + f"[/][{color_empty}]" + "░" * (width - filled) + "[/]"


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


class ThemePicker(ModalScreen[str | None]):
    """Modal screen for interactive theme selection with live preview like btop."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("enter", "confirm", "Apply"),
    ]

    def __init__(self, current_theme_name: str, on_preview=None) -> None:
        super().__init__()
        self._current = current_theme_name
        self._selected = current_theme_name
        self._on_preview = on_preview

    def compose(self) -> ComposeResult:
        with Vertical(id="theme-dialog"):
            yield Static("Select UI Theme", id="theme-title")
            yield Static("↑/↓ to preview · Enter to apply · Esc to cancel", id="theme-help")
            options = []
            for t_id, t in THEMES.items():
                mark = "● " if t_id == self._current else "○ "
                options.append(Option(f"{mark}{t.display_name}", id=t_id))
            yield OptionList(*options, id="theme-options")

    def on_mount(self) -> None:
        opt_list = self.query_one("#theme-options", OptionList)
        for idx, (t_id, _) in enumerate(THEMES.items()):
            if t_id == self._current:
                opt_list.highlighted = idx
                break

    @on(OptionList.OptionHighlighted)
    def _highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_id and self._on_preview:
            self._selected = str(event.option_id)
            self._on_preview(str(event.option_id))

    @on(OptionList.OptionSelected)
    def _selected_event(self, event: OptionList.OptionSelected) -> None:
        if event.option_id:
            self.dismiss(str(event.option_id))

    def action_confirm(self) -> None:
        self.dismiss(self._selected)

    def action_cancel(self) -> None:
        self.dismiss(None)


class HWFetchLive(App[None]):
    CSS_PATH = "styles.tcss"
    TITLE = "hwfetch-live"

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("ctrl+c", "quit", "Quit"),
        ("k", "kill_process", "Kill process"),
        ("p", "toggle_gpu_poll", "dGPU poll 1s/5s"),
        ("t", "open_theme_picker", "Themes"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._current_theme: Theme = get_theme(load_saved_theme())
        self._rapl = RaplReader()
        self._cpu = CpuUsage()
        self._gpu_path = find_gpu_path()
        self._proc_sampler = ProcessSampler(top_n=5)
        self._gpu_interval = GPU_POLL_FAST
        self._gpu_timer = None
        self._top_procs: list[dict] = []
        self._last_telemetry: tuple | None = None
        self._last_gpu_report: dict | None = None

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
        self.apply_theme_styles(self._current_theme)
        self.query_one("#left", Static).update(static_info_lines(theme=self._current_theme))
        self.query_one("#gpu", Static).update("[dim]dGPU: probing …[/dim]")
        self.tick_telemetry()
        self.tick_gpu()
        self.set_interval(1.0, self.tick_telemetry)
        self._gpu_timer = self.set_interval(self._gpu_interval, self.tick_gpu)

    # ---- theme management ------------------------------------------------ #

    def apply_theme_styles(self, theme: Theme) -> None:
        self._current_theme = theme
        try:
            self.screen.styles.background = theme.bg

            header = self.query_one(Header)
            header.styles.background = theme.header_bg
            header.styles.color = theme.accent

            footer = self.query_one(Footer)
            footer.styles.background = theme.header_bg
            footer.styles.color = theme.accent_alt

            left = self.query_one("#left", Static)
            left.styles.border = ("round", theme.border_left)
            left.styles.background = theme.surface_left

            for card_id in ("#gpu", "#cpu-live", "#battery"):
                card = self.query_one(card_id, Static)
                card.styles.border = ("round", theme.border_right)
                card.styles.background = theme.surface_right

            hogs = self.query_one("#hogs", DataTable)
            hogs.styles.border = ("round", theme.border_hogs)
            hogs.styles.background = theme.surface_hogs

            self.query_one("#left", Static).update(static_info_lines(theme=theme))

            if self._last_telemetry:
                self.apply_telemetry(*self._last_telemetry)
            if self._last_gpu_report is not None:
                self.apply_gpu(self._last_gpu_report)
        except Exception:
            pass

    def set_theme(self, theme_name: str, persist: bool = False) -> None:
        theme = get_theme(theme_name)
        self.apply_theme_styles(theme)
        if persist:
            save_theme(theme_name)

    def action_open_theme_picker(self) -> None:
        initial_name = self._current_theme.name

        def on_preview(name: str) -> None:
            self.set_theme(name, persist=False)

        def on_dismiss(selected: str | None) -> None:
            if selected:
                self.set_theme(selected, persist=True)
                self.notify(f"Theme applied: {THEMES[selected].display_name}")
            else:
                self.set_theme(initial_name, persist=False)

        self.push_screen(ThemePicker(initial_name, on_preview=on_preview), on_dismiss)

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
        self._last_telemetry = (power, cpu_pct, temps, battery, procs)
        t = self._current_theme

        if cpu_pct is None:
            cpu_line = f"[b {t.accent}]CPU[/] [dim]sampling …[/dim]"
        else:
            cpu_line = f"[b {t.accent}]CPU[/] {_bar(cpu_pct, theme=t)} [{t.cyan}]{cpu_pct:5.1f}%[/]"

        if power is None:
            power_line = (
                f"[b {t.accent}]PKG PWR[/] [dim]n/a — RAPL/hwmon unreadable "
                "(install packaging/99-intel-rapl.rules or run as root)[/dim]"
            )
        else:
            power_line = f"[b {t.accent}]PKG PWR[/] [{t.yellow}]{power:6.2f} W[/]"

        temp_line = (
            "  ·  ".join(f"{name} [{t.green}]{temp:.0f}°C[/]" for name, temp in temps[:4])
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
                t.green if status == "Charging"
                else t.yellow if status == "Discharging"
                else t.cyan
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
                    f"[b {t.accent}]BAT[/] [{t.cyan}]{cap_s}[/] [{color}]{status} {arrow}[/]",
                    f"[b {t.accent}]DRAW[/] [{t.yellow}]{draw_s}[/]   "
                    f"[b {t.accent}]HEALTH[/] {health_s}   "
                    f"[b {t.accent}]CYCLES[/] {cycles if cycles is not None else '?'}",
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
        self._last_gpu_report = report
        t = self._current_theme

        if report is None:
            text = f"[b {t.accent}]dGPU[/] [dim]none detected — iGPU only[/dim]"
        elif report["state"] == "suspended":
            v_name = report.get("vendor", "dGPU").upper()
            text = (
                f"[b {t.accent}]dGPU ({v_name})[/] [{t.green}][ SLEEP / 0.0 W ][/]"
                " [dim]runtime_status=suspended (D3cold) — left untouched[/dim]"
            )
        elif report["state"] == "unknown":
            v_name = report.get("vendor", "dGPU").upper()
            text = f"[b {t.accent}]dGPU ({v_name})[/] [dim]runtime_status unavailable[/dim]"
        else:
            v_name = report.get("vendor", "dGPU").upper()
            watts = report.get("power_w")
            temp = report.get("temp_c")
            vram = report.get("vram_used_mb")
            parts = [f"[b {t.accent}]dGPU ({v_name})[/] [{t.yellow}][ ACTIVE ][/]"]
            parts.append(
                f"[{t.yellow}]{watts:.2f} W[/]" if watts is not None
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

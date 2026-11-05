"""Top power hogs — processes ranked by CPU (energy-impact proxy)."""

from __future__ import annotations

import psutil


class ProcessSampler:
    """Persistent psutil sampling so ``cpu_percent`` yields real deltas.

    ``psutil.process_iter`` caches ``Process`` objects between calls, so the
    per-process CPU counters keep accumulating across ticks.
    """

    def __init__(self, top_n: int = 5) -> None:
        self.top_n = top_n
        for proc in psutil.process_iter():  # prime the counters once
            try:
                proc.cpu_percent(None)
            except psutil.Error:
                pass

    def sample(self, top_n: int | None = None) -> list[dict]:
        top_n = top_n or self.top_n
        rows: list[dict] = []
        for proc in psutil.process_iter(
            ["pid", "name", "username", "memory_percent"]
        ):
            try:
                cpu = proc.cpu_percent(None)
                info = proc.info
            except psutil.Error:
                continue
            rows.append(
                {
                    "pid": info["pid"],
                    "name": (info["name"] or "?")[:24],
                    "user": info["username"] or "?",
                    "cpu": cpu,
                    "mem": info["memory_percent"] or 0.0,
                }
            )
        rows.sort(key=lambda r: (-r["cpu"], -r["mem"]))
        return rows[:top_n]

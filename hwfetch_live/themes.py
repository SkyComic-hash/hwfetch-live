"""Theme definitions and configuration persistence for hwfetch-live."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

CONFIG_DIR = os.path.expanduser("~/.config/hwfetch-live")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")


@dataclass(frozen=True)
class Theme:
    name: str
    display_name: str
    # Surfaces & backgrounds
    bg: str
    header_bg: str
    surface_left: str
    surface_right: str
    surface_hogs: str
    # Borders
    border_left: str
    border_right: str
    border_hogs: str
    # Telemetry accents
    accent: str        # main brand/labels (e.g. pink in dracula)
    accent_alt: str    # secondary brand/labels (e.g. purple)
    cyan: str          # info/values (e.g. #8be9fd)
    green: str         # success / low temp / charging
    yellow: str        # warning / power watts / discharging
    red: str           # high load / danger / kill
    text: str          # primary text
    dim: str           # muted text
    bar_filled: str    # CPU bar active
    bar_empty: str     # CPU bar empty


THEMES: dict[str, Theme] = {
    "dracula": Theme(
        name="dracula",
        display_name="🧛 Dracula Neon",
        bg="#0b0e14",
        header_bg="#16121f",
        surface_left="#0f0d1a",
        surface_right="#0d1420",
        surface_hogs="#170d18",
        border_left="#bd93f9",
        border_right="#8be9fd",
        border_hogs="#ff79c6",
        accent="#ff79c6",
        accent_alt="#bd93f9",
        cyan="#8be9fd",
        green="#50fa7b",
        yellow="#f1fa8c",
        red="#ff5555",
        text="#f8f8f2",
        dim="#6272a4",
        bar_filled="#ff79c6",
        bar_empty="#3b4252",
    ),
    "nord": Theme(
        name="nord",
        display_name="❄️ Nord Frost",
        bg="#242933",
        header_bg="#2e3440",
        surface_left="#2e3440",
        surface_right="#2e3440",
        surface_hogs="#2e3440",
        border_left="#88c0d0",
        border_right="#81a1c1",
        border_hogs="#5e81ac",
        accent="#88c0d0",
        accent_alt="#81a1c1",
        cyan="#8fbcbb",
        green="#a3be8c",
        yellow="#ebcb8b",
        red="#bf616a",
        text="#eceff4",
        dim="#4c566a",
        bar_filled="#88c0d0",
        bar_empty="#3b4252",
    ),
    "catppuccin": Theme(
        name="catppuccin",
        display_name="☕ Catppuccin Mocha",
        bg="#181825",
        header_bg="#1e1e2e",
        surface_left="#1e1e2e",
        surface_right="#1e1e2e",
        surface_hogs="#1e1e2e",
        border_left="#cba6f7",
        border_right="#89b4fa",
        border_hogs="#f5c2e7",
        accent="#f5c2e7",
        accent_alt="#cba6f7",
        cyan="#89dceb",
        green="#a6e3a1",
        yellow="#f9e2af",
        red="#f38ba8",
        text="#cdd6f4",
        dim="#6c7086",
        bar_filled="#cba6f7",
        bar_empty="#313244",
    ),
    "gruvbox": Theme(
        name="gruvbox",
        display_name="🍂 Gruvbox Dark",
        bg="#1d2021",
        header_bg="#282828",
        surface_left="#282828",
        surface_right="#282828",
        surface_hogs="#282828",
        border_left="#fabd2f",
        border_right="#83a598",
        border_hogs="#fe8019",
        accent="#fabd2f",
        accent_alt="#fe8019",
        cyan="#8ec07c",
        green="#b8bb26",
        yellow="#d79921",
        red="#fb4934",
        text="#ebdbb2",
        dim="#7c6f64",
        bar_filled="#fabd2f",
        bar_empty="#3c3836",
    ),
    "tokyo-night": Theme(
        name="tokyo-night",
        display_name="🌃 Tokyo Night",
        bg="#16161e",
        header_bg="#1a1b26",
        surface_left="#1a1b26",
        surface_right="#1a1b26",
        surface_hogs="#1a1b26",
        border_left="#7aa2f7",
        border_right="#7dcfff",
        border_hogs="#bb9af7",
        accent="#7aa2f7",
        accent_alt="#bb9af7",
        cyan="#7dcfff",
        green="#9ece6a",
        yellow="#e0af68",
        red="#f7768e",
        text="#c0caf5",
        dim="#565f89",
        bar_filled="#7aa2f7",
        bar_empty="#24283b",
    ),
    "cyberpunk": Theme(
        name="cyberpunk",
        display_name="⚡ Cyberpunk 2077",
        bg="#08080c",
        header_bg="#12121c",
        surface_left="#0f0f18",
        surface_right="#0f0f18",
        surface_hogs="#12121c",
        border_left="#fcee0a",
        border_right="#00f0ff",
        border_hogs="#ff003c",
        accent="#fcee0a",
        accent_alt="#00f0ff",
        cyan="#00f0ff",
        green="#05ffa1",
        yellow="#fcee0a",
        red="#ff003c",
        text="#f0f0f8",
        dim="#505068",
        bar_filled="#fcee0a",
        bar_empty="#222233",
    ),
}

DEFAULT_THEME = "dracula"


def get_theme(name: str | None) -> Theme:
    if name and name in THEMES:
        return THEMES[name]
    return THEMES[DEFAULT_THEME]


def load_saved_theme() -> str:
    try:
        if os.path.isfile(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                theme_name = data.get("theme")
                if theme_name in THEMES:
                    return theme_name
    except Exception:
        pass
    return DEFAULT_THEME


def save_theme(theme_name: str) -> None:
    try:
        if theme_name not in THEMES:
            return
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
            json.dump({"theme": theme_name}, fh, indent=2)
    except Exception:
        pass

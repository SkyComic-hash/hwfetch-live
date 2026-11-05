"""Unit tests for theme definitions and persistence."""

import re

from hwfetch_live.staticinfo import static_info_lines
from hwfetch_live.themes import (
    DEFAULT_THEME,
    THEMES,
    get_theme,
    load_saved_theme,
    save_theme,
)

HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def test_theme_palette_integrity():
    expected_themes = {"dracula", "nord", "catppuccin", "gruvbox", "tokyo-night", "cyberpunk"}
    assert set(THEMES.keys()) == expected_themes

    for name, t in THEMES.items():
        assert t.name == name
        assert len(t.display_name) > 0
        for color_field in (
            t.bg, t.header_bg, t.surface_left, t.surface_right, t.surface_hogs,
            t.border_left, t.border_right, t.border_hogs,
            t.accent, t.accent_alt, t.cyan, t.green, t.yellow, t.red,
            t.text, t.dim, t.bar_filled, t.bar_empty,
        ):
            assert HEX_COLOR_RE.match(color_field), f"Invalid color {color_field} in {name}"


def test_get_theme_fallback():
    assert get_theme("nord").name == "nord"
    assert get_theme("non_existent").name == DEFAULT_THEME
    assert get_theme(None).name == DEFAULT_THEME


def test_save_and_load_theme(tmp_path, monkeypatch):
    test_cfg = tmp_path / "config.json"
    monkeypatch.setattr("hwfetch_live.themes.CONFIG_FILE", str(test_cfg))
    monkeypatch.setattr("hwfetch_live.themes.CONFIG_DIR", str(tmp_path))

    # Defaults to default theme when file absent
    assert load_saved_theme() == DEFAULT_THEME

    # Save and reload
    save_theme("catppuccin")
    assert load_saved_theme() == "catppuccin"

    # Invalid theme is ignored
    save_theme("unknown_invalid_theme")
    assert load_saved_theme() == "catppuccin"


def test_static_info_lines_with_theme(tmp_path):
    t = get_theme("nord")
    out = static_info_lines(ps_root=str(tmp_path), theme=t)
    assert f"[b {t.accent_alt}]" in out

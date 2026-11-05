# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for a standalone, zero-dependency hwfetch-live binary.

Invoke from anywhere (paths are resolved via SPECPATH):
    pyinstaller --noconfirm --clean packaging/hwfetch-live.spec
"""
import os

from PyInstaller.utils.hooks import collect_all, collect_data_files

SPEC_DIR = SPECPATH              # directory containing this spec file
PROJECT_ROOT = os.path.dirname(SPEC_DIR)

datas, binaries, hiddenimports = collect_all("textual")
datas += collect_data_files("hwfetch_live")  # styles.tcss + package data
ps_datas, ps_binaries, ps_hidden = collect_all("psutil")
datas += ps_datas
binaries += ps_binaries
hiddenimports += ps_hidden
# optional NVML — a missing module is only a warning, never fatal
hiddenimports.append("pynvml")

a = Analysis(
    [os.path.join(SPEC_DIR, "entrypoint.py")],
    pathex=[PROJECT_ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter", "matplotlib", "numpy", "pandas",
        "PyQt5", "PyQt6", "PySide2", "PySide6", "gi",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="hwfetch-live",
    debug=False,
    strip=False,
    upx=False,
    console=True,
    icon=None,
)

# ⚡ hwfetch-live

[![Arch Linux](https://img.shields.io/badge/Arch%20Linux-Supported-1793d1?logo=arch-linux&logoColor=white)](https://archlinux.org/)
[![Python](https://img.shields.io/badge/Python-3.9+-3776ab?logo=python&logoColor=white)](https://python.org/)
[![Textual](https://img.shields.io/badge/TUI-Textual-blueviolet)](https://textual.textualize.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **Languages:** [English](README.md) | [Русский](README.ru.md)

**hwfetch-live** is a modern, lightweight Terminal User Interface (TUI) hardware and real-time power telemetry monitor. It combines the clean aesthetic of **Fastfetch** with a live system dashboard tailored for Linux laptops — with first-class support for **Intel & AMD CPUs** (Ryzen / Zen) and **hybrid graphics (Intel/AMD iGPU + NVIDIA/AMD dGPU)** on **Arch Linux** and Wayland/X11.

Designed with a sleek **Cyberpunk / Dracula neon** palette, it updates in real time (~1 s tick) with zero UI lag and negligible CPU overhead.

---

## 📸 Overview & Layout

```
┌─ static (fastfetch-style) ─┐┌─ live telemetry (1 s) ────────────┐
│ OS, kernel, uptime         ││ CPU package power (Intel/AMD RAPL)│
│ CPU model + topology       ││ CPU usage bar + core temps        │
│ RAM capacity / active swap ││ dGPU: [ SLEEP / 0.0 W ] or live   │
│ battery health / cycles    ││ battery draw (W), status, health  │
└────────────────────────────┘└───────────────────────────────────┘
┌─ top 5 power hogs: PID / user / name / CPU % / MEM % ────────────┐
│ 1342  user  firefox          14.2%   8.4%                        │
│ 8491  user  antigravity       6.1%   4.2%                        │
└──────────────────────────────────────────────────────────────────┘
```

---

## ✨ Features

- 🛡️ **Zero-Wake dGPU Safety (NVIDIA & AMD)**: Passive read of sysfs `power/runtime_status`. If the discrete GPU is in `suspended` power mode (D3cold), it displays `[ SLEEP / 0.0 W ]` without triggering PCI bus wake-ups or battery drain.
- ⚡ **CPU Package Power (Intel & AMD)**: Real-time CPU package wattage consumption parsed from `/sys/class/powercap/*rapl:*` (Intel & AMD Zen via `intel_rapl_msr`) with fallback to AMD `hwmon` (`amd_energy` / `zenpower` / `k10temp`).
- 🔋 **Battery Telemetry**: Live discharge/charge rate (in Watts), current capacity, health percentage, and cycle count.
- 🌡️ **Thermals & CPU Load**: Overall CPU percentage bar with package, individual core, and AMD die temperatures (`Tctl` / `Tdie` prioritized).
- 📊 **Top 5 Power Hogs**: Dynamic process list tracking top resource-consuming tasks by CPU & RAM with persistent delta sampling.
- 🎨 **btop-style Theme Switcher**: Press `t` to open an interactive theme picker with real-time live preview across 6 presets (Dracula, Nord, Catppuccin, Gruvbox, Tokyo Night, Cyberpunk 2077). Settings automatically persist in `~/.config/hwfetch-live/config.json`.
- 🎯 **Interactive Process Killer**: Press `k` to safely send `SIGTERM` to any highlighted offending process with interactive confirmation dialog.
- 🚀 **Asynchronous & Non-blocking**: All `/proc` and `/sys` reads run inside isolated background worker threads (`@work(thread=True)`). The UI thread stays at 60 FPS.

---

## ⌨️ Keybindings

| Key | Action |
|:---|:---|
| <kbd>q</kbd>, <kbd>Ctrl+C</kbd> | Graceful exit |
| <kbd>t</kbd> | Open btop-style **Theme Switcher** modal (live preview & auto-save) |
| <kbd>k</kbd> | Open confirmation dialog to terminate (`SIGTERM`) selected process |
| <kbd>p</kbd> | Toggle discrete GPU poll interval between **1 s** (fast) and **5 s** (power-save) |
| <kbd>Tab</kbd> / <kbd>↑</kbd> <kbd>↓</kbd> | Navigate process list |

---

## 🎨 Themes

hwfetch-live includes 6 built-in themes inspired by modern terminal setups:

| Theme | Aesthetic | Accents |
|:---|:---|:---|
| **🧛 Dracula Neon** *(default)* | Classic dark vampire palette | Pink `#ff79c6`, Purple `#bd93f9`, Cyan `#8be9fd` |
| **❄️ Nord Frost** | Arctic blue-gray minimalism | Frost Blue `#88c0d0`, Green `#a3be8c`, Yellow `#ebcb8b` |
| **☕ Catppuccin Mocha** | Soothing pastel dark | Mauve `#cba6f7`, Pink `#f5c2e7`, Blue `#89b4fa` |
| **🍂 Gruvbox Dark** | Warm retro groove | Yellow `#fabd2f`, Orange `#fe8019`, Aqua `#8ec07c` |
| **🌃 Tokyo Night** | Deep neon Tokyo city vibes | Blue `#7aa2f7`, Purple `#bb9af7`, Cyan `#7dcfff` |
| **⚡ Cyberpunk 2077** | High-contrast neon dystopia | Acid Yellow `#fcee0a`, Cyber Cyan `#00f0ff`, Hot Red `#ff003c` |

Press <kbd>t</kbd> anywhere inside the TUI to open the theme menu. Navigating with <kbd>↑</kbd> / <kbd>↓</kbd> provides **instant live preview**; pressing <kbd>Enter</kbd> saves your selection permanently to `~/.config/hwfetch-live/config.json`.

---

## 📦 Installation & Setup

### 1. Native Arch Linux Package (Recommended)

Build and install a native package using `makepkg`:

```bash
git clone https://github.com/SkyComic-hash/hwfetch-live.git
cd hwfetch-live
make pkg
```

This will compile the standalone binary and install:
- Executable: `/usr/bin/hwfetch-live`
- Desktop entry: `/usr/share/applications/hwfetch-live.desktop`
- Udev rule: `/usr/lib/udev/rules.d/99-intel-rapl.rules`
- License: `/usr/share/licenses/hwfetch-live/LICENSE`

### 2. Standalone Binary (Zero Dependencies)

If you don't want to install Python packages into your system environment, build a standalone single-file binary:

```bash
make build
./dist/hwfetch-live
```

To install it system-wide to `/usr/local/bin`:
```bash
sudo make install
```

### 3. Installation via Pip / Virtual Environment

```bash
# Basic installation
pip install .

# With optional NVIDIA NVML acceleration
pip install '.[nvidia]'

# Run
hwfetch-live
```

---

## ⚙️ Intel & AMD RAPL / Power Permissions Setup

By default on Linux, `/sys/class/powercap/*rapl:*/energy_uj` is restricted to `root`. To allow regular users in the `power` or `wheel` group to read energy metrics without `sudo`, install the bundled udev rule:

```bash
sudo cp packaging/99-intel-rapl.rules /etc/udev/rules.d/
sudo udevadm control --reload && sudo udevadm trigger --subsystem-match=powercap
```

> [!NOTE]
> If the udev rule is not installed, `hwfetch-live` will gracefully display `n/a` for package power or fall back to readable `hwmon` energy counters without crashing.

---

## 🛠️ Makefile Commands

| Command | Description |
|:---|:---|
| `make test` | Run automated pytest suite for `/sys` and telemetry parsers |
| `make build` | Build standalone PyInstaller binary into `dist/hwfetch-live` |
| `make pkg` | Build and install native Arch Linux package via `makepkg -si` |
| `make install` | Install binary, desktop shortcut and udev rule to `/usr/local` |
| `make clean` | Clean up build artifacts, venv, and temporary caches |

---

## 📂 Project Architecture

```
hwfetch-live/
├── hwfetch_live/           # Main application package
│   ├── main.py             # Textual App, bindings, dialogs, timers
│   ├── telemetry.py        # RAPL, battery, thermals, NVIDIA sysfs readers
│   ├── staticinfo.py       # Fastfetch-style static hardware specs
│   ├── procs.py            # Top process sampler (psutil deltas)
│   └── styles.tcss         # Cyberpunk / Dracula neon stylesheet
├── packaging/              # Deployment & packaging resources
│   ├── 99-intel-rapl.rules # Udev rule for unprivileged RAPL reading
│   ├── PKGBUILD            # Arch Linux package recipe
│   ├── hwfetch-live.desktop# Desktop launcher entry
│   ├── hwfetch-live.spec   # PyInstaller bundle specification
│   └── build_binary.sh     # Binary compilation script
├── tests/                  # Automated pytest test cases
│   └── test_parsing.py     # Mocked /sys and /proc unit tests
├── Makefile                # Automation entry points
└── pyproject.toml          # Package metadata & build configuration
```

---

## 📄 License

Distributed under the [MIT](LICENSE) License.

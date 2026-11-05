# ⚡ hwfetch-live

[![Arch Linux](https://img.shields.io/badge/Arch%20Linux-Поддерживается-1793d1?logo=arch-linux&logoColor=white)](https://archlinux.org/)
[![Python](https://img.shields.io/badge/Python-3.9+-3776ab?logo=python&logoColor=white)](https://python.org/)
[![Textual](https://img.shields.io/badge/TUI-Textual-blueviolet)](https://textual.textualize.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

> **Языки:** [English](README.md) | [Русский](README.ru.md)

**hwfetch-live** — это современный, лёгкий консольный TUI-монитор аппаратного обеспечения и энергопотребления в реальном времени. Проект объединяет эстетичную статическую сводку в духе **Fastfetch** с динамической панелью телеметрии (обновление ~1 раз в секунду), оптимизированной для ноутбуков на базе процессоров **Intel и AMD** (Ryzen / Zen) с гибридной графикой (**Intel/AMD iGPU + NVIDIA/AMD dGPU**) под управлением **Arch Linux** (Wayland / X11).

Интерфейс оформлен в стиле **Cyberpunk / Dracula neon** на базе фреймворка `textual`.

---

## 📸 Схема интерфейса

```
┌─ Статическая инфо (Fastfetch) ─┐┌─ Динамическая телеметрия (1 сек) ─┐
│ ОС, ядро, аптайм               ││ Мощность CPU (Intel/AMD RAPL)      │
│ Модель CPU и топология ядер    ││ Загрузка CPU (%) и температуры ядер│
│ ОЗУ / swap                     ││ dGPU: [ SLEEP / 0.0 W ] или активна│
│ Здоровье и циклы батареи       ││ Потребление батареи (Вт), статус   │
└────────────────────────────────┘└────────────────────────────────────┘
┌─ Топ-5 процессов-пожирателей ресурсов: PID / пользователь / CPU / RAM ┐
│ 1342  user  firefox          14.2%   8.4%                             │
│ 8491  user  antigravity       6.1%   4.2%                             │
└───────────────────────────────────────────────────────────────────────┘
```

---

## ✨ Ключевые возможности

- 🛡️ **Безопасный мониторинг dGPU (Zero-Wake для NVIDIA и AMD)**: Чтение состояния дискретной видеокарты производится пассивно через атрибуты sysfs (`power/runtime_status`). Если видеокарта находится в спящем режиме (`suspended` / D3cold), утилита отображает `[ SLEEP / 0.0 W ]` и **не выполняет никаких обращений к NVML или шине PCI**, что предотвращает случайное пробуждение видеокарты и экономит заряд батареи.
- ⚡ **Энергопотребление процессора (Intel & AMD)**: Измерение реальной мощности в ваттах через счетчики `/sys/class/powercap/*rapl:*` (поддерживаются процессоры Intel и AMD Zen на ядре 5.8+ через `intel_rapl_msr`), а также через датчики `hwmon` (`amd_energy`, `zenpower`, `k10temp`).
- 🔋 **Телеметрия батареи**: Отображение скорости разряда/заряда в ваттах (W), текущей ёмкости, процента износа (health) и количества циклов перезарядки.
- 🌡️ **Температуры и нагрузка CPU**: Графическая полоса загрузки процессора и датчики температур каждого ядра и кристалла (с приоритетом датчиков `Tctl` и `Tdie` для процессоров AMD).
- 📊 **Топ-5 ресурсоёмких процессов**: Отслеживание самых «прожорливых» процессов по CPU и RAM в реальном времени.
- 🎯 **Интерактивное завершение процессов**: Нажатием клавиши `k` можно безопасно отправить сигнал `SIGTERM` выбранному процессу с подтверждением действия.
- 🚀 **Полностью асинхронный движок**: Сбор телеметрии вынесен в фоновые потоки (`@work(thread=True)`), благодаря чему интерфейс не фризит и работает с плавной частотой кадров.

---

## ⌨️ Горячие клавиши

| Клавиша | Действие |
|:---|:---|
| <kbd>q</kbd>, <kbd>Ctrl+C</kbd> | Выход из программы |
| <kbd>k</kbd> | Завершить выбранный процесс (`SIGTERM`) с подтверждением |
| <kbd>p</kbd> | Переключить интервал опроса dGPU: **1 сек** ⇄ **5 сек** |
| <kbd>Tab</kbd> / <kbd>↑</kbd> <kbd>↓</kbd> | Навигация по таблице процессов |

---

## 📦 Инструкция по установке

### Вариант 1: Сборка нативного пакета Arch Linux (Рекомендуется)

Сборка полноценного Arch-пакета с интеграцией в систему через `makepkg`:

```bash
git clone https://github.com/SkyComic-hash/hwfetch-live.git
cd hwfetch-live
make pkg
```

Данная команда автоматически соберёт автономный бинарник и установит:
- Исполняемый файл: `/usr/bin/hwfetch-live`
- Ярлык приложения: `/usr/share/applications/hwfetch-live.desktop`
- Udev-правило для RAPL: `/usr/lib/udev/rules.d/99-intel-rapl.rules`
- Лицензию: `/usr/share/licenses/hwfetch-live/LICENSE`

### Вариант 2: Автономный бинарник (Zero-Dependencies)

Сборка бинарного файла через PyInstaller, не требующего установленного системного окружения Python:

```bash
make build
./dist/hwfetch-live
```

Установка бинарника в систему (`/usr/local/bin`):
```bash
sudo make install
```

### Вариант 3: Установка через Pip

```bash
# Базовая установка
pip install .

# С поддержкой прямого опроса NVIDIA NVML
pip install '.[nvidia]'

# Запуск
hwfetch-live
```

---

## ⚙️ Настройка прав доступа для Intel & AMD RAPL / Power

По умолчанию в Linux чтение счетчиков энергии `/sys/class/powercap/*rapl:*/energy_uj` разрешено только пользователю `root`. Чтобы `hwfetch-live` мог отображать мощность процессоров Intel и AMD без запуска из-под `sudo`, установите входящее в комплект правило udev:

```bash
sudo cp packaging/99-intel-rapl.rules /etc/udev/rules.d/
sudo udevadm control --reload && sudo udevadm trigger --subsystem-match=powercap
```

> [!NOTE]
> Если правило не установлено, утилита продолжит стабильно работать, считывая доступные счетчики через `hwmon` или отображая `n/a` в строке мощности процессора.

---

## 🛠️ Цели в Makefile

| Команда | Описание |
|:---|:---|
| `make test` | Запуск набора тестов pytest для парсеров `/sys` и телеметрии |
| `make build` | Сборка бинарного файла в `dist/hwfetch-live` |
| `make pkg` | Создание и установка нативного пакета для Arch Linux (`makepkg -si`) |
| `make install` | Установка бинарника, `.desktop` файла и правил udev в `/usr/local` |
| `make clean` | Очистка временных файлов, venv и сборочных директорий |

---

## 📂 Структура проекта

```
hwfetch-live/
├── hwfetch_live/           # Исходный код приложения
│   ├── main.py             # Главное TUI-приложение Textual, биндинги, таймеры
│   ├── telemetry.py        # Чтение RAPL, батареи, температур и sysfs NVIDIA
│   ├── staticinfo.py       # Статическая информация о системе (Fastfetch)
│   ├── procs.py            # Мониторинг топа процессов (psutil)
│   └── styles.tcss         # Стилизация интерфейса (neon/cyberpunk)
├── packaging/              # Файлы сборки и дистрибуции
│   ├── 99-intel-rapl.rules # Правило udev для доступа к Intel RAPL
│   ├── PKGBUILD            # Рецепт сборки пакета для Arch Linux
│   ├── hwfetch-live.desktop# Десктоп-файл
│   ├── hwfetch-live.spec   # Конфигурация для PyInstaller
│   └── build_binary.sh     # Скрипт сборки
├── tests/                  # Тесты
│   └── test_parsing.py     # Модульные тесты парсеров с поддельным деревом /sys
├── Makefile                # Автоматизация типовых команд
└── pyproject.toml          # Конфигурация проекта и метаданные
```

---

## 📄 Лицензия

Проект распространяется под лицензией [MIT](LICENSE).

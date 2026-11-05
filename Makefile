PYTHON ?= python3
VENV   := .venv
PIP    := $(VENV)/bin/pip
PYTEST := $(VENV)/bin/pytest
PYINST := $(VENV)/bin/pyinstaller
PKGVER := 0.1.0

.PHONY: all venv test build install pkg-tarball pkg clean

venv:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --quiet -e '.[dev,build]'

## Run the automated /sys-parsing test suite
test: venv
	$(PYTEST) -q tests/

## Build the standalone, zero-dependency binary -> dist/hwfetch-live
build: venv
	$(PYINST) --noconfirm --clean packaging/hwfetch-live.spec
	@echo "==> $(abspath dist/hwfetch-live)"

## Install binary + desktop entry + udev rule into /usr/local (root)
install: build
	install -Dm755 dist/hwfetch-live        $(DESTDIR)/usr/local/bin/hwfetch-live
	install -Dm644 packaging/hwfetch-live.desktop $(DESTDIR)/usr/share/applications/hwfetch-live.desktop
	install -Dm644 packaging/99-intel-rapl.rules  $(DESTDIR)/etc/udev/rules.d/99-intel-rapl.rules
	udevadm control --reload 2>/dev/null || true
	udevadm trigger --subsystem-match=powercap 2>/dev/null || true
	@echo "==> installed (desktop entry needs Terminal=true launcher support; RAPL group: see packaging/99-intel-rapl.rules)"

## Source tarball for makepkg
pkg-tarball:
	tar --transform 's,^\.,hwfetch-live-$(PKGVER),' \
	    -czf hwfetch-live-$(PKGVER).tar.gz \
	    ./pyproject.toml ./LICENSE ./README.md ./hwfetch_live ./packaging

## Build native Arch package from the tarball and install it (makepkg -si)
pkg: pkg-tarball
	cp packaging/PKGBUILD .
	makepkg -si

clean:
	rm -rf build dist src pkg hwfetch_live.egg-info $(VENV) \
	       hwfetch-live-$(PKGVER).tar.gz .pytest_cache

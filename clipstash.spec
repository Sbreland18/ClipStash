# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for ClipStash.

Build with:      python build.py
Or directly:     pyinstaller clipstash.spec --noconfirm

Environment toggles (all optional):
    CLIPSTASH_ONEFILE=0    build a folder instead of a single file (faster startup)
    CLIPSTASH_DEBUG=1      keep the console window so you can see tracebacks
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

APP_NAME = "ClipStash"
ENTRY = "clipstash.py"
PROJECT = Path(SPECPATH).resolve()

IS_MAC = sys.platform == "darwin"
IS_WIN = os.name == "nt"

DEBUG = os.environ.get("CLIPSTASH_DEBUG") == "1"
# macOS always builds a folder-based .app — onefile bundles break codesigning
# and add a multi-second unpack delay on every launch.
ONEFILE = (os.environ.get("CLIPSTASH_ONEFILE", "1") == "1") and not IS_MAC

# --------------------------------------------------------------------------- #
# yt-dlp's extractors are imported dynamically by name, so static analysis
# misses almost all of them. Pull in every submodule explicitly.
# --------------------------------------------------------------------------- #

hidden = collect_submodules("yt_dlp")
hidden += [
    "yt_dlp.compat._legacy",
    "yt_dlp.utils._legacy",
    # clipstash imports these inside try/except blocks, and updater pulls in the
    # stdlib machinery the self-updater needs. Listed explicitly so a future
    # refactor of those imports can't silently drop them from the bundle.
    "updater",
    "theme",
    "app_update",
    "version",
    "settings",
    "applog",
    "ssl",
    "hashlib",
    "zipfile",
    "urllib.request",
    "importlib.machinery",
]

# Optional yt-dlp accelerators/decryptors — include when present, skip quietly
# when not. Missing any of these degrades gracefully at runtime.
for optional in ("brotli", "brotlicffi", "mutagen", "Cryptodome", "websockets", "curl_cffi"):
    try:
        __import__(optional)
        hidden += collect_submodules(optional)
    except ImportError:
        pass

datas = collect_data_files("yt_dlp")

# tkinterdnd2 ships a compiled Tcl extension that must travel with the bundle,
# and collect_submodules alone won't bring it. Optional: without it the app runs
# exactly the same minus drag and drop.
try:
    from PyInstaller.utils.hooks import collect_dynamic_libs
    datas += collect_data_files("tkinterdnd2")
    hidden += collect_submodules("tkinterdnd2")
    print("[spec] bundling tkinterdnd2 for drag and drop")
except Exception:
    print("[spec] tkinterdnd2 not installed - drag and drop will be unavailable")
try:
    datas += collect_data_files("certifi")
except Exception:
    pass

# --------------------------------------------------------------------------- #
# Optional: bundle ffmpeg. Drop ffmpeg (+ ffprobe) into ./vendor/ before
# building and they'll be shipped inside the executable. Without this the app
# falls back to whatever is on the user's PATH.
# --------------------------------------------------------------------------- #

binaries = []
vendor = PROJECT / "vendor"
if vendor.is_dir():
    for tool in ("ffmpeg", "ffprobe"):
        name = f"{tool}.exe" if IS_WIN else tool
        path = vendor / name
        if path.is_file():
            # '.' puts it at the bundle root, where find_ffmpeg() looks first.
            binaries.append((str(path), "."))
            print(f"[spec] bundling {name}")

if not binaries:
    print("[spec] no vendor/ffmpeg found — the app will look for ffmpeg on PATH")

# --------------------------------------------------------------------------- #
# Trim the bundle. None of these are used; excluding them saves 50-150 MB if
# they happen to be installed in the build environment.
# --------------------------------------------------------------------------- #

excludes = [
    "numpy", "pandas", "scipy", "matplotlib", "PIL", "IPython",
    "notebook", "pytest", "setuptools", "pip", "wheel",
    "test", "unittest", "pydoc_data", "lib2to3",
]

icon = None
preferred = "icon.icns" if IS_MAC else ("icon.ico" if IS_WIN else "icon.png")
for folder in (PROJECT / "assets", PROJECT):
    for candidate in (preferred, "icon.png"):
        if (folder / candidate).is_file():
            icon = str(folder / candidate)
            break
    if icon:
        break

if icon:
    print(f"[spec] icon: {icon}")
else:
    print("[spec] no icon found — run 'python assets/make_icons.py' to generate one")

# PyInstaller's icon= only embeds an icon in the executable file itself, which
# is what Explorer shows. The title-bar and taskbar icon is set by Tkinter at
# runtime, so the image files have to travel inside the bundle too.
icon_assets = PROJECT / "assets"
for runtime_icon in ("icon.ico", "icon.png"):
    source = icon_assets / runtime_icon
    if source.is_file():
        datas.append((str(source), "assets"))
        print(f"[spec] bundling {runtime_icon} for the window icon")


a = Analysis(
    [ENTRY],
    pathex=[str(PROJECT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

if ONEFILE:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name=APP_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,          # UPX trips antivirus heuristics on Windows
        runtime_tmpdir=None,
        console=DEBUG,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=icon,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=APP_NAME,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=DEBUG,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=icon,
    )

    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name=APP_NAME,
    )

    if IS_MAC:
        app = BUNDLE(
            coll,
            name=f"{APP_NAME}.app",
            icon=icon,
            bundle_identifier="com.example.clipstash",
            info_plist={
                "CFBundleName": APP_NAME,
                "CFBundleDisplayName": APP_NAME,
                "CFBundleShortVersionString": "1.0.0",
                "CFBundleVersion": "1.0.0",
                "NSHighResolutionCapable": True,
                "LSMinimumSystemVersion": "11.0",
            },
        )

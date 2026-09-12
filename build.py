#!/usr/bin/env python3
"""
Build ClipStash into a standalone executable.

    python build.py                  # single-file build for this OS
    python build.py --with-ffmpeg    # also bundle ffmpeg from your PATH
    python build.py --onedir         # folder build (starts much faster)
    python build.py --debug          # keep a console window for tracebacks
    python build.py --clean          # wipe build/ and dist/ first

PyInstaller does not cross-compile. Run this on Windows to get a .exe, on
macOS to get a .app, on Linux to get an ELF binary.
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent
APP_NAME = "ClipStash"


def app_version() -> str:
    """Read the version straight from version.py so nothing can drift."""
    try:
        sys.path.insert(0, str(PROJECT))
        import version
        return version.__version__
    except Exception:
        return "1.0.0"
REQUIRED = ["pyinstaller", "yt-dlp"]
RECOMMENDED = ["mutagen", "pycryptodomex", "brotli", "certifi", "websockets"]


def _launched_by_double_click() -> bool:
    """
    True when this script owns its console window.

    Double-clicking a .py file in Explorer spawns a fresh console that closes
    the moment the script exits, so any error message flashes past unread.
    Windows tells us how many processes share the console: just us means we
    were double-clicked, more means we were run from an existing prompt.
    """
    if os.name != "nt":
        return False
    try:
        import ctypes
        buffer = (ctypes.c_uint * 4)()
        count = ctypes.windll.kernel32.GetConsoleProcessList(buffer, 4)
        return count <= 1
    except Exception:
        return False


def hold_window() -> None:
    """Wait for a keypress so the user can actually read what happened."""
    if _launched_by_double_click():
        try:
            print()
            input("Press Enter to close this window…")
        except Exception:
            pass


def log(msg: str) -> None:
    print(f"\033[36m[build]\033[0m {msg}" if sys.stdout.isatty() else f"[build] {msg}")


def warn(msg: str) -> None:
    print(f"\033[33m[warn ]\033[0m {msg}" if sys.stdout.isatty() else f"[warn ] {msg}")


def die(msg: str) -> None:
    print(f"\033[31m[error]\033[0m {msg}" if sys.stdout.isatty() else f"[error] {msg}")
    hold_window()
    sys.exit(1)


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def dir_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


# --------------------------------------------------------------------------- #
# Prerequisite checks
# --------------------------------------------------------------------------- #

def check_python() -> None:
    if sys.version_info < (3, 9):
        die(f"Python 3.9+ required, found {platform.python_version()}")
    log(f"Python {platform.python_version()} on {platform.system()} {platform.machine()}")


def check_tkinter() -> None:
    try:
        import tkinter  # noqa: F401
    except ImportError:
        die(
            "tkinter is missing from this Python install — the app cannot be built.\n"
            "  Debian/Ubuntu:  sudo apt install python3-tk\n"
            "  Fedora:         sudo dnf install python3-tkinter\n"
            "  macOS:          use python.org's installer or `brew install python-tk`\n"
            "  Windows:        re-run the Python installer and tick 'tcl/tk and IDLE'"
        )
    log("tkinter present")


def check_packages(auto_install: bool) -> None:
    import importlib.util

    dist_to_module = {"pyinstaller": "PyInstaller", "yt-dlp": "yt_dlp", "pycryptodomex": "Cryptodome"}
    missing = [
        pkg for pkg in REQUIRED
        if importlib.util.find_spec(dist_to_module.get(pkg, pkg.replace("-", "_"))) is None
    ]
    if missing:
        if not auto_install:
            die(f"Missing required packages: {', '.join(missing)}\n  pip install -U {' '.join(missing)}")
        log(f"Installing {', '.join(missing)}…")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-U", *missing])

    absent = [
        pkg for pkg in RECOMMENDED
        if importlib.util.find_spec(dist_to_module.get(pkg, pkg.replace("-", "_"))) is None
    ]
    if absent:
        warn(
            f"Optional yt-dlp extras not installed: {', '.join(absent)}. "
            "These add support for some sites, metadata embedding and faster transfers. "
            "Re-run with --extras to install them automatically, or:  "
            f"pip install -U {' '.join(absent)}"
        )


# --------------------------------------------------------------------------- #
# ffmpeg vendoring
# --------------------------------------------------------------------------- #

def vendor_ffmpeg() -> bool:
    """
    Copy ffmpeg/ffprobe from PATH into ./vendor so the spec picks them up.

    Caveat: this copies whatever binary you already have. On Windows that is
    almost always a self-contained static build and works fine. On macOS and
    Linux, distro/Homebrew builds link against shared libraries that will NOT
    be present on other machines — for a portable build, download a static
    build and put it in ./vendor yourself.
    """
    vendor = PROJECT / "vendor"
    vendor.mkdir(exist_ok=True)

    found_any = False
    for tool in ("ffmpeg", "ffprobe"):
        src = shutil.which(tool)
        if not src:
            warn(f"{tool} not found on PATH — skipping")
            continue
        name = f"{tool}.exe" if os.name == "nt" else tool
        dst = vendor / name
        shutil.copy2(src, dst)
        dst.chmod(dst.stat().st_mode | 0o111)
        log(f"vendored {tool} from {src} ({human_size(dst.stat().st_size)})")
        found_any = True

    if not found_any:
        warn("Nothing found on PATH.")
        return False

    if sys.platform != "win32":
        warn(
            "Copied a system ffmpeg. It may depend on shared libraries that other "
            "machines don't have. For a truly portable build, use --fetch-ffmpeg "
            "instead, which downloads a self-contained static build."
        )
    return True


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #

def run_pyinstaller(onefile: bool, debug: bool, clean: bool) -> None:
    env = dict(os.environ)
    env["CLIPSTASH_ONEFILE"] = "1" if onefile else "0"
    env["CLIPSTASH_DEBUG"] = "1" if debug else "0"

    cmd = [sys.executable, "-m", "PyInstaller", "clipstash.spec", "--noconfirm"]
    if clean:
        cmd.append("--clean")

    log(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=PROJECT, env=env)
    if result.returncode != 0:
        die("PyInstaller failed. Re-run with --debug to keep the console window, "
            "and check build/ClipStash/warn-ClipStash.txt for missing modules.")


FFMPEG_SOURCES = {
    # LGPL rather than GPL: it still carries the MP3 encoder ClipStash needs,
    # and it's far less onerous if you redistribute the installer.
    "win32": (
        "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
        "ffmpeg-master-latest-win64-lgpl.zip"
    ),
    "linux": "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz",
}


def _download(url: str, dest: Path) -> None:
    """Stream a URL to disk with a progress line."""
    import urllib.request

    try:
        import updater
        context = updater.ssl_context()
    except Exception:
        import ssl
        context = ssl.create_default_context()

    request = urllib.request.Request(url, headers={"User-Agent": "ClipStash-build"})
    with urllib.request.urlopen(request, timeout=60, context=context) as response:
        total = int(response.headers.get("Content-Length") or 0)
        received = 0
        with open(dest, "wb") as handle:
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                received += len(chunk)
                if total:
                    pct = received / total * 100
                    print(f"\r  {pct:5.1f}%  {human_size(received)} of {human_size(total)}",
                          end="", flush=True)
    print()


def fetch_ffmpeg() -> bool:
    """
    Download a static ffmpeg build into ./vendor.

    Static matters: a copy lifted from PATH links against shared libraries that
    won't exist on anyone else's machine. These builds are self-contained, which
    is the whole point of bundling one.
    """
    import tarfile
    import zipfile

    key = "win32" if os.name == "nt" else ("linux" if sys.platform.startswith("linux") else None)
    if key is None:
        warn(
            "Automatic download isn't wired up for macOS — the available builds are "
            "split by CPU architecture. Grab ffmpeg and ffprobe from "
            "https://evermeet.cx/ffmpeg and drop them in ./vendor, then rebuild."
        )
        return False

    url = FFMPEG_SOURCES[key]
    vendor = PROJECT / "vendor"
    vendor.mkdir(exist_ok=True)

    log(f"Downloading ffmpeg from {url.split('/')[2]}")
    warn(
        "This is a large download (~170 MB) and the binaries are ~125 MB each. "
        "Expect the finished installer to be in the 100-200 MB range. "
        "Skip --with-ffmpeg if you'd rather users install ffmpeg themselves."
    )
    archive = vendor / ("ffmpeg-download.zip" if key == "win32" else "ffmpeg-download.tar.xz")

    try:
        _download(url, archive)
    except Exception as exc:
        archive.unlink(missing_ok=True)
        text = str(exc)
        if "CERTIFICATE_VERIFY_FAILED" in text:
            warn(
                "Download blocked by a certificate error. A network filter is likely "
                "inspecting HTTPS traffic. Download ffmpeg manually in your browser "
                "and put ffmpeg.exe and ffprobe.exe in ./vendor instead."
            )
        else:
            warn(f"ffmpeg download failed: {exc}")
        return False

    wanted = {"ffmpeg.exe", "ffprobe.exe"} if key == "win32" else {"ffmpeg", "ffprobe"}
    extracted = []

    try:
        if key == "win32":
            with zipfile.ZipFile(archive) as zf:
                for member in zf.namelist():
                    name = Path(member).name
                    if name in wanted:
                        with zf.open(member) as src, open(vendor / name, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                        extracted.append(name)
        else:
            with tarfile.open(archive) as tf:
                for member in tf.getmembers():
                    name = Path(member.name).name
                    if member.isfile() and name in wanted:
                        src = tf.extractfile(member)
                        if src is None:
                            continue
                        target = vendor / name
                        with open(target, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                        target.chmod(target.stat().st_mode | 0o111)
                        extracted.append(name)
    finally:
        archive.unlink(missing_ok=True)

    if not extracted:
        warn("Downloaded the archive but found no ffmpeg binaries inside it.")
        return False

    for name in extracted:
        log(f"  {name}  {human_size((vendor / name).stat().st_size)}")
    log("ffmpeg will be bundled into the build.")
    return True


def install_extras() -> None:
    """Install yt-dlp's optional companions."""
    log(f"Installing optional extras: {', '.join(RECOMMENDED)}")
    result = subprocess.run([sys.executable, "-m", "pip", "install", "-U", *RECOMMENDED])
    if result.returncode != 0:
        warn("Some extras failed to install. The build will still work without them.")


def find_iscc() -> str | None:
    """Locate the Inno Setup command-line compiler."""
    found = shutil.which("ISCC") or shutil.which("iscc")
    if found:
        return found

    program_files = [
        os.environ.get("ProgramFiles(x86)"),
        os.environ.get("ProgramFiles"),
        r"C:\Program Files (x86)",
        r"C:\Program Files",
    ]
    for base in program_files:
        if not base:
            continue
        for version in ("Inno Setup 6", "Inno Setup 5"):
            candidate = Path(base) / version / "ISCC.exe"
            if candidate.is_file():
                return str(candidate)
    return None


def build_installer(onedir: bool) -> None:
    """Compile installer.iss into a distributable setup .exe."""
    if os.name != "nt":
        warn("Installers are Windows-only — skipping. Run build.py on Windows with --installer.")
        return

    script = PROJECT / "installer.iss"
    if not script.is_file():
        die("installer.iss not found next to build.py")

    iscc = find_iscc()
    if not iscc:
        die(
            "Inno Setup's compiler (ISCC.exe) wasn't found.\n"
            "  Download it free from https://jrsoftware.org/isdl.php\n"
            "  Then re-run, or add its folder to your PATH."
        )

    if not onedir:
        warn(
            "installer.iss expects a folder build. You built --onefile, so edit the "
            "[Files] section of installer.iss before this will work."
        )

    expected = PROJECT / "dist" / APP_NAME
    if onedir and not expected.is_dir():
        die(f"Expected {expected} from the PyInstaller build, but it isn't there.")

    release = app_version()

    # Hand the version over in a generated include rather than on the command
    # line. ISCC's /D has no safe form for a dotted version: quoted, the quotes
    # land inside the value and VersionInfoVersion rejects it; unquoted, the
    # preprocessor tries to evaluate it as arithmetic.
    version_include = PROJECT / "version.iss"
    version_include.write_text(
        "; Generated by build.py from version.py - do not edit by hand.\n"
        f'#define AppVersion "{release}"\n',
        encoding="ascii",
    )

    log(f"Compiling installer with {iscc}  (version {release})")
    result = subprocess.run([iscc, str(script)], cwd=PROJECT)
    if result.returncode != 0:
        die("Inno Setup failed - see its output above.")

    write_update_manifest(release)

    out = PROJECT / "installer_output"
    if out.is_dir():
        for item in sorted(out.glob("*.exe")):
            log(f"Installer: {item}  —  {human_size(item.stat().st_size)}")


def write_update_manifest(release: str) -> None:
    """
    Write the latest.json that installed copies read to discover this release.

    Publishing then means uploading two files together - the installer and this
    manifest. The SHA-256 recorded here is what each copy checks its download
    against, so the two must always travel as a pair; a manifest pointing at a
    different build will be rejected by every client.
    """
    import hashlib
    import json
    from datetime import date

    out = PROJECT / "installer_output"
    installer = out / f"ClipStash-Setup-{release}.exe"

    if not installer.is_file():
        # Fall back to whatever installer is actually there. A silent skip here
        # is the worst outcome: the build looks fine and updates quietly never
        # work, which is exactly how this went unnoticed the first time.
        candidates = sorted(out.glob("ClipStash-Setup-*.exe"),
                            key=lambda f: f.stat().st_mtime, reverse=True) if out.is_dir() else []
        if candidates:
            installer = candidates[0]
            warn(f"Expected {out / f'ClipStash-Setup-{release}.exe'} but found "
                 f"{installer.name} instead - using that.")
            # Take the version from the file we're actually shipping. If the
            # manifest claimed a version the installer doesn't deliver, clients
            # would install it, find themselves on the old version, and be
            # offered the same "update" forever.
            found = re.match(r"ClipStash-Setup-(.+)\.exe$", installer.name)
            if found and found.group(1) != release:
                release = found.group(1)
                warn(f"Manifest will say version {release}, matching the installer "
                     f"rather than version.py. Rebuild if that isn't what you want.")
        else:
            warn(f"No installer found in {out} - skipping the update manifest.")
            if out.is_dir():
                present = sorted(p.name for p in out.iterdir())
                warn(f"  That folder contains: {', '.join(present) if present else '(nothing)'}")
            else:
                warn("  That folder doesn't exist yet. Build with the installer option first.")
            return

    digest = hashlib.sha256()
    with open(installer, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)

    notes_file = PROJECT / "RELEASE_NOTES.txt"
    notes = notes_file.read_text(encoding="utf-8").strip() if notes_file.is_file() else ""
    if not notes:
        warn("No RELEASE_NOTES.txt found - the manifest will have empty notes. "
             "Create that file to tell people what changed.")

    manifest = {
        "version": release,
        # Relative, so the whole folder can be hosted anywhere without edits.
        "url": installer.name,
        "sha256": digest.hexdigest(),
        "size": installer.stat().st_size,
        "notes": notes,
        "released": date.today().isoformat(),
    }

    target = out / "latest.json"
    target.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    log(f"Update manifest: {target}")
    log(f"  version {release}  sha256 {digest.hexdigest()[:16]}...")
    log("  Publish latest.json AND the installer together for updates to work.")


def ensure_icons() -> None:
    """
    Generate icon and wizard artwork if the source SVGs are present but the
    rendered files aren't.

    Checks every artifact, not just the platform icon. An earlier version only
    looked for icon.ico, so when new wizard images were added it saw the .ico
    already sitting there and skipped generation entirely — leaving Inno Setup
    to fail on a missing BMP.
    """
    assets = PROJECT / "assets"
    if not (assets / "icon.svg").is_file():
        return

    platform_icon = "icon.ico" if os.name == "nt" else ("icon.icns" if sys.platform == "darwin" else "icon.png")
    required = [platform_icon, "icon.png"]
    if os.name == "nt":
        required += ["wizard-large.bmp", "wizard-small.bmp"]

    missing = [name for name in required if not (assets / name).is_file()]
    if not missing:
        return

    log(f"Missing artwork ({', '.join(missing)}) — generating from assets/icon.svg")
    result = subprocess.run([sys.executable, str(assets / "make_icons.py")], cwd=PROJECT)
    if result.returncode == 0:
        return

    warn("Icon generation failed.")
    if os.name == "nt":
        warn(
            "This is usually cairosvg: on Windows it needs Cairo's DLLs, which pip "
            "can't supply, so it often won't work. You don't need it — the rendered "
            "icon and wizard files can simply be copied into assets\\ and committed "
            "alongside the SVGs. The build continues without them; the app and the "
            "installer just use default artwork."
        )
    else:
        warn("Install the renderer's dependencies with:  pip install cairosvg pillow")


def report() -> None:
    dist = PROJECT / "dist"
    if not dist.is_dir():
        warn("No dist/ directory produced.")
        return

    log("Artifacts:")
    for item in sorted(dist.iterdir()):
        log(f"  {item.name}  —  {human_size(dir_size(item))}")

    if sys.platform == "darwin":
        app = dist / f"{APP_NAME}.app"
        if app.exists():
            print()
            log("This .app is unsigned, so Gatekeeper will quarantine it on other Macs.")
            log("Recipient fix:   xattr -dr com.apple.quarantine /Applications/ClipStash.app")
            log("Proper fix:      codesign --deep --force --sign \"Developer ID Application: …\" "
                f"\"{app}\"  &&  xcrun notarytool submit …")
    elif os.name == "nt":
        print()
        log("Unsigned PyInstaller .exe files commonly trip SmartScreen and antivirus "
            "heuristics. Sign with signtool, or expect users to click through a warning.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build ClipStash into a standalone executable.")
    parser.add_argument("--onedir", action="store_true",
                        help="build a folder instead of one file (starts in ~1s instead of ~5s)")
    parser.add_argument("--with-ffmpeg", action="store_true",
                        help="bundle ffmpeg: copy from PATH, or download a static build if absent")
    parser.add_argument("--fetch-ffmpeg", action="store_true",
                        help="always download a static ffmpeg, ignoring any copy on PATH")
    parser.add_argument("--extras", action="store_true",
                        help="install yt-dlp's optional companions before building")
    parser.add_argument("--manifest", action="store_true",
                        help="regenerate installer_output/latest.json from the existing "
                             "installer, without rebuilding anything")
    parser.add_argument("--installer", action="store_true",
                        help="compile installer.iss into a setup .exe (Windows, needs Inno Setup)")
    parser.add_argument("--debug", action="store_true",
                        help="keep the console window attached to see tracebacks")
    parser.add_argument("--clean", action="store_true", help="remove build/ and dist/ first")
    parser.add_argument("--no-install", action="store_true",
                        help="fail instead of pip-installing missing build dependencies")
    args = parser.parse_args()

    if not (PROJECT / "clipstash.py").is_file():
        die("clipstash.py not found next to build.py")
    if not (PROJECT / "clipstash.spec").is_file():
        die("clipstash.spec not found next to build.py")

    # Regenerating the manifest needs no toolchain, so handle it before the
    # prerequisite checks and exit.
    if args.manifest and not args.installer:
        write_update_manifest(app_version())
        hold_window()
        return

    check_python()
    check_tkinter()
    check_packages(auto_install=not args.no_install)

    if args.clean:
        for d in ("build", "dist"):
            shutil.rmtree(PROJECT / d, ignore_errors=True)
        log("Cleaned build/ and dist/")

    if args.extras:
        install_extras()

    if args.fetch_ffmpeg:
        fetch_ffmpeg()
    elif args.with_ffmpeg:
        if not vendor_ffmpeg():
            log("Falling back to downloading a static build…")
            fetch_ffmpeg()

    ensure_icons()

    # macOS is forced to onedir inside the spec; say so rather than silently differing.
    if sys.platform == "darwin" and not args.onedir:
        log("macOS: building a folder-based .app bundle (onefile is not used on macOS)")

    onedir = args.onedir or sys.platform == "darwin"
    run_pyinstaller(onefile=not args.onedir, debug=args.debug, clean=args.clean)
    report()

    if args.installer:
        build_installer(onedir=onedir)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[build] Cancelled.")
        hold_window()
        sys.exit(130)
    except SystemExit:
        raise
    except Exception:
        import traceback
        print("\n[error] The build script itself crashed:\n")
        traceback.print_exc()
        hold_window()
        sys.exit(1)
    hold_window()

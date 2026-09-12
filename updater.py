#!/usr/bin/env python3
"""
Keeps yt-dlp current inside a frozen ClipStash build.

The problem this solves: PyInstaller freezes yt-dlp at build time, but YouTube
changes its player often enough that yt-dlp ships fixes most weeks. A bundled
copy goes stale within a month or two, and users of a frozen app can't
`pip install -U` their way out of it.

How it works: yt-dlp publishes a pure-Python wheel, so we download it straight
from PyPI, verify the hash, and unzip it into a per-user directory. No pip
required — which matters, because a frozen app has no pip and `sys.executable`
points at the app itself, not a Python interpreter.

Getting the freshly installed copy to actually load takes one extra step.
PyInstaller registers a FrozenImporter in `sys.meta_path`, and meta_path
finders run before anything on `sys.path` — so merely prepending a directory
does nothing. `activate()` installs a narrow finder ahead of the frozen one
that claims `yt_dlp` and its submodules, and nothing else.

Call `activate()` BEFORE importing yt_dlp.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import ssl
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from importlib.abc import MetaPathFinder
from importlib.machinery import PathFinder
from pathlib import Path
from typing import Any, Callable

PACKAGE = "yt_dlp"
PYPI_JSON = "https://pypi.org/pypi/yt-dlp/json"
CHANGELOG_URL = "https://github.com/yt-dlp/yt-dlp/releases"
USER_AGENT = "ClipStash/1.0 (+https://github.com/yt-dlp/yt-dlp)"
NETWORK_TIMEOUT = 30

APP_DIRNAME = "ClipStash"
LEGACY_DIRNAMES = ("TubeFetch",)
RUNTIME_DIRNAME = "runtime"


# --------------------------------------------------------------------------- #
# Locations
# --------------------------------------------------------------------------- #

def _app_dir_base() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base)


def user_data_dir() -> Path:
    """Per-user writable directory, following each platform's convention."""
    return _app_dir_base() / APP_DIRNAME


def migrate_legacy_data() -> Path | None:
    """
    Adopt data left behind by an earlier name of this app.

    Without this, anyone upgrading from TubeFetch would silently lose their
    downloaded yt-dlp and fall back to the bundled copy. Only runs when the new
    directory doesn't exist yet, so it can never clobber current data.
    """
    target = user_data_dir()
    if target.exists():
        return None

    base = _app_dir_base()
    for legacy_name in LEGACY_DIRNAMES:
        legacy = base / legacy_name
        if not legacy.is_dir():
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            legacy.rename(target)
            return target
        except OSError:
            # Cross-device or permission trouble — copy instead, leave the
            # original alone rather than risk losing it.
            try:
                shutil.copytree(legacy, target)
                return target
            except OSError:
                return None
    return None


def runtime_root() -> Path:
    return user_data_dir() / RUNTIME_DIRNAME


# --------------------------------------------------------------------------- #
# Version handling
# --------------------------------------------------------------------------- #

def parse_version(text: str) -> tuple:
    """
    yt-dlp uses CalVer ('2026.08.19', occasionally '2026.08.19.1').

    Returns a sortable tuple. Unparseable components sort low rather than
    raising, so a malformed version never crashes the update check.
    """
    parts = []
    for chunk in str(text).split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def is_newer(candidate: str, current: str) -> bool:
    return parse_version(candidate) > parse_version(current)


def installed_runtimes() -> list[tuple[tuple, str, Path]]:
    """All yt-dlp versions installed into the runtime dir, newest first."""
    root = runtime_root()
    if not root.is_dir():
        return []

    found = []
    for entry in root.iterdir():
        if not entry.is_dir() or not entry.name.startswith("yt-dlp-"):
            continue
        if not (entry / PACKAGE / "__init__.py").is_file():
            continue  # incomplete or interrupted install
        version = entry.name[len("yt-dlp-"):]
        found.append((parse_version(version), version, entry))

    found.sort(reverse=True)
    return found


def newest_runtime() -> tuple[str, Path] | None:
    runtimes = installed_runtimes()
    if not runtimes:
        return None
    _, version, path = runtimes[0]
    return version, path


# --------------------------------------------------------------------------- #
# Import interception
# --------------------------------------------------------------------------- #

class _RuntimeFinder(MetaPathFinder):
    """
    Resolves `yt_dlp` and its submodules from a directory on disk.

    Deliberately narrow: anything that isn't yt_dlp returns None immediately and
    falls through to the normal import machinery.
    """

    def __init__(self, root: Path):
        self.root = str(root)

    def find_spec(self, fullname: str, path=None, target=None):
        if fullname != PACKAGE and not fullname.startswith(PACKAGE + "."):
            return None
        # Submodules arrive with the parent package's __path__, which already
        # points into our runtime dir. Only the top-level import needs steering.
        search = list(path) if path else [self.root]
        return PathFinder.find_spec(fullname, search)


_active_finder: _RuntimeFinder | None = None
_active_version: str | None = None


def activate() -> str | None:
    """
    Make the newest downloaded yt-dlp shadow the bundled one.

    Must run before `import yt_dlp`. Returns the activated version, or None if
    there's nothing installed or the installed copy turns out to be unusable —
    in which case the bundled copy is left in charge.
    """
    global _active_finder, _active_version

    if PACKAGE in sys.modules:
        # Too late to redirect; whatever is loaded stays loaded.
        return None

    try:
        migrate_legacy_data()
    except Exception:
        pass  # migration is a convenience, never a startup blocker

    newest = newest_runtime()
    if newest is None:
        return None
    version, path = newest

    finder = _RuntimeFinder(path)
    sys.meta_path.insert(0, finder)

    try:
        __import__(PACKAGE)
    except Exception:
        # A broken install must not take the app down with it.
        sys.meta_path.remove(finder)
        sys.modules.pop(PACKAGE, None)
        for name in [n for n in sys.modules if n.startswith(PACKAGE + ".")]:
            sys.modules.pop(name, None)
        return None

    _active_finder = finder
    _active_version = version
    return version


def active_version() -> str | None:
    """Version activated from the runtime dir, or None if the bundled copy is in use."""
    return _active_version


def current_version() -> str:
    """Whichever yt-dlp is actually loaded right now."""
    try:
        import yt_dlp
        return yt_dlp.version.__version__
    except Exception:
        return "unknown"


# --------------------------------------------------------------------------- #
# Fetching
# --------------------------------------------------------------------------- #

def _ssl_context() -> ssl.SSLContext:
    """
    Build a verifying SSL context that works behind corporate TLS inspection.

    Order matters here. Many schools and workplaces run a proxy that re-signs
    every connection with a private CA, installed into the OS trust store by
    policy. certifi doesn't know about that CA, so preferring certifi would make
    updates fail on exactly the managed machines most likely to be running this.

    So: explicit env overrides first, then the OS store (which is where a
    corporate CA lands), and certifi only as a backstop for frozen builds on
    systems where the OS store comes up empty.
    """
    for variable in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        path = os.environ.get(variable)
        if path and Path(path).is_file():
            try:
                return ssl.create_default_context(cafile=path)
            except Exception:
                pass

    context = ssl.create_default_context()
    try:
        if context.cert_store_stats().get("x509_ca", 0) > 0:
            return context
    except Exception:
        return context

    # OS store is empty — common in frozen macOS builds. Fall back to certifi.
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return context


def ssl_context() -> ssl.SSLContext:
    """Public alias — build.py reuses this for its own downloads."""
    return _ssl_context()


def _describe_network_error(exc: Exception) -> str:
    """Turn an opaque urllib failure into something a user can act on."""
    text = str(exc)
    if "CERTIFICATE_VERIFY_FAILED" in text:
        return (
            "Couldn't verify the connection to PyPI.\n\n"
            "This usually means a network filter or antivirus is inspecting HTTPS "
            "traffic with its own certificate. On a managed work or school machine, "
            "that certificate is normally installed system-wide and this will just "
            "work — if it isn't, ask IT for the proxy's root certificate, or set the "
            "SSL_CERT_FILE environment variable to point at it.\n\n"
            f"Details: {text}"
        )
    if isinstance(exc, urllib.error.HTTPError):
        return f"PyPI returned HTTP {exc.code} ({exc.reason})."
    if isinstance(exc, urllib.error.URLError):
        return (
            "Couldn't reach PyPI. Check your internet connection, or whether a "
            f"firewall is blocking pypi.org.\n\nDetails: {exc.reason}"
        )
    return text


def _open(url: str):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(request, timeout=NETWORK_TIMEOUT, context=_ssl_context())


def fetch_latest() -> dict[str, Any]:
    """
    Ask PyPI what the newest yt-dlp is.

    Returns {version, url, sha256, size}. Raises on network or parse failure.
    """
    with _open(PYPI_JSON) as response:
        payload = json.loads(response.read().decode("utf-8"))

    version = payload["info"]["version"]
    wheels = [
        f for f in payload["urls"]
        if f.get("packagetype") == "bdist_wheel" and f.get("filename", "").endswith(".whl")
    ]
    if not wheels:
        raise RuntimeError(f"PyPI lists no wheel for yt-dlp {version}")

    # yt-dlp ships a single py3-none-any wheel; prefer it explicitly anyway.
    wheels.sort(key=lambda f: "none-any" not in f["filename"])
    chosen = wheels[0]

    return {
        "version": version,
        "url": chosen["url"],
        "sha256": (chosen.get("digests") or {}).get("sha256", ""),
        "size": chosen.get("size", 0),
        "filename": chosen["filename"],
    }


class UpdateError(Exception):
    """Update failed for a reason worth showing the user verbatim."""


def check_for_update() -> tuple[bool, dict[str, Any]]:
    """Returns (update_available, metadata)."""
    try:
        latest = fetch_latest()
    except Exception as exc:
        raise UpdateError(_describe_network_error(exc)) from exc
    return is_newer(latest["version"], current_version()), latest


# --------------------------------------------------------------------------- #
# Installing
# --------------------------------------------------------------------------- #

def download_and_install(
    meta: dict[str, Any],
    progress: Callable[[int, int], None] | None = None,
) -> Path:
    """
    Download the wheel, verify its hash, and unpack it into a versioned dir.

    Installs to `runtime/yt-dlp-<version>/` rather than overwriting anything.
    That sidesteps Windows' refusal to replace files that are currently mapped
    into a running process — the new copy simply wins at next launch.
    """
    version = meta["version"]
    target = runtime_root() / f"yt-dlp-{version}"
    if (target / PACKAGE / "__init__.py").is_file():
        return target  # already installed

    runtime_root().mkdir(parents=True, exist_ok=True)

    digest = hashlib.sha256()
    with tempfile.NamedTemporaryFile(suffix=".whl", delete=False) as handle:
        wheel_path = Path(handle.name)
        try:
            with _open(meta["url"]) as response:
                total = int(response.headers.get("Content-Length") or meta.get("size") or 0)
                received = 0
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    digest.update(chunk)
                    received += len(chunk)
                    if progress:
                        progress(received, total)
        except Exception as exc:
            handle.close()
            wheel_path.unlink(missing_ok=True)
            raise UpdateError(_describe_network_error(exc)) from exc

    try:
        expected = meta.get("sha256")
        if expected and digest.hexdigest() != expected:
            raise RuntimeError(
                "Downloaded file failed its checksum — the download was corrupted "
                "or tampered with. Nothing was installed."
            )

        # Extract to a staging dir so an interrupted unzip never leaves a
        # half-populated version dir that activate() would try to load.
        staging = runtime_root() / f".staging-{version}"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True)

        with zipfile.ZipFile(wheel_path) as archive:
            for member in archive.namelist():
                # Refuse path traversal out of the staging dir.
                resolved = (staging / member).resolve()
                if not str(resolved).startswith(str(staging.resolve())):
                    raise RuntimeError(f"Wheel contains an unsafe path: {member}")
            archive.extractall(staging)

        if not (staging / PACKAGE / "__init__.py").is_file():
            raise RuntimeError("Wheel did not contain a yt_dlp package")

        shutil.rmtree(target, ignore_errors=True)
        staging.rename(target)
    finally:
        wheel_path.unlink(missing_ok=True)

    return target


def prune(keep: int = 2) -> int:
    """Delete all but the newest `keep` installed runtimes. Returns count removed."""
    removed = 0
    for _, _, path in installed_runtimes()[keep:]:
        try:
            shutil.rmtree(path)
            removed += 1
        except OSError:
            pass
    # Sweep up abandoned staging dirs from interrupted installs.
    root = runtime_root()
    if root.is_dir():
        for entry in root.iterdir():
            if entry.is_dir() and entry.name.startswith(".staging-"):
                shutil.rmtree(entry, ignore_errors=True)
    return removed


def uninstall_all() -> None:
    """Remove every downloaded runtime, reverting to the bundled yt-dlp at next launch."""
    shutil.rmtree(runtime_root(), ignore_errors=True)


if __name__ == "__main__":
    # Small CLI for testing the updater without launching the GUI.
    activated = activate()
    print(f"runtime dir:      {runtime_root()}")
    print(f"activated:        {activated or '(using bundled copy)'}")
    print(f"current version:  {current_version()}")
    try:
        available, meta = check_for_update()
        print(f"latest on PyPI:   {meta['version']}")
        if available:
            print("update available — installing…")
            path = download_and_install(meta, lambda a, b: None)
            print(f"installed to:     {path}")
            print(f"pruned:           {prune()} old runtime(s)")
        else:
            print("up to date")
    except Exception as exc:
        print(f"update check failed: {exc}")

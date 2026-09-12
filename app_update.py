#!/usr/bin/env python3
"""
Self-update for ClipStash.

The constraint that shapes everything here: on Windows a running executable is
locked and cannot overwrite itself. So ClipStash does not patch itself. It
downloads the installer you already publish, starts it, and exits. The installer
does the replacing and puts the app back afterwards.

The flow:

    1. Fetch a small JSON manifest describing the newest release.
    2. Compare its version against the running one.
    3. Download the installer, verifying its SHA-256 against the manifest.
    4. Launch it detached, then quit so the files aren't locked.

Publishing a release means putting two files somewhere reachable: the installer
and a manifest pointing at it. `build.py` writes the manifest for you.

Manifest format:

    {
      "version": "1.1.0",
      "url":     "https://example.com/ClipStash-Setup-1.1.0.exe",
      "sha256":  "a1b2c3...",
      "size":    118293841,
      "notes":   "What changed in this release.",
      "released": "2026-09-14"
    }

Where to host it. Any of these work, because the feed is just a URL:

  * GitHub Releases - upload the installer and manifest as release assets, then
    point UPDATE_FEED_URL at
    https://github.com/OWNER/REPO/releases/latest/download/latest.json
    That permalink always resolves to the newest release, so the URL never
    changes between versions.
  * Any web server - drop both files in a folder and link to the manifest.
  * A network share - a UNC path such as \\\\fileserver\\apps\\clipstash\\latest.json
    works too, which suits an organisation distributing internally without
    putting anything on the public internet.

A note on trust. The SHA-256 check proves the download matches what the manifest
said, so it catches corruption and tampering in transit. It does not prove the
manifest itself is genuine - that rests on HTTPS. Anyone who can modify the
manifest can point it at any executable they like. For a small internal tool
that's usually an acceptable risk; if ClipStash ever goes wider, signing the
installer with a code-signing certificate is the real answer, and Windows will
then refuse anything that isn't yours.
"""

from __future__ import annotations

import hashlib
import json
import os
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import version

# ---------------------------------------------------------------------------
# Point this at your published manifest. Left empty, the in-app update check is
# hidden entirely, so the app still works fine before you've set up hosting.
#
# This GitHub permalink always resolves to the newest release, so it never needs
# changing between versions. It must match your repository name exactly - if you
# name the repo something other than "ClipStash", edit the URL to match, or the
# update check will report that no update information was found.
# ---------------------------------------------------------------------------
UPDATE_FEED_URL = "https://github.com/Sbreland18/ClipStash/releases/latest/download/latest.json"

USER_AGENT = f"ClipStash/{version.__version__}"
NETWORK_TIMEOUT = 30


class UpdateError(Exception):
    """Something went wrong that's worth showing the user verbatim."""


@dataclass
class Release:
    version: str
    url: str
    sha256: str = ""
    size: int = 0
    notes: str = ""
    released: str = ""

    @property
    def filename(self) -> str:
        name = Path(urllib.parse.urlparse(self.url).path).name
        return name or f"ClipStash-Setup-{self.version}.exe"


# --------------------------------------------------------------------------- #
# Fetching
# --------------------------------------------------------------------------- #

def _ssl_context() -> ssl.SSLContext:
    """Reuse the updater's context so corporate TLS inspection keeps working."""
    try:
        import updater
        return updater.ssl_context()
    except Exception:
        return ssl.create_default_context()


def _read(url: str) -> bytes:
    """Read a URL, a file:// URL, or a plain local/UNC path."""
    parsed = urllib.parse.urlparse(url)

    if parsed.scheme in ("", "file") or url.startswith("\\\\"):
        path = Path(urllib.parse.unquote(parsed.path)) if parsed.scheme == "file" else Path(url)
        return path.read_bytes()

    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=NETWORK_TIMEOUT, context=_ssl_context()) as response:
        return response.read()


def describe_error(exc: Exception) -> str:
    text = str(exc)
    if "CERTIFICATE_VERIFY_FAILED" in text:
        return (
            "Couldn't verify the secure connection to the update server.\n\n"
            "This usually means a network filter is inspecting HTTPS traffic. On a "
            "managed work or school computer the necessary certificate is normally "
            "installed for you; if it isn't, ask your IT team.\n\n"
            f"Details: {text}"
        )
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 404:
            return "No update information was found at the address configured in this app."
        return f"The update server returned an error ({exc.code} {exc.reason})."
    if isinstance(exc, urllib.error.URLError):
        return (
            "Couldn't reach the update server. Check your internet connection.\n\n"
            f"Details: {exc.reason}"
        )
    if isinstance(exc, (FileNotFoundError, PermissionError)):
        return f"Couldn't read the update information: {text}"
    return text


def fetch_release(feed_url: str = "") -> Release:
    """Read the manifest and return what it describes."""
    feed = feed_url or UPDATE_FEED_URL
    if not feed:
        raise UpdateError("No update source is configured in this build.")

    try:
        raw = _read(feed)
    except Exception as exc:
        raise UpdateError(describe_error(exc)) from exc

    try:
        data: dict[str, Any] = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise UpdateError(f"The update information was unreadable: {exc}") from exc

    if not data.get("version") or not data.get("url"):
        raise UpdateError("The update information is incomplete (missing version or url).")

    # Relative URLs resolve against the manifest, so moving the whole folder
    # somewhere else doesn't break the link to the installer.
    url = data["url"]
    if not urllib.parse.urlparse(url).scheme and not url.startswith("\\\\"):
        url = urllib.parse.urljoin(feed, url)

    return Release(
        version=str(data["version"]).strip(),
        url=url,
        sha256=str(data.get("sha256", "")).strip().lower(),
        size=int(data.get("size") or 0),
        notes=str(data.get("notes", "")).strip(),
        released=str(data.get("released", "")).strip(),
    )


def check(feed_url: str = "") -> tuple[bool, Release]:
    """Returns (an_update_is_available, release)."""
    release = fetch_release(feed_url)
    return version.is_newer(release.version), release


def is_configured() -> bool:
    return bool(UPDATE_FEED_URL)


# --------------------------------------------------------------------------- #
# Downloading
# --------------------------------------------------------------------------- #

def download(release: Release, progress: Callable[[int, int], None] | None = None) -> Path:
    """
    Fetch the installer into a temporary folder, verifying it as it arrives.

    Returns the path to the verified file. Raises rather than returning
    something unverified: a failed hash means the file is discarded.
    """
    folder = Path(tempfile.mkdtemp(prefix="clipstash-update-"))
    target = folder / release.filename

    digest = hashlib.sha256()
    try:
        parsed = urllib.parse.urlparse(release.url)
        if parsed.scheme in ("", "file") or release.url.startswith("\\\\"):
            data = _read(release.url)
            digest.update(data)
            target.write_bytes(data)
            if progress:
                progress(len(data), len(data))
        else:
            request = urllib.request.Request(release.url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=NETWORK_TIMEOUT,
                                        context=_ssl_context()) as response:
                total = int(response.headers.get("Content-Length") or release.size or 0)
                received = 0
                with open(target, "wb") as handle:
                    while True:
                        chunk = response.read(256 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
                        digest.update(chunk)
                        received += len(chunk)
                        if progress:
                            progress(received, total)
    except Exception as exc:
        _cleanup(folder)
        raise UpdateError(describe_error(exc)) from exc

    if release.sha256:
        if digest.hexdigest() != release.sha256:
            _cleanup(folder)
            raise UpdateError(
                "The downloaded file didn't match the expected fingerprint, so it "
                "has been discarded.\n\n"
                "This usually means the download was interrupted or corrupted. "
                "Try again; if it keeps happening, download the installer manually."
            )

    return target


def _cleanup(folder: Path) -> None:
    import shutil
    shutil.rmtree(folder, ignore_errors=True)


# --------------------------------------------------------------------------- #
# Handing over to the installer
# --------------------------------------------------------------------------- #

def launch_installer(installer: Path, silent: bool = True) -> None:
    """
    Start the installer and detach from it.

    Detaching matters: the installer has to outlive this process, because the
    very next thing that happens is ClipStash exiting so its files stop being
    locked. Inno Setup's /SILENT shows a progress window but asks nothing, which
    is the right amount of feedback for an update someone already agreed to.
    """
    if os.name != "nt":
        raise UpdateError("In-app updating is only wired up for Windows.")

    arguments = [str(installer)]
    if silent:
        arguments += [
            "/SILENT",              # progress window, no questions
            "/SUPPRESSMSGBOXES",
            "/NORESTART",
            "/RESTARTAPPLICATIONS",  # reopen ClipStash when it's done
        ]

    flags = 0
    flags |= getattr(subprocess, "DETACHED_PROCESS", 0)
    flags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    subprocess.Popen(
        arguments,
        close_fds=True,
        creationflags=flags,
        cwd=str(installer.parent),
    )


def apply_and_exit(installer: Path) -> None:
    """Start the installer, then leave immediately so nothing stays locked."""
    launch_installer(installer)
    # os._exit rather than sys.exit: this must not be caught by anything, and
    # must not wait on the download or UI threads still running.
    os._exit(0)


if __name__ == "__main__":
    feed = sys.argv[1] if len(sys.argv) > 1 else UPDATE_FEED_URL
    print(f"running version: {version.__version__}")
    print(f"feed:            {feed or '(not configured)'}")
    if not feed:
        sys.exit(0)
    try:
        available, release = check(feed)
        print(f"latest version:  {release.version}")
        print(f"installer:       {release.url}")
        print(f"update needed:   {available}")
        if release.notes:
            print(f"notes:           {release.notes[:200]}")
    except UpdateError as exc:
        print(f"check failed: {exc}")
        sys.exit(1)

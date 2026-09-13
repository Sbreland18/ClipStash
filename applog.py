#!/usr/bin/env python3
"""
Writes ClipStash's activity to disk so a problem can be looked at after it happens.

The log panel in the window disappears the moment the app closes, which leaves
nothing to go on when someone reports that a download "didn't work". These files
turn that conversation from guesswork into reading a file.

    Windows   %LOCALAPPDATA%\\ClipStash\\logs\\
    macOS     ~/Library/Application Support/ClipStash/logs/
    Linux     ~/.local/share/ClipStash/logs/

One file per run, named for the time it started. Old ones are pruned on launch
so the folder can't grow without limit on a machine that's never cleaned up.

Every operation here is wrapped. A full disk, a locked file, a folder someone
has made read-only - none of these should be able to stop a download, so a
logger that cannot write simply goes quiet.
"""

from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

MAX_FILES = 10          # roughly the last ten sessions
MAX_BYTES = 5_000_000   # stop appending well before a log becomes unwieldy


def _base_dir() -> Path:
    try:
        import updater
        return updater.user_data_dir()
    except Exception:
        if os.name == "nt":
            root = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        elif sys.platform == "darwin":
            root = Path.home() / "Library" / "Application Support"
        else:
            root = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
        return Path(root) / "ClipStash"


def log_dir() -> Path:
    return _base_dir() / "logs"


class SessionLog:
    """A single run's log file."""

    def __init__(self) -> None:
        self.path: Path | None = None
        self.disabled = False
        self._written = 0
        self._open()

    # -- lifecycle ---------------------------------------------------------- #

    def _open(self) -> None:
        try:
            folder = log_dir()
            folder.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            self.path = folder / f"clipstash_{stamp}.log"
            self.path.touch()
            self._prune()
        except Exception:
            self.disabled = True
            self.path = None

    def _prune(self) -> None:
        """Keep the newest MAX_FILES logs and delete the rest."""
        try:
            files = sorted(
                log_dir().glob("clipstash_*.log"),
                key=lambda f: f.stat().st_mtime,
                reverse=True,
            )
            for old in files[MAX_FILES:]:
                old.unlink(missing_ok=True)
        except Exception:
            pass

    # -- writing ------------------------------------------------------------ #

    def write(self, message: str, level: str = "INFO") -> None:
        if self.disabled or self.path is None:
            return
        if self._written > MAX_BYTES:
            return
        try:
            stamp = datetime.now().strftime("%H:%M:%S")
            line = f"{stamp} [{level}] {message.rstrip()}\n"
            with open(self.path, "a", encoding="utf-8", errors="replace") as handle:
                handle.write(line)
            self._written += len(line)
        except Exception:
            # Losing a log line must never interrupt what the user is doing.
            self.disabled = True

    def header(self, app_version: str, ytdlp_version: str, ffmpeg: str | None) -> None:
        """
        Record the environment once at the top of each file.

        This is the part that actually saves time later: most reports turn out
        to be a specific version, a missing ffmpeg, or an odd install location,
        and all three are answered here without another round of questions.
        """
        self.write("=" * 62)
        self.write(f"ClipStash {app_version}")
        self.write(f"yt-dlp {ytdlp_version}")
        self.write(f"ffmpeg: {ffmpeg or 'NOT FOUND - quality will be limited'}")
        self.write(f"Python {sys.version.split()[0]} on {sys.platform}")
        self.write(f"Frozen build: {getattr(sys, 'frozen', False)}")
        self.write(f"Executable: {sys.executable}")
        self.write("=" * 62)

    def exception(self, context: str) -> None:
        self.write(f"{context}\n{traceback.format_exc()}", level="ERROR")


_session: SessionLog | None = None


def session() -> SessionLog:
    global _session
    if _session is None:
        _session = SessionLog()
    return _session


def write(message: str, level: str = "INFO") -> None:
    session().write(message, level)


def open_folder() -> bool:
    """Show the log folder in the system file manager."""
    try:
        folder = log_dir()
        folder.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(folder)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            import subprocess
            subprocess.run(["open", str(folder)])
        else:
            import subprocess
            subprocess.run(["xdg-open", str(folder)])
        return True
    except Exception:
        return False


if __name__ == "__main__":
    log = session()
    print(f"log folder: {log_dir()}")
    print(f"this file:  {log.path}")
    log.header("1.0.0", "2026.08.19", "/usr/bin")
    log.write("Diagnostic run")
    print(f"disabled:   {log.disabled}")

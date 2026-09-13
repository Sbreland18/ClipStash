#!/usr/bin/env python3
"""
Remembers ClipStash's options between launches.

Stored as JSON alongside the downloaded yt-dlp runtime, so everything ClipStash
keeps for a user lives under one folder:

    Windows   %LOCALAPPDATA%\\ClipStash\\settings.json
    macOS     ~/Library/Application Support/ClipStash/settings.json
    Linux     ~/.local/share/ClipStash/settings.json

Two rules shape what goes in here.

Nothing that isn't the user's own preference is saved. The URL box is
deliberately not persisted: reopening the app with last week's link already
typed in invites downloading it again by accident.

A corrupt or hand-edited file must never stop the app starting. Every read is
guarded, every value is checked against a default of the right type, and
anything unrecognised is dropped. Losing settings is a nuisance; refusing to
launch is a fault.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

FILENAME = "settings.json"

# Keys and their defaults. A key absent from here is discarded on load, so an
# old settings file can never inject unexpected values into the app.
DEFAULTS: dict[str, Any] = {
    "output_dir": "",
    "quality": "Best available",
    "playlist_items": "",
    "folder_per_playlist": True,
    "number_playlist_items": True,
    "use_archive": True,
    "write_subtitles": False,
    "subtitle_langs": "en",
    "embed_metadata": True,
    "embed_thumbnail": False,
    "restrict_filenames": False,
    "cookies_browser": "None",
    "cookies_file": "",
    "concurrent_fragments": 4,
    "window_geometry": "",
    "watch_clipboard": False,
    # Clip start/end are deliberately absent: a time range belongs to one
    # specific video, and silently reapplying last week's to a new download
    # would quietly truncate it.
    "sponsorblock": False,
    "split_chapters": False,
    "warn_duplicates": True,
    "auto_check_ytdlp": True,
    "last_ytdlp_check": "",
    "schedule_enabled": False,
    "schedule_time": "18:00",
}


def _base_dir() -> Path:
    """Match the updater's location exactly, so all user data sits together."""
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


def path() -> Path:
    return _base_dir() / FILENAME


def load() -> dict[str, Any]:
    """
    Read saved settings, falling back to defaults for anything missing or wrong.

    Values are validated against the type of their default rather than trusted,
    so a hand-edited file with a string where a number belongs degrades to the
    default instead of crashing the app three screens later.
    """
    values = dict(DEFAULTS)

    try:
        raw = path().read_text(encoding="utf-8")
        stored = json.loads(raw)
        if not isinstance(stored, dict):
            return values
    except Exception:
        return values

    for key, default in DEFAULTS.items():
        if key not in stored:
            continue
        candidate = stored[key]
        if isinstance(default, bool):
            if isinstance(candidate, bool):
                values[key] = candidate
        elif isinstance(default, int):
            try:
                values[key] = max(1, min(16, int(candidate)))
            except (TypeError, ValueError):
                pass
        elif isinstance(default, str):
            if isinstance(candidate, str):
                values[key] = candidate

    return values


def save(values: dict[str, Any]) -> bool:
    """
    Write settings, keeping only recognised keys.

    Written to a temporary file and moved into place, so an interruption
    mid-write leaves the previous settings intact rather than a truncated file
    that fails to parse on next launch.
    """
    clean = {k: values[k] for k in DEFAULTS if k in values}

    try:
        folder = _base_dir()
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / FILENAME
        temporary = folder / f"{FILENAME}.tmp"
        temporary.write_text(json.dumps(clean, indent=2) + "\n", encoding="utf-8")
        shutil.move(str(temporary), str(target))
        return True
    except Exception:
        return False


def reset() -> bool:
    try:
        path().unlink(missing_ok=True)
        return True
    except Exception:
        return False


if __name__ == "__main__":
    print(f"settings file: {path()}")
    print(f"exists:        {path().is_file()}")
    for key, value in load().items():
        print(f"  {key:24} {value!r}")

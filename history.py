#!/usr/bin/env python3
"""
Remembers what ClipStash has downloaded, and where it put it.

ClipStash already keeps a download archive, but that file exists for yt-dlp's
benefit - it records opaque ids so repeat downloads can be skipped, and tells a
person nothing. This is the human-readable counterpart, answering "did I already
get this, and where did it go?" without hunting through folders.

Stored as JSON next to the other per-user data:

    Windows   %LOCALAPPDATA%\\ClipStash\\history.json
    macOS     ~/Library/Application Support/ClipStash/history.json
    Linux     ~/.local/share/ClipStash/history.json

Newest first, capped at MAX_ENTRIES. A history file is a convenience, so every
operation fails quietly rather than interrupting a download.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

FILENAME = "history.json"
MAX_ENTRIES = 500


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


def path() -> Path:
    return _base_dir() / FILENAME


@dataclass
class Entry:
    title: str = ""
    filename: str = ""
    folder: str = ""
    url: str = ""
    channel: str = ""
    size: int = 0
    when: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    @property
    def full_path(self) -> Path:
        return Path(self.folder) / self.filename

    @property
    def exists(self) -> bool:
        try:
            return self.full_path.is_file()
        except OSError:
            return False

    @property
    def when_display(self) -> str:
        try:
            moment = datetime.fromisoformat(self.when)
        except ValueError:
            return self.when
        today = datetime.now().date()
        if moment.date() == today:
            return f"Today {moment.strftime('%H:%M')}"
        if (today - moment.date()).days == 1:
            return f"Yesterday {moment.strftime('%H:%M')}"
        return f"{moment.day} {moment.strftime('%b %Y, %H:%M')}"


def load() -> list[Entry]:
    try:
        raw = json.loads(path().read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            return []
    except Exception:
        return []

    entries = []
    allowed = set(Entry().__dict__)
    for record in raw:
        if not isinstance(record, dict):
            continue
        try:
            # Drop anything unrecognised rather than passing it to the
            # constructor, so an older or hand-edited file can't raise here.
            entries.append(Entry(**{k: v for k, v in record.items() if k in allowed}))
        except Exception:
            continue
    return entries


def save(entries: list[Entry]) -> bool:
    try:
        folder = _base_dir()
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / FILENAME
        temporary = folder / f"{FILENAME}.tmp"
        payload = [asdict(e) for e in entries[:MAX_ENTRIES]]
        temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        shutil.move(str(temporary), str(target))
        return True
    except Exception:
        return False


def record(filepath: str, title: str = "", url: str = "", channel: str = "") -> Entry | None:
    """Add one finished file to the top of the history."""
    try:
        target = Path(filepath)
        entry = Entry(
            title=title or target.stem,
            filename=target.name,
            folder=str(target.parent),
            url=url,
            channel=channel,
            size=target.stat().st_size if target.is_file() else 0,
        )
    except Exception:
        return None

    entries = load()
    # A repeat download of the same file replaces the old record rather than
    # adding a second, so the list stays a picture of what's on disk.
    entries = [e for e in entries if not (e.filename == entry.filename and e.folder == entry.folder)]
    entries.insert(0, entry)
    save(entries)
    return entry


def clear() -> bool:
    try:
        path().unlink(missing_ok=True)
        return True
    except Exception:
        return False


def open_containing(entry: Entry) -> bool:
    """Open the folder an entry lives in, selecting the file where possible."""
    try:
        folder = Path(entry.folder)
        if not folder.is_dir():
            return False
        if os.name == "nt":
            import subprocess
            if entry.exists:
                subprocess.Popen(["explorer", "/select,", str(entry.full_path)])
            else:
                os.startfile(folder)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            import subprocess
            if entry.exists:
                subprocess.run(["open", "-R", str(entry.full_path)])
            else:
                subprocess.run(["open", str(folder)])
        else:
            import subprocess
            subprocess.run(["xdg-open", str(folder)])
        return True
    except Exception:
        return False


if __name__ == "__main__":
    print(f"history file: {path()}")
    items = load()
    print(f"entries: {len(items)}")
    for item in items[:10]:
        mark = " " if item.exists else "?"
        print(f" {mark} {item.when_display:22} {item.title[:48]:48} {item.folder}")

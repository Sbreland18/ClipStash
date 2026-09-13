#!/usr/bin/env python3
"""
ClipStash — a desktop application for downloading YouTube videos and playlists.

Built on yt-dlp. Single file, standard-library GUI (Tkinter).

Setup
-----
    pip install -U yt-dlp

    ffmpeg is also required for merging video+audio streams and for MP3
    conversion. Install it from https://ffmpeg.org/download.html or via your
    package manager (brew install ffmpeg / apt install ffmpeg /
    winget install Gyan.FFmpeg).

Run
---
    python clipstash.py

Please only download content you have the rights to: your own uploads,
Creative Commons material, or anything the rights holder permits. Bulk
downloading copyrighted material generally violates YouTube's Terms of Service.
"""

from __future__ import annotations

import os
import queue
import re
import shutil
import sys
import threading
import time
import tkinter as tk
from dataclasses import dataclass, field, replace
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

try:
    import theme
except Exception:  # theming is cosmetic — never block startup over it
    theme = None  # type: ignore[assignment]

try:
    import settings as appsettings
except Exception:
    appsettings = None  # type: ignore[assignment]

try:
    import applog
except Exception:
    applog = None  # type: ignore[assignment]

# Drag and drop needs a different root class, so this must be resolved before
# App is defined rather than inside it. Absent the package the app is identical
# minus the ability to drop a link on the window.
try:
    from tkinterdnd2 import TkinterDnD, DND_TEXT, DND_FILES
    TK_BASE = TkinterDnD.Tk
    HAVE_DND = True
except Exception:
    TK_BASE = tk.Tk
    HAVE_DND = False
    DND_TEXT = DND_FILES = None

try:
    import version as appversion
    import app_update
except Exception:  # self-update is optional; the app must still run without it
    appversion = None  # type: ignore[assignment]
    app_update = None  # type: ignore[assignment]

# Must run before yt_dlp is imported: swaps in a newer downloaded copy if one
# exists, otherwise leaves the bundled version in charge.
try:
    import updater
    updater.activate()
except Exception:  # updater is optional — never let it block startup
    updater = None  # type: ignore[assignment]

try:
    import yt_dlp
    from yt_dlp.utils import DownloadError
except ImportError:  # pragma: no cover
    yt_dlp = None
    DownloadError = Exception

try:
    from yt_dlp.utils import DownloadCancelled
except ImportError:  # older yt-dlp

    class DownloadCancelled(Exception):  # type: ignore[no-redef]
        pass


APP_NAME = "ClipStash"

QUALITY_PRESETS = [
    "Best available",
    "4K (2160p) or below",
    "1440p or below",
    "1080p or below",
    "720p or below",
    "480p or below",
    "360p or below",
    "Audio only — MP3",
    "Audio only — original (m4a/opus)",
]

BROWSERS = ["None", "chrome", "firefox", "edge", "brave", "safari", "chromium", "opera", "vivaldi"]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def human_bytes(n: float | None) -> str:
    if not n:
        return "—"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def human_time(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def default_download_dir() -> Path:
    candidate = Path.home() / "Downloads" / APP_NAME
    return candidate


HELP = {
    "url":
        "Paste the web address of a YouTube video or playlist here.\n\n"
        "Copy it from your browser's address bar. If the link is to a playlist, "
        "every video in that playlist is downloaded.",
    "savedir":
        "The folder your downloads are saved into.\n\n"
        "If it doesn't exist yet, ClipStash creates it for you.",
    "browse":
        "Pick the folder to save downloads into.",
    "quality":
        "How good you want the video to look.\n\n"
        "'Best available' takes the highest quality YouTube offers. Choosing a "
        "lower setting gives smaller files that download faster.\n\n"
        "The two 'Audio only' options skip the video entirely and keep just the "
        "sound, which is handy for music or podcasts.",
    "items":
        "Which videos from a playlist you want.\n\n"
        "Leave this empty to get all of them.\n\n"
        "Examples:\n"
        "    1-10   the first ten\n"
        "    3,7,12   only those three\n"
        "    25-   from the 25th to the end",
    "browser":
        "Only needed for videos you must be signed in to watch.\n\n"
        "Leave this on None for ordinary public videos.\n\n"
        "On Windows this often fails anyway: recent versions of Chrome and Edge "
        "scramble their saved sign-in data in a way ClipStash can't read. If you "
        "do need to be signed in, use the Cookie file box instead.",
    "fragments":
        "How many pieces of a single video to fetch at the same time.\n\n"
        "YouTube sends larger videos in small chunks and limits the speed of each "
        "connection, so collecting several chunks at once is usually much faster "
        "than one after another.\n\n"
        "4 suits most connections. Try 8 on fast wired internet. Drop to 1 or 2 if "
        "downloads keep failing partway through.",
    "cookiefile":
        "Another way to reach videos that need you signed in, and the one that "
        "actually works reliably on Windows.\n\n"
        "Install a browser add-on such as 'Get cookies.txt', save a cookies file "
        "while viewing YouTube, then select it here.\n\n"
        "Leave this empty unless you need it. When set, it overrides the "
        "'Sign in via' box above.",
    "choose":
        "Browse for a cookies.txt file you saved from your browser.",
    "folder":
        "When downloading a playlist, give it its own folder named after the "
        "playlist.\n\n"
        "Turn this off and everything lands loose in your main download folder.",
    "number":
        "Put the position number at the front of each filename, like "
        "'001 - Episode Title'.\n\n"
        "This keeps videos sitting in playlist order rather than alphabetical "
        "order.",
    "archive":
        "Remember what you've already downloaded and don't fetch it twice.\n\n"
        "Run the same playlist again next month and only the new videos come "
        "down. Genuinely useful for a series or channel you follow.\n\n"
        "The record is a small text file kept in your download folder.",
    "subs":
        "Also fetch subtitles and store them inside the video file.\n\n"
        "Falls back to YouTube's automatic captions when no proper subtitles "
        "exist. Choose the languages in the box below.",
    "metadata":
        "Save the title, channel name, description and upload date inside the "
        "file itself.\n\n"
        "Media players and music apps can then display that information.",
    "thumb":
        "Save the video's cover image inside the file, so it appears as artwork "
        "in your media player.\n\n"
        "Especially nice for audio-only downloads.",
    "restrict":
        "Remove spaces, accented letters and unusual symbols from filenames.\n\n"
        "Worth turning on if you'll copy files to a USB stick, an older device, "
        "or another operating system that struggles with those characters.",
    "sublangs":
        "Which subtitle languages to fetch, written as two-letter codes.\n\n"
        "'en' means English. Separate several with commas, like:  en,es,fr",
    "queue":
        "Links waiting to be downloaded, worked through one at a time.\n\n"
        "Titles and channel names are filled in shortly after a link is added, "
        "so you can check you queued the right thing. Playlists also show how "
        "many videos they contain.\n\n"
        "Paste several links and leave it running. If one fails, the rest carry "
        "on regardless.",
    "addqueue":
        "Add the link in the URL box to the queue.\n\n"
        "You can also paste several links at once, one per line, or drag a link "
        "straight onto this window.",
    "paste":
        "Paste a link from the clipboard into the URL box.",
    "removeitem":
        "Remove the selected link from the queue.\n\n"
        "Anything already downloaded stays on your computer.",
    "clearqueue":
        "Empty the queue.\n\n"
        "Only removes the list of links; downloaded files are untouched.",
    "retryfailed":
        "Put everything that failed back in the queue to try again.\n\n"
        "Downloads often fail for temporary reasons and succeed on a second "
        "attempt. With 'Skip already downloaded' switched on, videos that worked "
        "the first time are passed over, so only the failures are retried.",
    "openlogs":
        "Open the folder holding ClipStash's log files.\n\n"
        "Each run is recorded to a file. If something goes wrong, the log says "
        "what happened and is worth sending on when reporting a problem.",
    "download":
        "Start downloading.\n\n"
        "The progress bars and the log underneath show what's happening.",
    "cancel":
        "Stop the download that's running.\n\n"
        "Partly finished files are kept, and downloading again picks up from "
        "where it stopped rather than starting over.",
    "openfolder":
        "Open your download folder in File Explorer.",
    "clearlog":
        "Empty the message log below. This doesn't touch any downloaded files.",
    "bar_item":
        "How far through the video currently downloading.",
    "bar_overall":
        "How far through the whole playlist, counted in finished videos.",
    "log":
        "Messages about what ClipStash is doing.\n\n"
        "Green lines are completed files, amber are warnings worth a glance, and "
        "red are errors.",
    "version":
        "Which version of yt-dlp is doing the downloading. That's the component "
        "that actually talks to YouTube.\n\n"
        "'bundled' means the copy that shipped with ClipStash.\n"
        "'updated' means a newer one you've since downloaded.",
    "appversion":
        "Which version of ClipStash you're running.",
    "appupdate":
        "Check whether a newer version of ClipStash is available.\n\n"
        "If there is one, it downloads and installs itself. ClipStash closes "
        "briefly during the update and reopens when it's finished.",
    "update":
        "Check for a newer version of yt-dlp.\n\n"
        "YouTube changes how it works fairly often, so if downloads suddenly stop "
        "working, updating here usually fixes it.",
}


def apply_cookie_opts(opts: dict[str, Any], cfg: "JobConfig") -> None:
    """
    Attach cookie settings. An explicit cookies.txt always wins over browser
    extraction, since it's the option that actually works reliably on Windows.
    """
    if cfg.cookies_file and Path(cfg.cookies_file).is_file():
        opts["cookiefile"] = cfg.cookies_file
    elif cfg.cookies_browser and cfg.cookies_browser != "None":
        opts["cookiesfrombrowser"] = (cfg.cookies_browser,)


COOKIE_ERROR_MARKERS = (
    "could not copy",
    "could not find",
    "unable to read",
    "failed to decrypt",
    "permission denied",
    "cookiesfrombrowser",
    "database",
)


def looks_like_cookie_error(message: str) -> bool:
    text = str(message).lower()
    if "cookie" not in text:
        return False
    return any(marker in text for marker in COOKIE_ERROR_MARKERS)


COOKIE_HELP = (
    "ClipStash couldn't read cookies from your browser.\n\n"
    "On Windows this happens for two reasons, and both may apply:\n\n"
    "  1. The browser locks its cookie database while it's running. "
    "Fully quitting the browser (not just closing the window) sometimes "
    "clears this.\n\n"
    "  2. Chrome and Edge 127 and later encrypt cookies in a way yt-dlp "
    "cannot decrypt at all. If this is the cause, closing the browser "
    "will not help.\n\n"
    "What to do:\n\n"
    "  • If the video or playlist is public, you don't need cookies. "
    "Set 'Sign in via' to None and try again.\n\n"
    "  • If you need to be signed in — for private, unlisted, members-only "
    "or age-restricted content — install a 'Get cookies.txt' extension in "
    "your browser, export cookies for youtube.com, and select that file in "
    "the 'Cookie file' box instead."
)


def find_icon(extension: str) -> Path | None:
    """
    Locate a bundled icon file at runtime.

    The spec copies these into an `assets` folder inside the bundle; when
    running from source they sit in the repo's assets folder instead.
    """
    name = f"icon.{extension}"
    for candidate in (
        bundle_dir() / "assets" / name,
        bundle_dir() / name,
        executable_dir() / "assets" / name,
        Path(__file__).resolve().parent / "assets" / name,
    ):
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


# Held for the process lifetime. Inno Setup checks for this name via AppMutex,
# which lets the installer notice ClipStash is running and close it cleanly
# instead of failing on locked files mid-update.
APP_MUTEX_NAME = "ClipStashRunningMutex"
_mutex_handle = None


def claim_app_mutex() -> None:
    """Create the named mutex the installer looks for. Harmless if it fails."""
    global _mutex_handle
    if os.name != "nt":
        return
    try:
        import ctypes
        _mutex_handle = ctypes.windll.kernel32.CreateMutexW(None, False, APP_MUTEX_NAME)
    except Exception:
        pass


def set_taskbar_identity() -> None:
    """
    Give Windows an explicit application ID.

    Without one, Windows treats a Python-hosted window as belonging to the
    interpreter and may show its icon on the taskbar instead of ours. Must run
    before any window is created.
    """
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ClipStash.App.1")
    except Exception:
        pass


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle."""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def bundle_dir() -> Path:
    """Directory holding bundled resources (PyInstaller temp dir, or the source dir)."""
    if is_frozen():
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent


def executable_dir() -> Path:
    """Directory the user actually launched us from, for side-by-side ffmpeg."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def find_ffmpeg() -> str | None:
    """
    Locate ffmpeg, preferring a copy shipped inside the bundle.

    Returns a directory path (which is what yt-dlp's ffmpeg_location wants),
    or None to let yt-dlp search PATH itself.
    """
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    candidates = [
        bundle_dir() / exe,
        bundle_dir() / "bin" / exe,
        executable_dir() / exe,
        executable_dir() / "bin" / exe,
    ]
    # macOS .app layout: Contents/MacOS/clipstash -> Contents/Resources/ffmpeg
    if sys.platform == "darwin" and is_frozen():
        candidates.append(executable_dir().parent / "Resources" / exe)

    for path in candidates:
        if path.is_file():
            return str(path.parent)

    on_path = shutil.which(exe)
    return str(Path(on_path).parent) if on_path else None


# --------------------------------------------------------------------------- #
# Job configuration
# --------------------------------------------------------------------------- #

QUEUE_STATUS = {
    "pending":   "Waiting",
    "running":   "Downloading",
    "done":      "Finished",
    "partial":   "Finished with errors",
    "failed":    "Failed",
    "cancelled": "Cancelled",
}


@dataclass
class QueueItem:
    """One URL waiting its turn, plus whatever we've learned about it."""
    url: str
    status: str = "pending"
    note: str = ""
    title: str = ""
    channel: str = ""
    is_playlist: bool = False
    count: int = 0
    looked_up: bool = False
    failed_ids: list = field(default_factory=list)
    cookie_opts: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        """What to show in the Link column."""
        if not self.title:
            return self.url
        if self.is_playlist and self.count:
            return f"{self.title}  ({self.count} videos)"
        if self.is_playlist:
            return f"{self.title}  (playlist)"
        return self.title

    @property
    def retryable(self) -> bool:
        return self.status in ("failed", "partial", "cancelled")


@dataclass
class JobConfig:
    url: str
    output_dir: Path
    quality: str = "Best available"
    playlist_items: str = ""          # e.g. "1-10,15,20-"
    folder_per_playlist: bool = True
    number_playlist_items: bool = True
    use_archive: bool = True          # skip files already downloaded
    write_subtitles: bool = False
    subtitle_langs: str = "en"
    embed_metadata: bool = True
    embed_thumbnail: bool = False
    restrict_filenames: bool = False
    cookies_browser: str = "None"
    cookies_file: str = ""
    concurrent_fragments: int = 4
    extra_args: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Downloader (runs off the UI thread)
# --------------------------------------------------------------------------- #

class MetadataFetcher(threading.Thread):
    """
    Looks up titles and channel names for queued links.

    Runs as a single long-lived worker rather than a thread per item. That is
    deliberate: firing off ten simultaneous lookups when someone pastes ten
    links is a good way to attract rate limiting, and the results are only
    cosmetic, so there is nothing to gain from doing them at once.

    Failures are silent by design. Not knowing a video's title is a small
    cosmetic loss; it must never produce an error dialog or stop the link from
    being downloaded perfectly well a moment later.
    """

    def __init__(self, out: queue.Queue):
        super().__init__(daemon=True)
        self.out = out
        self.work: queue.Queue = queue.Queue()
        # Not named _stop: threading.Thread already has a private _stop()
        # method that Python calls during teardown, and shadowing it with an
        # Event breaks is_alive() and thread cleanup.
        self._stop_event = threading.Event()

    def request(self, url: str, cookie_opts: dict) -> None:
        self.work.put((url, cookie_opts))

    def stop(self) -> None:
        self._stop_event.set()
        self.work.put((None, None))

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                url, cookie_opts = self.work.get(timeout=0.5)
            except queue.Empty:
                continue
            if url is None or self._stop_event.is_set():
                return
            try:
                self.out.put(("meta_result", self._lookup(url, cookie_opts or {})))
            except Exception:
                pass

    def _lookup(self, url: str, cookie_opts: dict) -> dict:
        result = {"url": url, "title": "", "channel": "", "is_playlist": False, "count": 0}
        if yt_dlp is None:
            return result

        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            # Flatten playlist members so a 200-video playlist doesn't trigger
            # 200 separate extractions just to display its name.
            "extract_flat": "in_playlist",
            "ignoreerrors": True,
        }
        opts.update(cookie_opts)

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception:
            return result
        if not info:
            return result

        result["title"] = (info.get("title") or "").strip()
        result["channel"] = (
            info.get("channel") or info.get("uploader") or info.get("playlist_uploader") or ""
        ).strip()

        if info.get("_type") == "playlist":
            result["is_playlist"] = True
            entries = [e for e in (info.get("entries") or []) if e]
            result["count"] = info.get("playlist_count") or len(entries)

        return result


class QueueLogger:
    """Routes yt-dlp's internal messages into the UI queue."""

    def __init__(self, out: queue.Queue):
        self.out = out

    def debug(self, msg: str) -> None:
        if msg.startswith("[debug] "):
            return
        if msg.strip():
            self.out.put(("log", msg))

    def info(self, msg: str) -> None:
        self.out.put(("log", msg))

    def warning(self, msg: str) -> None:
        self.out.put(("log", self._tag("WARNING", msg)))

    def error(self, msg: str) -> None:
        self.out.put(("log", self._tag("ERROR", msg)))

    @staticmethod
    def _tag(level: str, msg: str) -> str:
        """yt-dlp already labels most of its own messages — don't stack prefixes."""
        text = str(msg).strip()
        while True:
            stripped = text.lstrip()
            for prefix in ("ERROR:", "WARNING:"):
                if stripped.upper().startswith(prefix):
                    text = stripped[len(prefix):].lstrip()
                    break
            else:
                break
        return f"{level}: {text}"


class Downloader(threading.Thread):
    def __init__(self, config: JobConfig, out: queue.Queue, cancel: threading.Event):
        super().__init__(daemon=True)
        self.config = config
        self.out = out
        self.cancel = cancel
        self.completed = 0
        self.failed = 0
        self.total = 1
        self.current_title = ""

    # -- yt-dlp option construction ---------------------------------------- #

    def _format_selector(self) -> tuple[str, list[dict], str | None]:
        q = self.config.quality
        postprocessors: list[dict] = []
        merge_format: str | None = "mp4"

        if q == "Audio only — MP3":
            postprocessors.append(
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "0"}
            )
            return "bestaudio/best", postprocessors, None
        if q == "Audio only — original (m4a/opus)":
            return "bestaudio/best", postprocessors, None
        if q == "Best available":
            return "bestvideo*+bestaudio/best", postprocessors, merge_format

        height = {
            "4K (2160p) or below": 2160,
            "1440p or below": 1440,
            "1080p or below": 1080,
            "720p or below": 720,
            "480p or below": 480,
            "360p or below": 360,
        }[q]
        fmt = (
            f"bestvideo[height<=?{height}]+bestaudio/"
            f"best[height<=?{height}]/best"
        )
        return fmt, postprocessors, merge_format

    def _output_template(self, is_playlist: bool) -> str:
        parts: list[str] = []
        if is_playlist and self.config.folder_per_playlist:
            parts.append("%(playlist_title)s")

        name = ""
        if is_playlist and self.config.number_playlist_items:
            name += "%(playlist_index)03d - "
        name += "%(title)s [%(id)s].%(ext)s"
        parts.append(name)
        return os.path.join(str(self.config.output_dir), *parts)

    def _build_opts(self, is_playlist: bool) -> dict[str, Any]:
        fmt, postprocessors, merge_format = self._format_selector()
        cfg = self.config

        opts: dict[str, Any] = {
            "format": fmt,
            "outtmpl": self._output_template(is_playlist),
            "logger": QueueLogger(self.out),
            "progress_hooks": [self._progress_hook],
            "postprocessor_hooks": [self._postprocessor_hook],
            "quiet": True,
            "no_warnings": False,
            "noprogress": True,
            "ignoreerrors": True,        # one bad video shouldn't kill a 300-item playlist
            "retries": 5,
            "fragment_retries": 10,
            "concurrent_fragment_downloads": max(1, cfg.concurrent_fragments),
            "restrictfilenames": cfg.restrict_filenames,
            "windowsfilenames": os.name == "nt",
            "overwrites": False,
            "continuedl": True,
        }

        apply_cookie_opts(opts, cfg)

        ffmpeg_dir = find_ffmpeg()
        if ffmpeg_dir:
            opts["ffmpeg_location"] = ffmpeg_dir

        if merge_format:
            opts["merge_output_format"] = merge_format
        if cfg.playlist_items.strip():
            opts["playlist_items"] = cfg.playlist_items.strip()
        if cfg.use_archive:
            archive = cfg.output_dir / ".clipstash-archive.txt"
            opts["download_archive"] = str(archive)
        if cfg.write_subtitles:
            opts["writesubtitles"] = True
            opts["writeautomaticsub"] = True
            opts["subtitleslangs"] = [s.strip() for s in cfg.subtitle_langs.split(",") if s.strip()]
            postprocessors.append({"key": "FFmpegEmbedSubtitle", "already_have_subtitle": False})
        if cfg.embed_metadata:
            postprocessors.append({"key": "FFmpegMetadata", "add_metadata": True})
        if cfg.embed_thumbnail:
            opts["writethumbnail"] = True
            postprocessors.append({"key": "EmbedThumbnail", "already_have_thumbnail": False})
        if postprocessors:
            opts["postprocessors"] = postprocessors
        opts.update(cfg.extra_args)
        return opts

    # -- hooks -------------------------------------------------------------- #

    def _check_cancel(self) -> None:
        if self.cancel.is_set():
            raise DownloadCancelled("Cancelled by user")

    def _progress_hook(self, d: dict[str, Any]) -> None:
        self._check_cancel()
        status = d.get("status")

        if status == "downloading":
            info = d.get("info_dict") or {}
            title = info.get("title") or Path(d.get("filename", "")).name
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes") or 0
            pct = (done / total * 100) if total else None
            self.out.put((
                "progress",
                {
                    "title": title,
                    "percent": pct,
                    "downloaded": done,
                    "total": total,
                    "speed": d.get("speed"),
                    "eta": d.get("eta"),
                    "index": self.completed + 1,
                    "count": self.total,
                },
            ))
        elif status == "finished":
            self.out.put(("log", f"Downloaded stream, post-processing: {Path(d.get('filename','')).name}"))
        elif status == "error":
            self.failed += 1

    def _postprocessor_hook(self, d: dict[str, Any]) -> None:
        self._check_cancel()
        if d.get("status") == "started":
            self.out.put(("log", f"  → {d.get('postprocessor', 'postprocessor')}"))

    # -- main --------------------------------------------------------------- #

    def run(self) -> None:
        cfg = self.config
        try:
            cfg.output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.out.put(("error", f"Cannot create output folder: {exc}"))
            return

        self.out.put(("status", "Fetching metadata…"))

        # Pre-flight: work out whether this is a playlist and how many items.
        probe_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",
            "skip_download": True,
            "logger": QueueLogger(self.out),
        }
        apply_cookie_opts(probe_opts, cfg)

        is_playlist = False
        try:
            with yt_dlp.YoutubeDL(probe_opts) as ydl:
                info = ydl.extract_info(cfg.url, download=False)
            if info is None:
                raise DownloadError("No information returned for that URL.")
            if info.get("_type") == "playlist":
                is_playlist = True
                entries = [e for e in (info.get("entries") or []) if e]
                self.total = len(entries) or 1
                self.out.put((
                    "meta",
                    {"title": info.get("title") or "Playlist", "count": self.total, "playlist": True},
                ))
            else:
                self.total = 1
                self.out.put((
                    "meta",
                    {"title": info.get("title") or cfg.url, "count": 1, "playlist": False},
                ))
        except DownloadCancelled:
            self.out.put(("cancelled", None))
            return
        except Exception as exc:
            using_cookies = bool(
                (cfg.cookies_file and Path(cfg.cookies_file).is_file())
                or (cfg.cookies_browser and cfg.cookies_browser != "None")
            )
            if using_cookies and looks_like_cookie_error(exc):
                self.out.put(("cookie_error", str(exc)))
            else:
                self.out.put(("error", f"Could not read that URL: {exc}"))
            return

        if self.cancel.is_set():
            self.out.put(("cancelled", None))
            return

        self.out.put(("status", "Downloading…"))
        started = time.time()
        try:
            with yt_dlp.YoutubeDL(self._build_opts(is_playlist)) as ydl:
                ydl.add_post_hook(self._on_file_done)
                ydl.download([cfg.url])
        except DownloadCancelled:
            self.out.put(("cancelled", None))
            return
        except Exception as exc:
            self.out.put(("error", str(exc)))
            return

        elapsed = time.time() - started
        self.out.put((
            "done",
            {"completed": self.completed, "failed": self.failed, "elapsed": elapsed},
        ))

    def _on_file_done(self, filepath: str) -> None:
        """Called by yt-dlp once each final file is fully written."""
        self.completed += 1
        self.out.put(("log", f"✓ [{self.completed}/{self.total}] {Path(filepath).name}"))
        self.out.put(("item_done", {"completed": self.completed, "count": self.total}))


# --------------------------------------------------------------------------- #
# GUI
# --------------------------------------------------------------------------- #

class App(TK_BASE):  # tk.Tk, or TkinterDnD.Tk when drag and drop is available
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_NAME)
        # Raised when the queue panel was added: below roughly this height the
        # queue and log both get squeezed to nothing, since they are the two
        # rows that absorb spare space.
        self.minsize(820, 780)
        self._icon_image: tk.PhotoImage | None = None
        self._apply_window_icon()
        self.palette = theme.apply(self) if theme else {}
        self._start_session_log()

        self.queue: queue.Queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker: Downloader | None = None

        # Saved preferences are read before the widgets exist, so _build_vars
        # can start every control at the value the user last chose.
        self.settings = appsettings.load() if appsettings else {}

        self.items: list[QueueItem] = []
        self.current_index: int | None = None
        self.processing = False
        self.metadata = MetadataFetcher(self.queue)
        self.metadata.start()
        self.last_config: JobConfig | None = None
        self.update_window: tk.Toplevel | None = None
        self.app_update_window: tk.Toplevel | None = None
        self.btn_appupdate: ttk.Button | None = None
        self.pending_release = None

        self._build_vars()
        self._build_ui()
        self.after(100, self._pump_queue)
        # Let the window finish drawing before touching the network, so a slow
        # or blocked connection can't delay the app appearing.
        self.after(2500, self._start_background_check)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._restore_geometry()
        self._register_drop_target()

        if yt_dlp is None:
            self.after(
                200,
                lambda: messagebox.showerror(
                    "yt-dlp not installed",
                    "This app needs yt-dlp.\n\nInstall it with:\n\n    pip install -U yt-dlp\n\n"
                    "You also need ffmpeg on your PATH for merging and MP3 conversion.",
                ),
            )
        elif find_ffmpeg() is None:
            self.after(
                200,
                lambda: messagebox.showwarning(
                    "ffmpeg not found",
                    "ffmpeg isn't bundled with this build and isn't on your PATH.\n\n"
                    "Downloads will still work, but YouTube serves high-resolution video and "
                    "audio as separate streams that need merging — without ffmpeg you'll be "
                    "capped around 720p, and MP3 conversion won't run.\n\n"
                    "Install it from https://ffmpeg.org/download.html, or drop an ffmpeg "
                    "binary next to this application.",
                ),
            )

    # -- state -------------------------------------------------------------- #

    def _apply_window_icon(self) -> None:
        """
        Set the title-bar and taskbar icon.

        Windows wants a real .ico via iconbitmap; everything else needs a
        PhotoImage via iconphoto. The PhotoImage reference has to be kept alive
        on the instance, or Tk garbage-collects it and the icon silently
        reverts to the default feather.
        """
        if os.name == "nt":
            ico = find_icon("ico")
            if ico:
                try:
                    # default=True applies to dialogs and child windows too.
                    self.iconbitmap(default=str(ico))
                    return
                except tk.TclError:
                    pass

        png = find_icon("png")
        if png:
            try:
                self._icon_image = tk.PhotoImage(file=str(png))
                self.iconphoto(True, self._icon_image)
            except tk.TclError:
                pass

    def _build_vars(self) -> None:
        s = self.settings

        def saved(key, fallback):
            value = s.get(key, fallback)
            return fallback if value is None else value

        # The URL box is deliberately never restored: reopening with an old link
        # already filled in invites downloading it again by accident.
        self.var_url = tk.StringVar()
        self.var_dir = tk.StringVar(
            value=saved("output_dir", "") or str(default_download_dir()))
        self.var_quality = tk.StringVar(value=saved("quality", QUALITY_PRESETS[0]))
        self.var_items = tk.StringVar(value=saved("playlist_items", ""))
        self.var_folder = tk.BooleanVar(value=saved("folder_per_playlist", True))
        self.var_number = tk.BooleanVar(value=saved("number_playlist_items", True))
        self.var_archive = tk.BooleanVar(value=saved("use_archive", True))
        self.var_subs = tk.BooleanVar(value=saved("write_subtitles", False))
        self.var_sublangs = tk.StringVar(value=saved("subtitle_langs", "en"))
        self.var_metadata = tk.BooleanVar(value=saved("embed_metadata", True))
        self.var_thumb = tk.BooleanVar(value=saved("embed_thumbnail", False))
        self.var_restrict = tk.BooleanVar(value=saved("restrict_filenames", False))
        self.var_browser = tk.StringVar(value=saved("cookies_browser", "None"))
        self.var_cookiefile = tk.StringVar(value=saved("cookies_file", ""))
        self.var_frags = tk.IntVar(value=saved("concurrent_fragments", 4))
        self.var_queue = tk.StringVar(value="Queue is empty.")
        self.var_version = tk.StringVar(value="")
        self.var_appversion = tk.StringVar(
            value=f"ClipStash {appversion.__version__}" if appversion else "ClipStash")

        self.var_status = tk.StringVar(value="Ready.")
        self.var_detail = tk.StringVar(value="")
        self.var_overall = tk.StringVar(value="")

    # -- layout ------------------------------------------------------------- #

    def _tip(self, key: str, *widgets) -> None:
        """Attach a hover description to a control and, usually, its label."""
        if theme is None:
            return
        text = HELP.get(key)
        if text:
            theme.tip(text, *[w for w in widgets if w is not None])

    def _build_ui(self) -> None:
        pad = {"padx": 8, "pady": 4}
        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)   # queue
        root.rowconfigure(5, weight=2)   # log, given the larger share

        # --- Source -------------------------------------------------------- #
        src = ttk.LabelFrame(root, text="Source", padding=10)
        src.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        src.columnconfigure(1, weight=1)

        url_label = ttk.Label(src, text="URL")
        url_label.grid(row=0, column=0, sticky="w", **pad)
        url_entry = ttk.Entry(src, textvariable=self.var_url)
        url_entry.grid(row=0, column=1, sticky="ew", **pad)
        url_entry.focus_set()
        self.url_entry = url_entry
        self._tip("url", url_label, url_entry)

        url_buttons = ttk.Frame(src)
        url_buttons.grid(row=0, column=2, sticky="w", **pad)
        paste_btn = ttk.Button(url_buttons, text="Paste", width=7, command=self._paste_url)
        paste_btn.pack(side="left")
        add_btn = ttk.Button(url_buttons, text="Add to queue", command=self._add_to_queue)
        add_btn.pack(side="left", padx=(6, 0))
        self._tip("paste", paste_btn)
        self._tip("addqueue", add_btn)

        # Enter starts a download from the URL box, which is what people expect
        # after typing or pasting a link.
        url_entry.bind("<Return>", lambda _e: self._start())

        dir_label = ttk.Label(src, text="Save to")
        dir_label.grid(row=1, column=0, sticky="w", **pad)
        dir_entry = ttk.Entry(src, textvariable=self.var_dir)
        dir_entry.grid(row=1, column=1, sticky="ew", **pad)
        browse_btn = ttk.Button(src, text="Browse\u2026", command=self._choose_dir)
        browse_btn.grid(row=1, column=2, **pad)
        self._tip("savedir", dir_label, dir_entry)
        self._tip("browse", browse_btn)

        # --- Options ------------------------------------------------------- #
        opt = ttk.LabelFrame(root, text="Options", padding=10)
        opt.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        opt.columnconfigure(1, weight=1)
        opt.columnconfigure(3, weight=1)

        quality_label = ttk.Label(opt, text="Quality")
        quality_label.grid(row=0, column=0, sticky="w", **pad)
        quality_box = ttk.Combobox(
            opt, textvariable=self.var_quality, values=QUALITY_PRESETS,
            state="readonly", width=28,
        )
        quality_box.grid(row=0, column=1, sticky="w", **pad)
        self._tip("quality", quality_label, quality_box)

        items_label = ttk.Label(opt, text="Playlist items")
        items_label.grid(row=0, column=2, sticky="e", **pad)
        items = ttk.Entry(opt, textvariable=self.var_items, width=18)
        items.grid(row=0, column=3, sticky="w", **pad)
        self._tip("items", items_label, items)

        browser_label = ttk.Label(opt, text="Sign in via")
        browser_label.grid(row=1, column=0, sticky="w", **pad)
        browser_box = ttk.Combobox(
            opt, textvariable=self.var_browser, values=BROWSERS,
            state="readonly", width=14,
        )
        browser_box.grid(row=1, column=1, sticky="w", **pad)
        self._tip("browser", browser_label, browser_box)

        frag_label = ttk.Label(opt, text="Parallel fragments")
        frag_label.grid(row=1, column=2, sticky="e", **pad)
        frag_box = ttk.Spinbox(opt, from_=1, to=16, textvariable=self.var_frags, width=6)
        frag_box.grid(row=1, column=3, sticky="w", **pad)
        self._tip("fragments", frag_label, frag_box)

        cookie_label = ttk.Label(opt, text="Cookie file")
        cookie_label.grid(row=2, column=0, sticky="w", **pad)
        cookie_entry = ttk.Entry(opt, textvariable=self.var_cookiefile)
        cookie_entry.grid(row=2, column=1, columnspan=2, sticky="ew", **pad)
        cookie_btn = ttk.Button(opt, text="Choose\u2026", command=self._choose_cookies)
        cookie_btn.grid(row=2, column=3, sticky="w", **pad)
        self._tip("cookiefile", cookie_label, cookie_entry)
        self._tip("choose", cookie_btn)

        checks = ttk.Frame(opt)
        checks.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(6, 0))

        row_one = [
            ("Folder per playlist", self.var_folder, "folder"),
            ("Number playlist items", self.var_number, "number"),
            ("Skip already downloaded", self.var_archive, "archive"),
        ]
        for col, (label, var, key) in enumerate(row_one):
            box = ttk.Checkbutton(checks, text=label, variable=var)
            box.grid(row=0, column=col, sticky="w", padx=(0, 16))
            self._tip(key, box)

        row_two = [
            ("Subtitles", self.var_subs, "subs"),
            ("Embed metadata", self.var_metadata, "metadata"),
            ("Embed thumbnail", self.var_thumb, "thumb"),
            ("Safe filenames", self.var_restrict, "restrict"),
        ]
        for col, (label, var, key) in enumerate(row_two):
            box = ttk.Checkbutton(checks, text=label, variable=var)
            box.grid(row=1, column=col, sticky="w", padx=(0, 16))
            self._tip(key, box)

        sublang_label = ttk.Label(checks, text="Subtitle languages")
        sublang_label.grid(row=2, column=0, sticky="w", pady=(6, 0))
        sublang_entry = ttk.Entry(checks, textvariable=self.var_sublangs, width=18)
        sublang_entry.grid(row=2, column=1, sticky="w", pady=(6, 0))
        self._tip("sublangs", sublang_label, sublang_entry)

        # --- Queue --------------------------------------------------------- #
        qframe = ttk.LabelFrame(root, text="Queue", padding=8)
        qframe.grid(row=2, column=0, sticky="nsew", pady=(0, 10))
        qframe.columnconfigure(0, weight=1)
        qframe.rowconfigure(0, weight=1, minsize=130)

        self.tree = ttk.Treeview(qframe, columns=("channel", "status"), height=5,
                                 selectmode="extended")
        self.tree.heading("#0", text="Video / Playlist", anchor="w")
        self.tree.heading("channel", text="Channel", anchor="w")
        self.tree.heading("status", text="Status", anchor="w")
        self.tree.column("#0", anchor="w", stretch=True, minwidth=240)
        self.tree.column("channel", anchor="w", width=170, stretch=False)
        self.tree.column("status", anchor="w", width=170, stretch=False)
        self.tree.grid(row=0, column=0, sticky="nsew")
        self._tip("queue", self.tree)

        tscroll = ttk.Scrollbar(qframe, orient="vertical", command=self.tree.yview)
        tscroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=tscroll.set)
        self.tree.bind("<Delete>", lambda _e: self._remove_selected())

        if theme:
            p = self.palette
            self.tree.tag_configure("done", foreground=p["ok"])
            self.tree.tag_configure("failed", foreground=p["error"])
            self.tree.tag_configure("partial", foreground=p["warn"])
            self.tree.tag_configure("running", foreground=p["info_hi"])
            self.tree.tag_configure("cancelled", foreground=p["muted"])
            self.tree.tag_configure("pending", foreground=p["fg"])

        qbuttons = ttk.Frame(qframe)
        qbuttons.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        remove_btn = ttk.Button(qbuttons, text="Remove", command=self._remove_selected)
        remove_btn.pack(side="left")
        clearq_btn = ttk.Button(qbuttons, text="Clear queue", command=self._clear_queue)
        clearq_btn.pack(side="left", padx=6)
        self.btn_retry = ttk.Button(qbuttons, text="Retry failed",
                                    command=self._retry_failed, state="disabled")
        self.btn_retry.pack(side="left")
        ttk.Label(qbuttons, textvariable=self.var_queue, style="Muted.TLabel").pack(side="right")
        self._tip("removeitem", remove_btn)
        self._tip("clearqueue", clearq_btn)
        self._tip("retryfailed", self.btn_retry)

        # --- Actions ------------------------------------------------------- #
        act = ttk.Frame(root)
        act.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        self.btn_start = ttk.Button(act, text="Download", command=self._start,
                                    style="Accent.TButton")
        self.btn_start.pack(side="left")
        self.btn_cancel = ttk.Button(act, text="Cancel", command=self._cancel, state="disabled")
        self.btn_cancel.pack(side="left", padx=8)
        open_btn = ttk.Button(act, text="Open folder", command=self._open_dir)
        open_btn.pack(side="left")
        clear_btn = ttk.Button(act, text="Clear log", command=self._clear_log)
        clear_btn.pack(side="right")
        logs_btn = ttk.Button(act, text="Open logs", command=self._open_logs)
        logs_btn.pack(side="right", padx=(0, 6))
        self._tip("openlogs", logs_btn)
        self._tip("download", self.btn_start)
        self._tip("cancel", self.btn_cancel)
        self._tip("openfolder", open_btn)
        self._tip("clearlog", clear_btn)

        # --- Progress ------------------------------------------------------ #
        prog = ttk.Frame(root)
        prog.grid(row=4, column=0, sticky="ew", pady=(0, 8))
        prog.columnconfigure(0, weight=1)

        ttk.Label(prog, textvariable=self.var_status, style="Heading.TLabel",
                  font=("", 10, "bold")).grid(row=0, column=0, sticky="w")
        self.bar_item = ttk.Progressbar(prog, mode="determinate", maximum=100,
                                        style="Horizontal.TProgressbar")
        self.bar_item.grid(row=1, column=0, sticky="ew", pady=(4, 2))
        detail_label = ttk.Label(prog, textvariable=self.var_detail, style="Muted.TLabel")
        detail_label.grid(row=2, column=0, sticky="w")
        self._tip("bar_item", self.bar_item, detail_label)

        # Overall progress in the accent red so the two bars read apart at a glance.
        self.bar_overall = ttk.Progressbar(prog, mode="determinate", maximum=100,
                                           style="Accent.Horizontal.TProgressbar")
        self.bar_overall.grid(row=3, column=0, sticky="ew", pady=(8, 2))
        overall_label = ttk.Label(prog, textvariable=self.var_overall, style="Muted.TLabel")
        overall_label.grid(row=4, column=0, sticky="w")
        self._tip("bar_overall", self.bar_overall, overall_label)

        # --- Log ----------------------------------------------------------- #
        logframe = ttk.LabelFrame(root, text="Log", padding=6)
        logframe.grid(row=5, column=0, sticky="nsew")
        logframe.columnconfigure(0, weight=1)
        logframe.rowconfigure(0, weight=1, minsize=120)

        self.log = tk.Text(logframe, height=12, wrap="none", state="disabled")
        self.log.grid(row=0, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(logframe, orient="vertical", command=self.log.yview)
        yscroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=yscroll.set)
        self._tip("log", self.log)

        if theme:
            theme.style_text(self.log)
            p = self.palette
            self.log.tag_configure("error", foreground=p["error"])
            self.log.tag_configure("warn", foreground=p["warn"])
            self.log.tag_configure("ok", foreground=p["ok"])
            self.log.tag_configure("head", foreground=p["info_hi"])

        # --- Footer -------------------------------------------------------- #
        footer = ttk.Frame(root)
        footer.grid(row=6, column=0, sticky="ew", pady=(8, 0))

        app_label = ttk.Label(footer, textvariable=self.var_appversion, style="Muted.TLabel")
        app_label.pack(side="left")
        self._tip("appversion", app_label)

        version_label = ttk.Label(footer, textvariable=self.var_version, style="Muted.TLabel")
        version_label.pack(side="left", padx=(14, 0))
        self._tip("version", version_label)

        update_btn = ttk.Button(footer, text="Update yt-dlp\u2026", command=self._open_updater)
        update_btn.pack(side="right")
        self._tip("update", update_btn)

        # Only offered when a feed is configured, so builds without one don't
        # show a button that can only ever fail.
        if app_update is not None and app_update.is_configured():
            self.btn_appupdate = ttk.Button(footer, text="Check for updates",
                                            command=self._open_app_updater)
            self.btn_appupdate.pack(side="right", padx=(0, 8))
            self._tip("appupdate", self.btn_appupdate)

        self._refresh_version_label()

    def _restore_geometry(self) -> None:
        """Reopen at the size the user left it, if it still fits on screen."""
        geometry = (self.settings or {}).get("window_geometry", "")
        if not geometry:
            return
        try:
            size = geometry.split("+")[0]
            width, height = (int(n) for n in size.split("x"))
            if 600 <= width <= self.winfo_screenwidth() and 400 <= height <= self.winfo_screenheight():
                self.geometry(geometry)
        except Exception:
            pass  # a nonsense saved geometry just means default sizing

    def _register_drop_target(self) -> None:
        if not HAVE_DND:
            return
        try:
            self.drop_target_register(DND_TEXT, DND_FILES)
            self.dnd_bind("<<Drop>>", self._on_drop)
        except Exception:
            pass

    # -- settings ----------------------------------------------------------- #

    def _collect_settings(self) -> dict:
        return {
            "output_dir": self.var_dir.get().strip(),
            "quality": self.var_quality.get(),
            "playlist_items": self.var_items.get().strip(),
            "folder_per_playlist": bool(self.var_folder.get()),
            "number_playlist_items": bool(self.var_number.get()),
            "use_archive": bool(self.var_archive.get()),
            "write_subtitles": bool(self.var_subs.get()),
            "subtitle_langs": self.var_sublangs.get().strip(),
            "embed_metadata": bool(self.var_metadata.get()),
            "embed_thumbnail": bool(self.var_thumb.get()),
            "restrict_filenames": bool(self.var_restrict.get()),
            "cookies_browser": self.var_browser.get(),
            "cookies_file": self.var_cookiefile.get().strip(),
            "concurrent_fragments": int(self.var_frags.get()),
            "window_geometry": self.geometry(),
        }

    def _save_settings(self) -> None:
        if appsettings is None:
            return
        try:
            appsettings.save(self._collect_settings())
        except Exception:
            pass  # preferences are a convenience, never worth an error dialog

    def _on_close(self) -> None:
        """Save preferences, then leave - warning first if work is in progress."""
        if self.processing:
            if not messagebox.askyesno(
                APP_NAME,
                "A download is still running.\n\nClose ClipStash anyway?",
            ):
                return
            self.cancel_event.set()
        self._save_settings()
        try:
            self.metadata.stop()
        except Exception:
            pass
        if applog:
            applog.write("ClipStash closed")
        self.destroy()

    # -- session log -------------------------------------------------------- #

    def _start_session_log(self) -> None:
        if applog is None:
            return
        try:
            log = applog.session()
            log.header(
                appversion.__version__ if appversion else "unknown",
                yt_dlp.version.__version__ if yt_dlp else "not installed",
                find_ffmpeg(),
            )
        except Exception:
            pass

    def _open_logs(self) -> None:
        if applog is None or not applog.open_folder():
            messagebox.showinfo(APP_NAME, "The log folder isn't available in this build.")

    # -- conveniences ------------------------------------------------------- #

    def _paste_url(self) -> None:
        try:
            text = self.clipboard_get()
        except tk.TclError:
            messagebox.showinfo(APP_NAME, "There's nothing on the clipboard to paste.")
            return
        text = (text or "").strip()
        if not text:
            return
        # Several links at once go straight to the queue; a single one lands in
        # the box so it can still be looked at before starting.
        if len(self._extract_urls(text)) > 1:
            self._enqueue_text(text)
        else:
            self.var_url.set(text)

    def _on_drop(self, event) -> None:
        """A link or file dropped onto the window."""
        data = getattr(event, "data", "") or ""
        # Tk wraps paths containing spaces in braces; strip them before parsing.
        data = data.replace("{", " ").replace("}", " ")
        found = self._extract_urls(data)
        if not found:
            self._append("WARNING: Nothing that looks like a link was dropped.")
            return
        if len(found) == 1 and not self.var_url.get().strip():
            self.var_url.set(found[0])
        else:
            self._enqueue_text(data)

    @staticmethod
    def _extract_urls(text: str) -> list[str]:
        """Pull every http(s) link out of arbitrary pasted or dropped text."""
        found = re.findall(r'https?://\S+', text or "")
        cleaned = []
        for item in found:
            item = item.strip().strip('\'\"<>,;')
            if item and item not in cleaned:
                cleaned.append(item)
        return cleaned

    # -- queue -------------------------------------------------------------- #

    def _cookie_snapshot(self) -> dict:
        """
        Capture cookie settings on the main thread for the lookup worker.

        Tk variables can only be read from the thread that owns the widgets, so
        the values are taken here and handed over as a plain dict rather than
        read inside the worker.
        """
        config = JobConfig(url="", output_dir=Path("."),
                           cookies_browser=self.var_browser.get(),
                           cookies_file=self.var_cookiefile.get().strip())
        opts: dict = {}
        apply_cookie_opts(opts, config)
        return opts

    def _request_metadata(self, item: QueueItem) -> None:
        if yt_dlp is None or item.looked_up:
            return
        try:
            self.metadata.request(item.url, item.cookie_opts)
        except Exception:
            pass


    def _enqueue_text(self, text: str) -> int:
        """Add every link found in some text. Returns how many were added."""
        added = 0
        existing = {item.url for item in self.items}
        for url in self._extract_urls(text):
            if url in existing:
                continue
            item = QueueItem(url=url, cookie_opts=self._cookie_snapshot())
            self.items.append(item)
            self._request_metadata(item)
            existing.add(url)
            added += 1
        if added:
            self._refresh_queue()
            self._append(f"Added {added} link{'s' if added != 1 else ''} to the queue.")
        return added

    def _add_to_queue(self) -> None:
        raw = self.var_url.get().strip()
        if not raw:
            messagebox.showinfo(APP_NAME, "Put a link in the URL box first.")
            return
        found = self._extract_urls(raw)
        if not found:
            # Not a recognisable link, but yt-dlp accepts more than plain URLs,
            # so it's queued as typed rather than rejected outright.
            item = QueueItem(url=raw, cookie_opts=self._cookie_snapshot())
            self.items.append(item)
            self._request_metadata(item)
            self._refresh_queue()
        else:
            self._enqueue_text(raw)
        self.var_url.set("")

    def _refresh_queue(self) -> None:
        """Redraw the queue list and the counts beside it."""
        selected = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        for index, item in enumerate(self.items):
            note = f"  -  {item.note}" if item.note else ""
            channel = item.channel or ("" if item.looked_up else "looking up...")
            self.tree.insert(
                "", "end", iid=str(index), text=item.label,
                values=(channel, QUEUE_STATUS.get(item.status, item.status) + note),
                tags=(item.status,),
            )
        for iid in selected:
            if self.tree.exists(iid):
                self.tree.selection_add(iid)

        if not self.items:
            self.var_queue.set("Queue is empty.")
        else:
            counts = {}
            for item in self.items:
                counts[item.status] = counts.get(item.status, 0) + 1
            parts = [f"{n} {QUEUE_STATUS.get(k, k).lower()}" for k, n in counts.items()]
            self.var_queue.set(f"{len(self.items)} in queue  ({', '.join(parts)})")

        self.btn_retry.configure(
            state="normal" if any(i.retryable for i in self.items) and not self.processing
            else "disabled")

    def _remove_selected(self) -> None:
        chosen = sorted((int(i) for i in self.tree.selection()), reverse=True)
        if not chosen:
            return
        for index in chosen:
            if index == self.current_index and self.processing:
                continue  # can't remove the one being downloaded
            if 0 <= index < len(self.items):
                del self.items[index]
        self.current_index = None
        self._refresh_queue()

    def _clear_queue(self) -> None:
        if self.processing:
            messagebox.showinfo(APP_NAME, "Stop the current download before clearing the queue.")
            return
        self.items.clear()
        self._refresh_queue()

    def _retry_failed(self) -> None:
        """
        Requeue everything that didn't finish.

        Individual videos that failed inside a playlist are added as their own
        links, so a retry fetches exactly those rather than walking the whole
        playlist again. Where no specific video could be identified, the original
        link is retried instead; with 'Skip already downloaded' switched on,
        yt-dlp passes over whatever already succeeded.
        """
        retried = 0
        existing = {item.url for item in self.items if item.status == "pending"}

        for item in list(self.items):
            if not item.retryable:
                continue
            for video_id in item.failed_ids:
                url = f"https://www.youtube.com/watch?v={video_id}"
                if url not in existing:
                    fresh = QueueItem(url=url, cookie_opts=self._cookie_snapshot())
                    self.items.append(fresh)
                    self._request_metadata(fresh)
                    existing.add(url)
                    retried += 1
            if not item.failed_ids and item.url not in existing:
                fresh = QueueItem(url=item.url, title=item.title, channel=item.channel,
                                  is_playlist=item.is_playlist, count=item.count,
                                  looked_up=item.looked_up,
                                  cookie_opts=self._cookie_snapshot())
                self.items.append(fresh)
                existing.add(item.url)
                retried += 1

        if not retried:
            messagebox.showinfo(APP_NAME, "Nothing to retry.")
            return

        self._refresh_queue()
        self._append(f"Requeued {retried} item{'s' if retried != 1 else ''} to retry.")
        self._start()

    def _choose_dir(self) -> None:
        chosen = filedialog.askdirectory(initialdir=self.var_dir.get() or str(Path.home()))
        if chosen:
            self.var_dir.set(chosen)

    def _choose_cookies(self) -> None:
        chosen = filedialog.askopenfilename(
            title="Select a cookies.txt file",
            filetypes=[("Cookie files", "*.txt"), ("All files", "*.*")],
        )
        if chosen:
            self.var_cookiefile.set(chosen)

    def _open_dir(self) -> None:
        path = Path(self.var_dir.get())
        path.mkdir(parents=True, exist_ok=True)
        if sys.platform == "darwin":
            os.system(f'open "{path}"')
        elif os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            os.system(f'xdg-open "{path}"')

    def _clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _append(self, text: str) -> None:
        line = text.rstrip()
        tag = ()
        if theme:
            lowered = line.lower()
            if lowered.startswith("error:"):
                tag = ("error",)
            elif lowered.startswith("warning:"):
                tag = ("warn",)
            elif line.startswith("✓") or line.startswith("Done"):
                tag = ("ok",)
            elif line.startswith("---"):
                tag = ("head",)
        self.log.configure(state="normal")
        self.log.insert("end", line + "\n", tag)
        self.log.see("end")
        self.log.configure(state="disabled")

        if line.lower().startswith("error:"):
            self._record_failed_video(line)

        if applog is not None:
            level = "ERROR" if tag == ("error",) else "WARN" if tag == ("warn",) else "INFO"
            applog.write(line, level)

    def _start(self) -> None:
        """Begin working through the queue, adding the URL box first if filled."""
        if yt_dlp is None:
            messagebox.showerror(APP_NAME, "yt-dlp is not installed.\n\npip install -U yt-dlp")
            return
        if self.processing:
            return
        if not self.var_dir.get().strip():
            messagebox.showwarning(APP_NAME, "Choose a folder to save into.")
            return

        typed = self.var_url.get().strip()
        if typed:
            self._add_to_queue()

        if not any(item.status == "pending" for item in self.items):
            messagebox.showinfo(
                APP_NAME,
                "Nothing to download.\n\nPaste a link in the URL box, or add links "
                "to the queue.")
            return

        # Options are saved whenever a download starts, so a crash or power cut
        # mid-download doesn't lose the settings the user just chose.
        self._save_settings()

        self.processing = True
        self.btn_start.configure(state="disabled")
        self.btn_cancel.configure(state="normal")
        self.btn_retry.configure(state="disabled")
        self._process_next()

    def _process_next(self) -> None:
        """Start the next waiting item, or finish up if there are none left."""
        nxt = next((i for i, item in enumerate(self.items)
                    if item.status == "pending"), None)

        if nxt is None:
            self.processing = False
            self.current_index = None
            self.btn_start.configure(state="normal")
            self.btn_cancel.configure(state="disabled")
            self.bar_item["value"] = 0
            self.bar_overall["value"] = 0

            finished = sum(1 for i in self.items if i.status == "done")
            problems = sum(1 for i in self.items if i.status in ("failed", "partial"))
            self.var_status.set(
                f"Queue finished. {finished} completed"
                + (f", {problems} with problems." if problems else "."))
            self._append(f"Queue finished - {finished} completed, {problems} with problems.")
            if applog:
                applog.write(f"Queue finished: {finished} ok, {problems} problems")
            self._refresh_queue()
            return

        self.current_index = nxt
        item = self.items[nxt]
        item.status = "running"
        item.failed_ids = []
        self._refresh_queue()
        self.tree.see(str(nxt))

        self._append(f"--- {item.url} ---")
        if applog:
            applog.write(f"Starting: {item.url}")

        config = JobConfig(
            url=item.url,
            output_dir=Path(self.var_dir.get()).expanduser(),
            quality=self.var_quality.get(),
            playlist_items=self.var_items.get(),
            folder_per_playlist=self.var_folder.get(),
            number_playlist_items=self.var_number.get(),
            use_archive=self.var_archive.get(),
            write_subtitles=self.var_subs.get(),
            subtitle_langs=self.var_sublangs.get(),
            embed_metadata=self.var_metadata.get(),
            embed_thumbnail=self.var_thumb.get(),
            restrict_filenames=self.var_restrict.get(),
            cookies_browser=self.var_browser.get(),
            cookies_file=self.var_cookiefile.get().strip(),
            concurrent_fragments=int(self.var_frags.get()),
        )
        self._start_job(config)

    def _start_job(self, config: JobConfig) -> None:
        self.last_config = config
        self.cancel_event = threading.Event()
        self.worker = Downloader(config, self.queue, self.cancel_event)
        self.worker.start()

        self.btn_start.configure(state="disabled")
        self.btn_cancel.configure(state="normal")
        self.bar_item["value"] = 0
        self.bar_overall["value"] = 0
        self.var_status.set("Starting…")
        self._append(f"--- {config.url} ---")

    # -- updater ------------------------------------------------------------ #

    def _refresh_version_label(self) -> None:
        if yt_dlp is None:
            self.var_version.set("yt-dlp not available")
            return
        version = yt_dlp.version.__version__
        source = "bundled"
        if updater is not None and updater.active_version():
            source = "updated"
        self.var_version.set(f"yt-dlp {version} ({source})")

    def _open_app_updater(self) -> None:
        if app_update is None or not app_update.is_configured():
            messagebox.showinfo(
                APP_NAME,
                "This build has no update source configured, so it can't check "
                "for new versions.")
            return
        if self.app_update_window is not None and self.app_update_window.winfo_exists():
            self.app_update_window.lift()
            return
        self.app_update_window = AppUpdateDialog(self)

    def _start_background_check(self) -> None:
        """
        Look for a newer ClipStash shortly after launch, quietly.

        Deliberately undemanding: no dialog, no modal interruption. If an update
        exists the footer button relabels itself and the log gains one line. A
        popup on every launch would train people to dismiss it without reading.
        """
        if app_update is None or not app_update.is_configured():
            return

        def worker() -> None:
            try:
                available, release = app_update.check()
                if available:
                    self.queue.put(("app_update_available", release))
            except Exception:
                pass  # a silent check that fails should stay silent

        threading.Thread(target=worker, daemon=True).start()

    def _open_updater(self) -> None:
        if updater is None:
            messagebox.showerror(APP_NAME, "The updater module isn't available in this build.")
            return
        if self.update_window is not None and self.update_window.winfo_exists():
            self.update_window.lift()
            return
        self.update_window = UpdateDialog(self)

    def _handle_cookie_error(self) -> None:
        """Explain the failure, and offer the fix that works for public content."""
        retry = messagebox.askyesno(
            "Couldn't read browser cookies",
            COOKIE_HELP + "\n\nTry again now without signing in?",
            icon="warning",
        )
        if not retry or self.last_config is None:
            return

        self.var_browser.set("None")
        self.var_cookiefile.set("")
        retry_config = replace(self.last_config, cookies_browser="None", cookies_file="")
        self._append("Retrying without cookies…")
        self._start_job(retry_config)

    def _cancel(self) -> None:
        self.cancel_event.set()
        self.var_status.set("Cancelling…")
        self.btn_cancel.configure(state="disabled")

    def _finish(self) -> None:
        """One queue item ended. Buttons stay disabled while more remain."""
        self.worker = None
        if not self.processing:
            self.btn_start.configure(state="normal")
            self.btn_cancel.configure(state="disabled")
            self._refresh_queue()

    def _mark_current(self, status: str, note: str = "") -> None:
        if self.current_index is None or not (0 <= self.current_index < len(self.items)):
            return
        item = self.items[self.current_index]
        item.status = status
        item.note = note
        self._refresh_queue()
        if applog:
            applog.write(f"{item.url} -> {status}{(' (' + note + ')') if note else ''}")

    def _record_failed_video(self, line: str) -> None:
        """
        Note individual videos that failed inside a playlist.

        yt-dlp reports these as lines like "ERROR: [youtube] dQw4w9WgXcQ: ...".
        Capturing the id means Retry can fetch exactly those, instead of walking
        the entire playlist again.
        """
        if self.current_index is None:
            return
        match = re.search(r'\[youtube[^\]]*\]\s+([A-Za-z0-9_-]{11})', line)
        if not match:
            match = re.search(r'watch\?v=([A-Za-z0-9_-]{11})', line)
        if not match:
            return
        item = self.items[self.current_index]
        video_id = match.group(1)
        if video_id not in item.failed_ids:
            item.failed_ids.append(video_id)

    # -- UI queue pump ------------------------------------------------------ #

    def _pump_queue(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()

                if kind == "log":
                    self._append(payload)

                elif kind == "meta_result":
                    # Matched by URL rather than position: the list may have been
                    # reordered or had rows removed while the lookup was running.
                    for item in self.items:
                        if item.url != payload["url"]:
                            continue
                        item.looked_up = True
                        if payload["title"]:
                            item.title = payload["title"]
                            item.channel = payload["channel"]
                            item.is_playlist = payload["is_playlist"]
                            item.count = payload["count"]
                        break
                    self._refresh_queue()

                elif kind == "meta":
                    label = "Playlist" if payload["playlist"] else "Video"
                    self._append(f"{label}: {payload['title']} ({payload['count']} item(s))")
                    self.var_overall.set(f"0 of {payload['count']} complete")

                elif kind == "status":
                    self.var_status.set(payload)

                elif kind == "progress":
                    pct = payload["percent"]
                    self.bar_item.configure(mode="determinate" if pct is not None else "indeterminate")
                    if pct is not None:
                        self.bar_item["value"] = pct
                    title = payload["title"]
                    if len(title) > 70:
                        title = title[:67] + "…"
                    self.var_status.set(f"[{payload['index']}/{payload['count']}] {title}")
                    speed = f"{human_bytes(payload['speed'])}/s" if payload["speed"] else "—"
                    self.var_detail.set(
                        f"{human_bytes(payload['downloaded'])} of {human_bytes(payload['total'])}"
                        f"   ·   {speed}   ·   ETA {human_time(payload['eta'])}"
                    )

                elif kind == "item_done":
                    done, count = payload["completed"], max(1, payload["count"])
                    self.bar_overall["value"] = min(100, done / count * 100)
                    self.var_overall.set(f"{done} of {count} complete")

                elif kind == "cancelled":
                    self.var_status.set("Cancelled.")
                    self.var_detail.set("")
                    self._append("Cancelled by user.")
                    self._mark_current("cancelled")
                    # Cancel stops the whole queue, not just this item - someone
                    # pressing Cancel wants everything to stop.
                    self.processing = False
                    self._finish()

                elif kind == "app_update_available":
                    self.pending_release = payload
                    when = getattr(payload, "published", "")
                    self._append(
                        f"ClipStash {payload.version} is available"
                        + (f" (published {when})" if when else "")
                        + " - use 'Check for updates' below to install it.")
                    if self.btn_appupdate is not None:
                        self.btn_appupdate.configure(
                            text=f"Update to {payload.version}", style="Accent.TButton")

                elif kind == "cookie_error":
                    self.var_status.set("Couldn't read browser cookies.")
                    self.var_detail.set("")
                    self._append(f"ERROR: {payload}")
                    self._finish()
                    self._handle_cookie_error()

                elif kind == "error":
                    self.var_status.set("Failed.")
                    self.var_detail.set("")
                    self._append(f"ERROR: {payload}")
                    self._mark_current("failed", str(payload)[:80])
                    self._finish()
                    # No dialog when a queue is running: one bad link in twenty
                    # shouldn't stop the batch and wait for someone to click OK.
                    if self.processing:
                        self._process_next()
                    else:
                        messagebox.showerror(APP_NAME, str(payload))

                elif kind == "done":
                    self.bar_item["value"] = 100
                    self.bar_overall["value"] = 100
                    self.var_detail.set("")
                    self._append(
                        f"Done - {payload['completed']} file(s) in {human_time(payload['elapsed'])}."
                    )
                    failures = payload.get("failed", 0)
                    current = (self.items[self.current_index]
                               if self.current_index is not None
                               and self.current_index < len(self.items) else None)
                    if current and (failures or current.failed_ids):
                        count = len(current.failed_ids) or failures
                        self._mark_current("partial", f"{count} item(s) failed")
                    else:
                        self._mark_current("done", f"{payload['completed']} file(s)")
                    self.var_status.set("Finished.")
                    self._finish()
                    if self.processing:
                        self._process_next()

        except queue.Empty:
            pass
        self.after(100, self._pump_queue)


class AppUpdateDialog(tk.Toplevel):
    """
    Checks for a newer ClipStash, downloads it, and hands over to the installer.

    The handover is the delicate part. Windows locks a running executable, so
    ClipStash cannot replace its own files. Instead it starts the installer
    detached and exits immediately; the installer waits for the app to release
    its lock, swaps the files, and reopens it.
    """

    def __init__(self, parent: App):
        super().__init__(parent)
        self.parent = parent
        self.title("Update ClipStash")
        self.resizable(False, False)
        self.transient(parent)
        if theme:
            self.configure(background=theme.PALETTE["bg"])

        self.queue: queue.Queue = queue.Queue()
        self.release = None
        self.installer: Path | None = None
        self.busy = False

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)

        self.var_installed = tk.StringVar(
            value=f"Installed:  {appversion.__version__}" if appversion else "Installed:  unknown")
        self.var_latest = tk.StringVar(value="Latest:  checking\u2026")

        ttk.Label(frame, textvariable=self.var_installed).grid(row=0, column=0, sticky="w")
        ttk.Label(frame, textvariable=self.var_latest).grid(row=1, column=0, sticky="w", pady=(2, 10))

        self.bar = ttk.Progressbar(frame, mode="indeterminate", length=400)
        self.bar.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self.bar.start(12)

        self.var_note = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self.var_note, wraplength=400, justify="left").grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(0, 6))

        self.notes_heading = ttk.Label(frame, text="What's new", style="Heading.TLabel",
                                       font=("", 10, "bold"))
        self.notes_heading.grid(row=4, column=0, sticky="w", pady=(2, 4))
        self.notes_heading.grid_remove()

        self.notes_box = tk.Text(frame, height=8, width=56, wrap="word", state="disabled")
        self.notes_box.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        if theme:
            theme.style_text(self.notes_box)
        self.notes_box.grid_remove()

        buttons = ttk.Frame(frame)
        buttons.grid(row=6, column=0, columnspan=2, sticky="ew")
        self.btn_install = ttk.Button(buttons, text="Download and install", state="disabled",
                                      command=self._install, style="Accent.TButton")
        self.btn_install.pack(side="left")
        self.btn_close = ttk.Button(buttons, text="Close", command=self._close)
        self.btn_close.pack(side="right")

        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(50, self._pump)
        threading.Thread(target=self._check_worker, daemon=True).start()

    # -- workers ------------------------------------------------------------ #

    def _check_worker(self) -> None:
        try:
            available, release = app_update.check()
            self.queue.put(("checked", (available, release)))
        except Exception as exc:
            self.queue.put(("failed", str(exc)))

    def _download_worker(self, release) -> None:
        try:
            path = app_update.download(
                release, lambda done, total: self.queue.put(("progress", (done, total))))
            self.queue.put(("downloaded", path))
        except Exception as exc:
            self.queue.put(("failed", str(exc)))

    # -- actions ------------------------------------------------------------ #

    def _install(self) -> None:
        if self.release is None or self.busy:
            return
        if self.parent.worker is not None:
            messagebox.showwarning(
                "Download in progress",
                "A video download is still running. Let it finish, or cancel it, "
                "before updating ClipStash.",
                parent=self,
            )
            return

        self.busy = True
        self.btn_install.configure(state="disabled")
        self.var_note.set("Downloading\u2026")
        self.bar.stop()
        self.bar.configure(mode="determinate", maximum=100, value=0)
        threading.Thread(target=self._download_worker, args=(self.release,), daemon=True).start()

    def _hand_over(self) -> None:
        if self.installer is None:
            return
        proceed = messagebox.askokcancel(
            "Ready to install",
            "ClipStash will now close and the update will install itself.\n\n"
            "It reopens automatically when it's done, usually within a minute.",
            parent=self,
        )
        if not proceed:
            self.var_note.set(
                f"Update downloaded but not installed.\n\nYou can run it yourself later:\n{self.installer}")
            self.btn_install.configure(text="Install now", state="normal")
            self.busy = False
            return

        try:
            app_update.apply_and_exit(self.installer)
        except Exception as exc:
            self.busy = False
            self.btn_install.configure(state="normal")
            messagebox.showerror("Couldn't start the installer", str(exc), parent=self)

    def _close(self) -> None:
        if self.busy:
            if not messagebox.askyesno("Update in progress",
                                       "The update is still downloading. Close anyway?",
                                       parent=self):
                return
        self.parent.app_update_window = None
        self.destroy()

    # -- queue pump --------------------------------------------------------- #

    def _show_notes(self, text: str) -> None:
        self.notes_box.grid()
        self.notes_box.configure(state="normal")
        self.notes_box.delete("1.0", "end")
        self.notes_box.insert("1.0", text)
        self.notes_box.configure(state="disabled")

    def _pump(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()

                if kind == "checked":
                    available, release = payload
                    self.release = release
                    self.bar.stop()
                    self.bar.configure(mode="determinate", maximum=100, value=0)
                    published = getattr(release, "published", "")
                    self.var_latest.set(
                        f"Latest:  {release.version}"
                        + (f"   (published {published})" if published else ""))
                    if available:
                        size = f" ({human_bytes(release.size)})" if release.size else ""
                        when = f", published {published}" if published else ""
                        self.var_note.set(
                            f"Version {release.version} is available{size}{when}.")
                        self.btn_install.configure(state="normal")
                        if release.notes:
                            self._show_notes(release.notes)
                            self.notes_heading.grid()
                    else:
                        self.var_note.set("You're running the latest version.")
                        self.bar.configure(value=100)

                elif kind == "progress":
                    done, total = payload
                    if total:
                        self.bar.configure(value=done / total * 100)
                        self.var_note.set(
                            f"Downloading\u2026 {human_bytes(done)} of {human_bytes(total)}")

                elif kind == "downloaded":
                    self.installer = payload
                    self.bar.configure(value=100)
                    self.var_note.set("Download complete and verified.")
                    self._hand_over()

                elif kind == "failed":
                    self.busy = False
                    self.bar.stop()
                    self.bar.configure(mode="determinate", value=0)
                    self.var_latest.set("Latest:  unknown")
                    self.var_note.set("Update check failed.")
                    self.btn_install.configure(state="disabled")
                    messagebox.showerror("Update failed", str(payload), parent=self)

        except queue.Empty:
            pass

        if self.winfo_exists():
            self.after(100, self._pump)


class UpdateDialog(tk.Toplevel):
    """
    Checks PyPI for a newer yt-dlp and installs it on request.

    Network work happens on a worker thread and reports back through a queue,
    same as downloads — Tkinter calls must stay on the main thread.
    """

    def __init__(self, parent: App):
        super().__init__(parent)
        self.parent = parent
        self.title("Update yt-dlp")
        self.resizable(False, False)
        self.transient(parent)
        if theme:
            # ttk styles are global, so the widgets inherit; only the Toplevel's
            # own background needs setting explicitly.
            self.configure(background=theme.PALETTE["bg"])

        self.queue: queue.Queue = queue.Queue()
        self.meta: dict[str, Any] | None = None
        self.busy = False

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame,
            text="YouTube changes often, and yt-dlp ships fixes most weeks.\n"
                 "Updating here replaces the copy built into this app.",
            justify="left",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))

        self.var_installed = tk.StringVar(value=f"Installed:  {updater.current_version()}")
        self.var_latest = tk.StringVar(value="Latest:  checking…")
        ttk.Label(frame, textvariable=self.var_installed).grid(row=1, column=0, sticky="w")
        ttk.Label(frame, textvariable=self.var_latest).grid(row=2, column=0, sticky="w", pady=(2, 10))

        self.bar = ttk.Progressbar(frame, mode="indeterminate", length=380)
        self.bar.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        self.bar.start(12)

        self.var_note = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self.var_note, wraplength=380, justify="left").grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(0, 12)
        )

        buttons = ttk.Frame(frame)
        buttons.grid(row=5, column=0, columnspan=2, sticky="ew")
        self.btn_install = ttk.Button(buttons, text="Install update", command=self._install,
                                      state="disabled", style="Accent.TButton")
        self.btn_install.pack(side="left")
        self.btn_close = ttk.Button(buttons, text="Close", command=self._close)
        self.btn_close.pack(side="right")

        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(50, self._pump)
        threading.Thread(target=self._check_worker, daemon=True).start()

    # -- workers ------------------------------------------------------------ #

    def _check_worker(self) -> None:
        try:
            available, meta = updater.check_for_update()
            self.queue.put(("checked", (available, meta)))
        except Exception as exc:
            self.queue.put(("failed", str(exc)))

    def _install_worker(self, meta: dict[str, Any]) -> None:
        try:
            updater.download_and_install(meta, lambda done, total: self.queue.put(
                ("progress", (done, total))
            ))
            updater.prune()
            self.queue.put(("installed", meta["version"]))
        except Exception as exc:
            self.queue.put(("failed", str(exc)))

    # -- actions ------------------------------------------------------------ #

    def _install(self) -> None:
        if self.meta is None or self.busy:
            return
        self.busy = True
        self.btn_install.configure(state="disabled")
        self.var_note.set("Downloading…")
        self.bar.configure(mode="determinate", maximum=100, value=0)
        threading.Thread(target=self._install_worker, args=(self.meta,), daemon=True).start()

    def _close(self) -> None:
        if self.busy:
            if not messagebox.askyesno(
                "Update in progress",
                "An update is still downloading. Close anyway?",
                parent=self,
            ):
                return
        self.parent.update_window = None
        self.destroy()

    # -- queue pump --------------------------------------------------------- #

    def _pump(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()

                if kind == "checked":
                    available, meta = payload
                    self.meta = meta
                    self.bar.stop()
                    self.bar.configure(mode="determinate", maximum=100, value=0)
                    self.var_latest.set(f"Latest:  {meta['version']}")
                    if available:
                        size = meta.get("size") or 0
                        self.var_note.set(
                            f"An update is available ({human_bytes(size)})."
                        )
                        self.btn_install.configure(state="normal")
                    else:
                        self.var_note.set("You're on the latest version.")
                        self.bar.configure(value=100)

                elif kind == "progress":
                    done, total = payload
                    if total:
                        self.bar.configure(value=done / total * 100)
                        self.var_note.set(f"Downloading… {human_bytes(done)} of {human_bytes(total)}")

                elif kind == "installed":
                    self.busy = False
                    self.bar.configure(value=100)
                    self.var_note.set(
                        f"yt-dlp {payload} installed. Restart ClipStash to start using it."
                    )
                    self.parent._append(f"Updated yt-dlp to {payload} — restart to apply.")
                    messagebox.showinfo(
                        "Update installed",
                        f"yt-dlp {payload} has been installed.\n\n"
                        "Restart ClipStash for the new version to take effect.",
                        parent=self,
                    )

                elif kind == "failed":
                    self.busy = False
                    self.bar.stop()
                    self.bar.configure(mode="determinate", value=0)
                    self.var_latest.set("Latest:  unknown")
                    self.var_note.set("Update check failed.")
                    messagebox.showerror("Update failed", str(payload), parent=self)

        except queue.Empty:
            pass

        if self.winfo_exists():
            self.after(100, self._pump)


def main() -> None:
    set_taskbar_identity()
    claim_app_mutex()
    app = App()
    try:
        app.tk.call("tk", "scaling", 1.2)
    except tk.TclError:
        pass
    app.mainloop()


if __name__ == "__main__":
    main()

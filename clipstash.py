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

class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_NAME)
        self.minsize(760, 620)
        self._icon_image: tk.PhotoImage | None = None
        self._apply_window_icon()
        self.palette = theme.apply(self) if theme else {}

        self.queue: queue.Queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker: Downloader | None = None
        self.last_config: JobConfig | None = None
        self.update_window: tk.Toplevel | None = None
        self.app_update_window: tk.Toplevel | None = None
        self.btn_appupdate: ttk.Button | None = None
        self.pending_release = None

        self._build_vars()
        self._build_ui()
        self.after(100, self._pump_queue)

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
        self.var_url = tk.StringVar()
        self.var_dir = tk.StringVar(value=str(default_download_dir()))
        self.var_quality = tk.StringVar(value=QUALITY_PRESETS[0])
        self.var_items = tk.StringVar()
        self.var_folder = tk.BooleanVar(value=True)
        self.var_number = tk.BooleanVar(value=True)
        self.var_archive = tk.BooleanVar(value=True)
        self.var_subs = tk.BooleanVar(value=False)
        self.var_sublangs = tk.StringVar(value="en")
        self.var_metadata = tk.BooleanVar(value=True)
        self.var_thumb = tk.BooleanVar(value=False)
        self.var_restrict = tk.BooleanVar(value=False)
        self.var_browser = tk.StringVar(value="None")
        self.var_cookiefile = tk.StringVar()
        self.var_frags = tk.IntVar(value=4)
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
        root.rowconfigure(4, weight=1)

        # --- Source -------------------------------------------------------- #
        src = ttk.LabelFrame(root, text="Source", padding=10)
        src.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        src.columnconfigure(1, weight=1)

        url_label = ttk.Label(src, text="URL")
        url_label.grid(row=0, column=0, sticky="w", **pad)
        url_entry = ttk.Entry(src, textvariable=self.var_url)
        url_entry.grid(row=0, column=1, columnspan=2, sticky="ew", **pad)
        url_entry.focus_set()
        self._tip("url", url_label, url_entry)

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

        # --- Actions ------------------------------------------------------- #
        act = ttk.Frame(root)
        act.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        self.btn_start = ttk.Button(act, text="Download", command=self._start,
                                    style="Accent.TButton")
        self.btn_start.pack(side="left")
        self.btn_cancel = ttk.Button(act, text="Cancel", command=self._cancel, state="disabled")
        self.btn_cancel.pack(side="left", padx=8)
        open_btn = ttk.Button(act, text="Open folder", command=self._open_dir)
        open_btn.pack(side="left")
        clear_btn = ttk.Button(act, text="Clear log", command=self._clear_log)
        clear_btn.pack(side="right")
        self._tip("download", self.btn_start)
        self._tip("cancel", self.btn_cancel)
        self._tip("openfolder", open_btn)
        self._tip("clearlog", clear_btn)

        # --- Progress ------------------------------------------------------ #
        prog = ttk.Frame(root)
        prog.grid(row=3, column=0, sticky="ew", pady=(0, 8))
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
        logframe.grid(row=4, column=0, sticky="nsew")
        logframe.columnconfigure(0, weight=1)
        logframe.rowconfigure(0, weight=1)

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
        footer.grid(row=5, column=0, sticky="ew", pady=(8, 0))

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

    def _start(self) -> None:
        if yt_dlp is None:
            messagebox.showerror(APP_NAME, "yt-dlp is not installed.\n\npip install -U yt-dlp")
            return
        url = self.var_url.get().strip()
        if not url:
            messagebox.showwarning(APP_NAME, "Paste a video or playlist URL first.")
            return
        if not self.var_dir.get().strip():
            messagebox.showwarning(APP_NAME, "Choose a folder to save into.")
            return

        config = JobConfig(
            url=url,
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
        self.btn_start.configure(state="normal")
        self.btn_cancel.configure(state="disabled")
        self.worker = None

    # -- UI queue pump ------------------------------------------------------ #

    def _pump_queue(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()

                if kind == "log":
                    self._append(payload)

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
                    self._finish()

                elif kind == "app_update_available":
                    self.pending_release = payload
                    self._append(
                        f"ClipStash {payload.version} is available - "
                        f"use 'Check for updates' below to install it.")
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
                    messagebox.showerror(APP_NAME, str(payload))
                    self._finish()

                elif kind == "done":
                    self.bar_item["value"] = 100
                    self.bar_overall["value"] = 100
                    self.var_status.set("Finished.")
                    self.var_detail.set("")
                    self._append(
                        f"Done — {payload['completed']} file(s) in {human_time(payload['elapsed'])}."
                    )
                    self._finish()

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

        self.notes_box = tk.Text(frame, height=6, width=52, wrap="word", state="disabled")
        self.notes_box.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        if theme:
            theme.style_text(self.notes_box)
        self.notes_box.grid_remove()

        buttons = ttk.Frame(frame)
        buttons.grid(row=5, column=0, columnspan=2, sticky="ew")
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
                    self.var_latest.set(f"Latest:  {release.version}")
                    if available:
                        size = f" ({human_bytes(release.size)})" if release.size else ""
                        self.var_note.set(f"Version {release.version} is available{size}.")
                        self.btn_install.configure(state="normal")
                        if release.notes:
                            self._show_notes(release.notes)
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

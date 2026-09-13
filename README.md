# ClipStash

A desktop app for downloading YouTube videos and playlists, built on
[yt-dlp](https://github.com/yt-dlp/yt-dlp) with a Tkinter interface.

Only download content you have the rights to — your own uploads, Creative
Commons material, or anything the rights holder permits. Bulk downloading
copyrighted material generally violates YouTube's Terms of Service. If you are
distributing this inside an organisation, that is worth raising with whoever
handles policy before it spreads.

---

## Who runs what

Easy to conflate, so stated plainly up front:

- **`build_gui.pyw`, `build.bat`, `build.py`** are *developer* tools. They
  compile the app. The people you give ClipStash to never see them.
- **`ClipStash-Setup-<version>.exe`** is what users run. An ordinary GUI
  installer wizard.

---

## Files

| File | Purpose |
| --- | --- |
| `clipstash.py` | The application. Run directly with `python clipstash.py`. |
| `version.py` | The version number. The only place it is written down. |
| `theme.py` | Colour palette, ttk theme, and the tooltip class. |
| `settings.py` | Saves and restores the user's options. |
| `applog.py` | Per-session log files on disk. |
| `history.py` | Record of what has been downloaded and where. |
| `crashhandler.py` | Turns unexpected errors into a readable message plus a log entry. |
| `updater.py` | Keeps the bundled yt-dlp current. Also resolves portable mode. |
| `app_update.py` | In-app self-update: checks the feed, verifies, hands off to the installer. |
| `build_gui.pyw` | Window-based front end for `build.py`. Double-click it; no console. |
| `build.bat` | Console launcher for `build.py`, if you prefer watching the output. |
| `build.py` | Build driver — prerequisites, ffmpeg, PyInstaller, Inno Setup, manifest. |
| `clipstash.spec` | PyInstaller build definition. |
| `installer.iss` | Inno Setup script producing the Windows installer. |
| `RELEASE_NOTES.txt` | What changed. Copied into the update manifest and shown to users. |
| `portable.txt.example` | Rename to `portable.txt` to enable portable mode. |
| `assets/` | Artwork: source SVGs, generated icons, installer wizard images. |

Keep everything except `assets/` in one folder, with `assets/` beside it.

---

## What the app does

**Downloading.** Single videos or entire playlists. Quality from 4K down to
360p, audio-only as MP3 or in the original format, or **subtitles / transcript
only** — which fetches just the captions and no video at all, turning a
500 MB download into a few kilobytes of text.

**Queue.** Add as many links as you like and leave it running. Titles, channel
names and playlist sizes fill in automatically so you can see what you queued.
A failure doesn't stop the batch, and **Retry failed** puts anything that didn't
finish back in the queue — for videos that failed inside a playlist, it requeues
exactly those rather than walking the whole playlist again.

**Getting links in.** Type or paste one, paste several at once, drag a link onto
the window, or switch on **Watch clipboard** and every YouTube address you copy
while browsing queues itself.

**Trimming and cleaning.** **Clip section** downloads only part of a video by
start and end time. **Remove sponsors** strips sponsor readings, self-promotion,
intros and outros via the SponsorBlock database. **Split at chapters** turns one
long video into a file per chapter.

**Being considerate.** **Start at** holds a queue until a set time, for running
large batches outside busy hours. **Pause** stops a download without losing
progress and resumes where it left off.

**Keeping track.** Every finished file is recorded in **History** with its
location. Queueing something you already have gets flagged with the date you got
it. ClipStash warns before starting if a queue looks likely to fill the drive,
and flashes in the taskbar when a queue finishes while you're in another window.

---

## Where user data lives

| Platform | Location |
| --- | --- |
| Windows | `%LOCALAPPDATA%\ClipStash\` |
| macOS | `~/Library/Application Support/ClipStash/` |
| Linux | `~/.local/share/ClipStash/` |

Containing `settings.json`, `history.json`, `logs/`, and `runtime/` (downloaded
yt-dlp updates).

### Portable mode

Rename `portable.txt.example` to `portable.txt` and put it next to
`ClipStash.exe`. Everything above then lives in a `Data` folder beside the
program instead, so the whole installation travels on a USB stick.

Because settings, logs, history and the yt-dlp runtime all derive their location
from one function in `updater.py`, that single marker moves the lot. The folder
is tested for writability before being accepted, so a write-protected stick
fails visibly rather than silently discarding every save.

Nothing is migrated automatically when you switch. Copy the `Data` folder
yourself if you want to keep your history.

---

## Building

Easiest: double-click **`build_gui.pyw`**. Tick your options, press Build, watch
the log panel. No console.

If double-clicking opens a text editor instead, right-click → Open with →
Python. Or use `build.bat`, which does the same thing in a console window.

From a terminal:

```
python build.py --onedir --extras --with-ffmpeg --installer
```

**PyInstaller does not cross-compile.** Build on Windows for a `.exe`, on macOS
for a `.app`, on Linux for an ELF binary. A Linux binary is also tied to the
glibc version of the machine that built it.

### Options

| Flag | Effect |
| --- | --- |
| `--installer` | Compile `installer.iss` into a setup `.exe` (needs Inno Setup) |
| `--with-ffmpeg` | Bundle ffmpeg: copy from PATH, or download a static build |
| `--fetch-ffmpeg` | Always download a static ffmpeg, ignoring any on PATH |
| `--extras` | Install yt-dlp's optional companions before building |
| `--onedir` | Folder build — starts faster, and what the installer expects |
| `--manifest` | Regenerate `latest.json` only, without rebuilding |
| `--debug` | Keep a console attached to the built app |
| `--clean` | Wipe `build/` and `dist/` first |

Expect roughly 25 MB without ffmpeg, or 100–200 MB with it bundled.

### Testing a folder build

`ClipStash.exe` and the `_internal` folder are **one unit**. Copying the exe on
its own produces "Failed to load Python DLL", because it looks for `_internal`
beside itself. Run it in place, or copy the whole folder.

---

## Making an installer

```
python build.py --onedir --with-ffmpeg --installer
```

Produces `installer_output\ClipStash-Setup-<version>.exe` plus `latest.json`.
Needs [Inno Setup 6](https://jrsoftware.org/isdl.php), which is free;
`build.py` finds `ISCC.exe` automatically.

The installer defaults to a **per-user install** (`PrivilegesRequired=lowest`),
so it works without admin rights — which matters on managed work and school
machines. Users can still choose a machine-wide install, which raises UAC.

It creates Start Menu and optional desktop shortcuts, blocks accidental
downgrades, and on uninstall asks whether to keep downloaded yt-dlp updates.

`AppMutex` matches a named mutex the app creates at startup. That is how Setup
notices ClipStash is running and closes it cleanly rather than failing on locked
files during an in-app update.

---

## Releasing an update

Users update from inside the app. A running `.exe` can't overwrite itself on
Windows, so ClipStash downloads your installer, starts it detached, and exits so
nothing stays locked. The installer swaps the files and reopens the app.

### One-time setup

Put your manifest address in `UPDATE_FEED_URL` at the top of `app_update.py`.
This GitHub permalink always resolves to the newest release:

```
https://github.com/OWNER/REPO/releases/latest/download/latest.json
```

Set `GITHUB_REPO` in the same file to `owner/repo` and the update dialog shows
the release description you wrote on GitHub, so you can fix a typo in your notes
without rebuilding. That is only consulted when an update actually exists —
GitHub allows 60 unauthenticated API calls per hour *per IP address*, shared by
everyone behind a school or office network.

A plain web server works too, as does a UNC path like
`\\fileserver\apps\clipstash\latest.json` for distributing internally without
publishing anything publicly.

Leave `UPDATE_FEED_URL` empty and the update button simply doesn't appear.

### Each release

1. Bump `__version__` in `version.py`.
2. Describe what changed in `RELEASE_NOTES.txt` — users read this in the update
   dialog. `build.py` warns if the version it mentions doesn't match the build.
3. Build with `--installer`.
4. Upload **both** `ClipStash-Setup-<version>.exe` and `latest.json` to a GitHub
   release tagged `v<version>`.

Both files, always. Every client verifies its download against the hash in the
manifest, so a mismatched pair is rejected everywhere.

**Improvements to the update system are invisible for exactly one release.** The
*currently running* version draws the update dialog, so a change to it only
shows once users are on a build containing it. Expect this and don't chase it.

### What protects users

The SHA-256 in the manifest proves the download matches what you published,
catching corruption and tampering in transit. It does **not** prove the manifest
itself is genuine — that rests on HTTPS. For an internal tool that is usually
acceptable. If ClipStash goes wider, sign the installer with a code-signing
certificate; Windows will then reject anything that isn't yours, and the
SmartScreen warning disappears as a bonus.

---

## The parts that actually cause trouble

**ffmpeg.** YouTube serves high-resolution video and audio as separate streams,
so without ffmpeg you're capped around 720p, and MP3 conversion, clipping,
chapter splitting and sponsor removal won't run. The app checks for a bundled
copy first, then PATH, and warns at startup if it finds neither.

`--with-ffmpeg` copies whatever is on your PATH. Fine on Windows, where builds
are static. On macOS and Linux, Homebrew and distro builds link against shared
libraries that won't exist elsewhere — use `--fetch-ffmpeg`, which downloads a
self-contained static build. The LGPL variant is chosen deliberately: it still
carries the MP3 encoder, and it is far less onerous if you redistribute.
Include ffmpeg's `COPYING.LGPLv2.1` alongside the installer to satisfy that.

**Extractors.** yt-dlp imports its ~1750 site extractors dynamically by name, so
PyInstaller's static analysis misses nearly all of them. The spec pulls them in
with `collect_submodules`. "Unsupported URL" from a frozen build but not from
source means that collection broke.

**macOS Gatekeeper.** An unsigned `.app` is quarantined on any Mac but the one
that built it. Recipients clear it with
`xattr -dr com.apple.quarantine /Applications/ClipStash.app`.

**Windows SmartScreen.** Unsigned executables *and installers* routinely trip
SmartScreen and antivirus heuristics. UPX is disabled in the spec because it
makes this measurably worse. On a managed network, application allowlisting may
block the installer outright regardless of what the user clicks.

**Staleness.** The bundled yt-dlp freezes at build time, and YouTube changes
often enough to break it every few weeks. The in-app updater handles this, and
the app now checks weekly on its own.

---

## Icons and artwork

`assets/icon.svg` is the full scene; `assets/icon-small.svg` is a simplified
mark. Below about 48px the full drawing turns to mush, so the 16, 24 and 32px
entries in the `.ico` use the simplified art — Windows picks whichever size it
needs, so the taskbar stays readable while larger contexts keep the scene.

Regenerate after editing either SVG:

```
pip install cairosvg pillow
python assets/make_icons.py
```

That also produces the installer's wizard BMPs — Inno requires BMP, not PNG,
and picks a size by display scaling, hence several of each.

**The rendered `.ico`, `.png`, `.icns` and `.bmp` files are committed even
though they are generated**, because cairosvg depends on Cairo's DLLs and
usually cannot be installed on Windows. Keeping them in the repo means a Windows
checkout builds without it. `installer.iss` probes for each artwork file before
referencing it, so a missing one degrades to default artwork rather than
aborting the compile.

---

## Theming

`theme.py` holds every colour, taken from the logo. Change a value there and the
app and build tool both follow.

Two Windows-specific traps. The default ttk theme draws widgets with native
Win32 calls and ignores background settings, so `apply()` switches to `clam`
first. And several widgets aren't ttk underneath — a Combobox's dropdown is a
plain Tk Listbox reachable only via the option database, while `tk.Text` and
`tk.Toplevel` need colouring directly.

The queue list needs particular care: Tk leaves entries in the Treeview colour
map that override selection colours, and `clam` adds its own `selected` entry
which wins because ttk uses the *first* match. Both are stripped before the
chosen colour is added. The selection colour is a muted blue rather than the
accent red, because row tags carry status colours whose foreground wins over the
selection foreground in Tk 8.6.10+.

The installer is themed separately in the `[Code]` section of `installer.iss`.
Inno's `TColor` is **BGR**, not RGB: `#1B2436` is written `$0036241B`. Only the
header band and welcome/finish headings are recoloured — body pages carry native
controls that ignore these settings, so darkening them would give black text on
a dark background.

⚠ ISPP, Inno's preprocessor, runs before any Pascal parsing and treats **any
line whose first non-blank character is `#`** as a directive — including inside
`{ }` comments. Never let a colour code begin a line in that file.

---

## If something goes wrong

**Start with the log.** Press **Open logs** in the app. Each run writes a file
recording the ClipStash version, yt-dlp version, whether ffmpeg was found, and
everything that happened. Unexpected errors are written there too, with a full
traceback. This answers most questions without another round of asking.

**"Could not copy Chrome cookie database"** — yt-dlp couldn't read browser
cookies. Two causes, often both: browsers lock the database while running, and
Chrome/Edge 127+ encrypt cookies in a way yt-dlp cannot decrypt at all. For
public videos you don't need cookies; set **Sign in via** to None. For private,
unlisted, members-only or age-restricted content, export a `cookies.txt` with a
browser extension and select it in **Cookie file**, which overrides the browser
setting.

**Updates never appear** — a stale manifest looks exactly like "no update
available". Run `python app_update.py` from the project folder; it prints what
the feed actually returns, separating a publishing problem from an app problem
in seconds. Manifest requests are sent uncacheable, but re-uploading
`latest.json` to the release is the fix if the asset itself went stale.

**Certificate errors** — something is inspecting HTTPS traffic, common on
managed networks. The updater trusts the OS certificate store first precisely so
corporate CAs installed by policy work. If it still fails, point `SSL_CERT_FILE`
at your organisation's root certificate.

**Subtitles come back empty** — the video has no captions in the languages
requested. Automatic captions are enabled, but not every video has even those.

**Sponsor removal does nothing** — SponsorBlock is a community database and
relies on someone having marked up that video. Well-known videos are usually
covered; obscure ones often aren't.

---

## Troubleshooting a failed build

Check `build/ClipStash/warn-ClipStash.txt` for missing modules, and re-run with
`--debug` so the console stays open.

If `build.py` reports tkinter missing:

- Debian/Ubuntu: `sudo apt install python3-tk`
- Fedora: `sudo dnf install python3-tkinter`
- macOS: python.org installer, or `brew install python-tk`
- Windows: re-run the Python installer and tick "tcl/tk and IDLE"

If the `py` launcher points at a Python that no longer exists, run `py -0p` to
see what it thinks is installed. `build.bat` tests each interpreter by running
it and falls back to any working one.

Drag-and-drop needs `tkinterdnd2`, which is in the recommended packages and
bundled by the spec. Without it everything works identically minus the drop
target.

# ClipStash

A desktop app for downloading YouTube videos and playlists, built on
[yt-dlp](https://github.com/yt-dlp/yt-dlp) with a Tkinter interface.

Only download content you have the rights to — your own uploads, Creative
Commons material, or anything the rights holder permits. Bulk downloading
copyrighted material generally violates YouTube's Terms of Service.

## Files

| File | Purpose |
| --- | --- |
| `clipstash.py` | The application. Runs directly with `python clipstash.py`. |
| `updater.py` | Self-updater for the bundled yt-dlp. Imported by the app; also runnable standalone. |
| `theme.py` | Colour palette and ttk theme, shared by the app and the build tool. |
| `version.py` | The version number. The only place it's written down. |
| `app_update.py` | In-app self-update: checks the feed, verifies the download, hands off to the installer. |
| `RELEASE_NOTES.txt` | What changed. Copied into the update manifest and shown to users. |
| `clipstash.spec` | PyInstaller build definition. |
| `build.py` | Build driver — checks prerequisites, vendors ffmpeg, runs PyInstaller and Inno Setup. |
| `build_gui.pyw` | Window-based front end for `build.py`. Double-click it; no console. |
| `build.bat` | Double-clickable launcher for `build.py`, for when you'd rather see the console. |
| `installer.iss` | Inno Setup script that produces the Windows installer. |
| `assets/icon.svg` | Source artwork: the robber and his sack of televisions. |
| `assets/icon-small.svg` | Simplified mark used below 48px, where the full scene stops being legible. |
| `assets/make_icons.py` | Renders the SVGs into `icon.ico`, `icon.icns`, `icon.png` and the installer's wizard BMPs. |

Keep `clipstash.py`, `updater.py`, `clipstash.spec`, `build.py` and `installer.iss`
in one directory, with `assets/` beside them.

## Who runs what

Worth being clear, because it's easy to conflate: **`build.py`, `build_gui.pyw`
and `build.bat` are developer tools.** People you give the app to never see
them. They run `ClipStash-Setup-<version>.exe`, which is an ordinary GUI
installer wizard.

## Building

Easiest: double-click **`build_gui.pyw`**. It opens a window, you tick the
options you want, press Build, and watch the output in the panel. No console.

If double-clicking it opens a text editor instead of running, right-click the
file, choose Open with, and pick Python. Or use `build.bat`, which does the same
thing in a console window.

From a terminal:

```
python build.py
```

That produces `dist/ClipStash` (or `ClipStash.exe` / `ClipStash.app`).

**PyInstaller does not cross-compile.** Run the build on Windows to get a
`.exe`, on macOS for a `.app`, on Linux for an ELF binary. A Linux binary is
also tied to the glibc version of the machine that built it, so build on the
oldest distro you intend to support.

### Options

| Flag | Effect |
| --- | --- |
| `--with-ffmpeg` | Copy `ffmpeg`/`ffprobe` from your PATH into the bundle |
| `--onedir` | Folder build instead of one file — starts in ~1s instead of ~5s |
| `--debug` | Keep a console window attached so tracebacks are visible |
| `--clean` | Wipe `build/` and `dist/` first |
| `--no-install` | Fail on missing build deps instead of pip-installing them |

Expect roughly 25 MB without ffmpeg, or 100–150 MB with it bundled.

## Making an installer

For handing this to people who shouldn't have to think about it:

```
python build.py --onedir --with-ffmpeg --installer
```

That produces `installer_output\ClipStash-Setup-1.0.0.exe`, a single file you
can send someone. It needs [Inno Setup 6](https://jrsoftware.org/isdl.php),
which is free; `build.py` finds `ISCC.exe` automatically in the usual install
locations, or you can put it on your PATH.

`installer.iss` defaults to a **per-user install** with
`PrivilegesRequired=lowest`, so it works without admin rights — which matters on
managed work and school machines. The user can still opt into a machine-wide
install, which raises a UAC prompt.

The installer also creates Start Menu and optional desktop shortcuts, blocks
accidental downgrades over a newer version, and on uninstall asks whether to
keep the downloaded yt-dlp so a reinstall doesn't have to fetch it again.

Note `--onedir`: `installer.iss` expects the folder build, since there's no
reason to pay the onefile unpack delay on every launch when an installer is
laying files down anyway. If you'd rather ship the single-file build, swap the
commented `Source:` line in the `[Files]` section.

Bump `AppVersion` in `installer.iss` for each release. Leave `AppId` alone —
Windows uses that GUID to recognise upgrades and to find the app at uninstall
time, so changing it strands the previous install.

## Icons

`assets/icon.svg` is the full scene; `assets/icon-small.svg` is a simplified
beanie-and-mask mark. Below roughly 48px the full drawing turns to mush, so the
16, 24 and 32px entries in the `.ico` use the simplified art instead — Windows
picks whichever size it needs, so the taskbar stays readable while larger
contexts keep the whole scene.

Edit either SVG and regenerate:

```
pip install cairosvg pillow
python assets/make_icons.py
```

`build.py` runs this automatically when the artwork is present but the icon
files aren't.

## Theming

`theme.py` holds every colour, each taken from the logo. Change a value there
and both the app and the build tool follow.

Two Windows-specific things make this work, and both are easy to trip over. The
default ttk theme there draws widgets with native Win32 calls and ignores
background settings entirely, so `apply()` switches to `clam` first. And a few
widgets aren't ttk underneath — a Combobox's dropdown is a plain Tk Listbox
reachable only via the option database, while `tk.Text` and `tk.Toplevel` need
colouring directly.

The installer is themed separately, in the `[Code]` section of `installer.iss`.
Note that Inno's `TColor` is **BGR**, not RGB: `#1B2436` is written `$0036241B`.
Getting that backwards produces a different colour rather than an error. Only
the header band and the welcome/finish headings are recoloured — the body pages
carry native edit boxes and buttons that Windows draws itself and that ignore
these settings, so darkening them would leave black text on a dark background.

## Releasing an update

Users get new versions from inside the app. A running `.exe` can't overwrite
itself on Windows, so ClipStash doesn't try: it downloads your installer, starts
it detached, and exits so nothing stays locked. The installer swaps the files
and reopens the app.

### One-time setup

Pick somewhere to host two files, then put its address in `UPDATE_FEED_URL` at
the top of `app_update.py`. Leave it empty and the update button simply doesn't
appear, so builds without hosting aren't broken.

GitHub Releases is the easiest option, because this permalink always points at
the newest release and so never needs changing:

```
https://github.com/OWNER/REPO/releases/latest/download/latest.json
```

Any web server works too. So does a UNC path such as
`\\fileserver\apps\clipstash\latest.json`, which suits distributing inside an
organisation without publishing anything publicly.

### Each release

1. Bump `__version__` in `version.py`.
2. Describe what changed in `RELEASE_NOTES.txt` — users read this in the update
   dialog.
3. Build with the installer option. `build.py` reads the version, passes it to
   Inno Setup, and writes `installer_output/latest.json` with the installer's
   SHA-256.
4. Upload **both** `ClipStash-Setup-<version>.exe` and `latest.json` to your
   hosting. They must travel together — every client checks the download against
   the hash in the manifest, so a mismatched pair is rejected by all of them.

Installed copies check quietly a couple of seconds after launch. If something
newer exists, the footer button relabels itself and one line appears in the log.
No popup, deliberately — an interruption on every launch teaches people to
dismiss it unread.

### What protects users

The SHA-256 in the manifest proves the download matches what you published, so
corruption and tampering in transit are caught. It does **not** prove the
manifest itself is genuine; that rests on HTTPS. Anyone able to modify the
manifest could point it at any executable. For an internal tool that's usually
acceptable. If ClipStash goes wider, sign the installer with a code-signing
certificate — Windows will then reject anything that isn't yours, and the
SmartScreen warning disappears as a bonus.

`AppMutex` in `installer.iss` matches a named mutex the app creates at startup.
That's how Setup notices ClipStash is running and closes it cleanly rather than
failing on locked files mid-update.

## The parts that actually cause trouble

**ffmpeg.** YouTube serves high-resolution video and audio as separate streams,
so without ffmpeg you're capped around 720p and MP3 conversion won't run. The
app checks for a bundled copy first, then falls back to PATH, and warns at
startup if it finds neither.

`--with-ffmpeg` copies whatever binary you already have. On Windows that's
almost always a self-contained static build and works fine. On macOS and Linux,
Homebrew and distro builds link against shared libraries that won't exist on
other machines — for a portable build, download a static build
([Linux](https://johnvansickle.com/ffmpeg), [macOS](https://evermeet.cx/ffmpeg))
and drop it in `./vendor/` yourself before building.

**Extractors.** yt-dlp imports its ~1750 site extractors dynamically by name,
so PyInstaller's static analysis misses nearly all of them. The spec pulls them
in with `collect_submodules`. If you ever see "Unsupported URL" from a frozen
build but not from the source, that collection is what broke.

**macOS Gatekeeper.** An unsigned `.app` is quarantined on any Mac other than
the one that built it. The recipient can clear it with:

```
xattr -dr com.apple.quarantine /Applications/ClipStash.app
```

Distributing properly means an Apple Developer ID, `codesign --deep --force
--sign`, and notarization via `xcrun notarytool`.

**Windows SmartScreen.** Unsigned PyInstaller executables — and unsigned
installers — routinely trip SmartScreen and antivirus heuristics — the onefile bootloader unpacking to a
temp directory looks a lot like packed malware. UPX compression is disabled in
the spec because it makes this notably worse. A code-signing certificate is the
only real fix.

**Staleness.** The bundled yt-dlp is frozen at build time, and YouTube changes
its player often enough that yt-dlp ships fixes most weeks. `updater.py`
handles this — see below.

## Updating yt-dlp

Click **Update yt-dlp…** in the bottom right. The footer shows which copy is
live, either `(bundled)` or `(updated)`. An update takes effect at next launch.

Under the hood, `updater.py` downloads yt-dlp's pure-Python wheel straight from
PyPI, verifies its SHA-256, and unzips it into a per-user directory:

| Platform | Location |
| --- | --- |
| Windows | `%LOCALAPPDATA%\ClipStash\runtime\` |
| macOS | `~/Library/Application Support/ClipStash/runtime/` |
| Linux | `~/.local/share/ClipStash/runtime/` |

No pip is involved, which matters because a frozen app has no pip and
`sys.executable` points at the app rather than an interpreter.

Getting the new copy to actually load takes one non-obvious step. PyInstaller
registers a `FrozenImporter` in `sys.meta_path`, and meta_path finders run
ahead of anything on `sys.path` — so merely prepending a directory does
nothing. `updater.activate()` installs a narrow finder in front of the frozen
one that claims `yt_dlp` and its submodules and nothing else. It must be called
before `import yt_dlp`, which is why it sits at the top of `clipstash.py`.

Versions install side by side as `yt-dlp-<version>/` rather than overwriting,
which sidesteps Windows' refusal to replace files mapped into a running
process. The newest valid one wins at startup; older ones are pruned. If an
install is corrupt, `activate()` falls back to the bundled copy rather than
failing to start.

Test the updater without launching the GUI:

```
python updater.py
```

## If downloads fail

**"Could not copy Chrome cookie database"** — yt-dlp couldn't read cookies from
your browser. Two causes, and both may apply at once: browsers lock the cookie
database while running, and Chrome/Edge 127 and later encrypt cookies in a way
yt-dlp cannot decrypt at all. If it's the second, closing the browser won't
help.

For public videos and playlists you don't need cookies — set **Sign in via** to
None. The app now detects this failure and offers to retry that way. If you
genuinely need to be signed in, for private, unlisted, members-only or
age-restricted content, export a `cookies.txt` with a browser extension and
select it in the **Cookie file** box, which overrides the browser setting.

**Update check fails with a certificate error** — something is inspecting HTTPS
traffic, which is common on managed work and school networks. The updater
trusts the OS certificate store first precisely so that corporate CAs installed
by policy work. If it still fails, point `SSL_CERT_FILE` at your organization's
root certificate.

## Troubleshooting a failed build

Check `build/ClipStash/warn-ClipStash.txt` for missing modules, and re-run with
`--debug` so the console window stays open and shows tracebacks.

If `build.py` reports tkinter missing:

- Debian/Ubuntu: `sudo apt install python3-tk`
- Fedora: `sudo dnf install python3-tkinter`
- macOS: use the python.org installer, or `brew install python-tk`
- Windows: re-run the Python installer and tick "tcl/tk and IDLE"

#!/usr/bin/env python3
"""
ClipStash Build Tool — a window instead of a command prompt.

Double-click this file. Windows runs .pyw files with pythonw.exe, which opens
no console, so you get a normal application window.

This doesn't reimplement anything: it assembles the options you tick into a
build.py command line, runs it, and streams the output into the log panel.
Anything build.py can do, this can do, and both stay in sync automatically.

If double-clicking opens a text editor instead of running it, right-click the
file, choose Open with, and pick Python. Or fall back to build.bat.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

try:
    import theme
except Exception:  # theming is cosmetic
    theme = None

PROJECT = Path(__file__).resolve().parent
APP_NAME = "ClipStash Build Tool"


def find_icon() -> Path | None:
    for name in ("icon.ico" if os.name == "nt" else "icon.png", "icon.png"):
        candidate = PROJECT / "assets" / name
        if candidate.is_file():
            return candidate
    return None


class BuildTool(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_NAME)
        self.minsize(700, 560)
        self._icon_image: tk.PhotoImage | None = None
        self._apply_icon()
        self.palette = theme.apply(self) if theme else {}

        self.queue: queue.Queue = queue.Queue()
        self.process: subprocess.Popen | None = None

        self.var_onedir = tk.BooleanVar(value=True)
        self.var_ffmpeg = tk.BooleanVar(value=True)
        self.var_extras = tk.BooleanVar(value=True)
        self.var_installer = tk.BooleanVar(value=True)
        self.var_clean = tk.BooleanVar(value=False)
        self.var_debug = tk.BooleanVar(value=False)
        self.var_status = tk.StringVar(value="Ready.")

        self._build_ui()
        self.after(100, self._pump)

    def _apply_icon(self) -> None:
        icon = find_icon()
        if not icon:
            return
        try:
            if icon.suffix == ".ico" and os.name == "nt":
                self.iconbitmap(default=str(icon))
            else:
                self._icon_image = tk.PhotoImage(file=str(icon))
                self.iconphoto(True, self._icon_image)
        except tk.TclError:
            pass

    # -- layout ------------------------------------------------------------- #

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=14)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(3, weight=1)

        ttk.Label(
            root,
            text="Build ClipStash",
            style="Heading.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            root,
            text="Tick what you want, then press Build. The defaults are the "
                 "recommended settings for producing an installer.",
            wraplength=650,
            justify="left",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(2, 12))

        options = ttk.LabelFrame(root, text="Options", padding=10)
        options.grid(row=2, column=0, sticky="ew", pady=(0, 10))

        rows = [
            (self.var_installer, "Build the installer",
             "Produces ClipStash-Setup.exe. Needs Inno Setup installed."),
            (self.var_ffmpeg, "Include ffmpeg",
             "Required for quality above 720p and MP3. Downloads ~170 MB if not already present."),
            (self.var_extras, "Install optional extras",
             "Adds metadata, encryption and compression support to yt-dlp."),
            (self.var_onedir, "Folder build",
             "Starts faster than a single file, and is what the installer expects."),
            (self.var_clean, "Clean first",
             "Deletes previous build output. Use if something seems stale."),
            (self.var_debug, "Debug console",
             "Keeps a console window attached to the built app to show errors."),
        ]
        for i, (var, label, hint) in enumerate(rows):
            ttk.Checkbutton(options, text=label, variable=var).grid(row=i, column=0, sticky="w", pady=2)
            ttk.Label(options, text=hint, style="Muted.TLabel").grid(row=i, column=1, sticky="w", padx=(14, 0))

        buttons = ttk.Frame(root)
        buttons.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        self.btn_build = ttk.Button(buttons, text="Build", command=self._start,
                                    style="Accent.TButton")
        self.btn_build.pack(side="left")
        self.btn_stop = ttk.Button(buttons, text="Stop", command=self._stop, state="disabled")
        self.btn_stop.pack(side="left", padx=8)
        ttk.Button(buttons, text="Open output folder", command=self._open_output).pack(side="left")
        ttk.Label(buttons, textvariable=self.var_status, style="Muted.TLabel").pack(side="right")

        logframe = ttk.LabelFrame(root, text="Output", padding=6)
        logframe.grid(row=3, column=0, sticky="nsew")
        logframe.columnconfigure(0, weight=1)
        logframe.rowconfigure(0, weight=1)

        self.log = tk.Text(logframe, height=16, wrap="word", state="disabled")
        self.log.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(logframe, orient="vertical", command=self.log.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scroll.set)

        if theme:
            theme.style_text(self.log)
        p = self.palette or {}
        self.log.tag_configure("error", foreground=p.get("error", "#B00020"))
        self.log.tag_configure("warn", foreground=p.get("warn", "#A66300"))
        self.log.tag_configure("good", foreground=p.get("ok", "#1B7F3B"))

    # -- running ------------------------------------------------------------ #

    def _arguments(self) -> list[str]:
        args = []
        if self.var_clean.get():
            args.append("--clean")
        if self.var_onedir.get():
            args.append("--onedir")
        if self.var_extras.get():
            args.append("--extras")
        if self.var_ffmpeg.get():
            args.append("--with-ffmpeg")
        if self.var_debug.get():
            args.append("--debug")
        if self.var_installer.get():
            args.append("--installer")
        return args

    def _start(self) -> None:
        script = PROJECT / "build.py"
        if not script.is_file():
            messagebox.showerror(APP_NAME, f"build.py wasn't found in:\n\n{PROJECT}")
            return

        # sys.executable is pythonw.exe here, which swallows output. Use the
        # console interpreter next to it so stdout actually reaches us.
        interpreter = sys.executable
        if os.name == "nt" and Path(interpreter).name.lower() == "pythonw.exe":
            console = Path(interpreter).with_name("python.exe")
            if console.is_file():
                interpreter = str(console)

        command = [interpreter, "-u", str(script), *self._arguments()]
        self._append(f"> {' '.join(command)}\n\n")

        creation = 0
        if os.name == "nt":
            creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        try:
            self.process = subprocess.Popen(
                command,
                cwd=PROJECT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                creationflags=creation,
            )
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Couldn't start the build:\n\n{exc}")
            return

        self.btn_build.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.var_status.set("Building…")
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self) -> None:
        assert self.process and self.process.stdout
        for line in self.process.stdout:
            self.queue.put(("line", line))
        code = self.process.wait()
        self.queue.put(("done", code))

    def _stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self.var_status.set("Stopping…")

    def _open_output(self) -> None:
        for folder in (PROJECT / "installer_output", PROJECT / "dist", PROJECT):
            if folder.is_dir():
                if os.name == "nt":
                    os.startfile(folder)  # type: ignore[attr-defined]
                elif sys.platform == "darwin":
                    subprocess.run(["open", str(folder)])
                else:
                    subprocess.run(["xdg-open", str(folder)])
                return

    # -- output ------------------------------------------------------------- #

    def _append(self, text: str, tag: str | None = None) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text, tag or ())
        self.log.see("end")
        self.log.configure(state="disabled")

    def _pump(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "line":
                    lowered = payload.lower()
                    tag = None
                    if "[error]" in lowered or "error:" in lowered:
                        tag = "error"
                    elif "[warn" in lowered or "warning" in lowered:
                        tag = "warn"
                    self._append(payload, tag)
                elif kind == "done":
                    self.process = None
                    self.btn_build.configure(state="normal")
                    self.btn_stop.configure(state="disabled")
                    if payload == 0:
                        self.var_status.set("Finished.")
                        self._append("\nBuild finished successfully.\n", "good")
                        messagebox.showinfo(
                            APP_NAME,
                            "Build finished.\n\nUse 'Open output folder' to find it.",
                        )
                    else:
                        self.var_status.set(f"Failed (exit {payload}).")
                        self._append(f"\nBuild failed with exit code {payload}.\n", "error")
        except queue.Empty:
            pass
        self.after(100, self._pump)


def main() -> None:
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ClipStash.BuildTool.1")
        except Exception:
            pass
    BuildTool().mainloop()


if __name__ == "__main__":
    main()

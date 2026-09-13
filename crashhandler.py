#!/usr/bin/env python3
"""
Catches unexpected errors and turns them into something a person can act on.

Without this, an unhandled exception in a frozen build produces a bare Python
traceback in a system dialog. That tells a developer plenty and a user nothing,
while looking like the program has broken beyond repair.

Three separate places can raise, and all three need covering. Missing any one
leaves a gap where the raw traceback still escapes:

  * the main thread, via sys.excepthook
  * background threads, via threading.excepthook
  * Tk callbacks, via Tk.report_callback_exception - button handlers and timers
    run inside Tk's event loop, which traps exceptions itself and never lets
    them reach sys.excepthook

Only the first crash raises a dialog. Faults tend to repeat once per event-loop
tick, and twenty stacked error boxes is worse than the crash.
"""

from __future__ import annotations

import sys
import threading
import traceback
from typing import Any, Callable

_installed = False
_dialog_shown = False
_lock = threading.Lock()

MESSAGE = (
    "Something went wrong inside ClipStash.\n\n"
    "Your downloads and settings are safe, and you can carry on using the app - "
    "though if it starts behaving oddly, closing and reopening it is worth a try.\n\n"
    "The technical details have been written to the log file. If you're reporting "
    "this, sending that file along is the single most useful thing you can do."
)


def _write_to_log(kind: str, text: str) -> None:
    try:
        import applog
        applog.write(f"UNHANDLED {kind}\n{text}", level="ERROR")
    except Exception:
        pass


def _fallback_print(kind: str, text: str) -> None:
    """Last resort if even the log is unavailable."""
    try:
        print(f"[{kind}] {text}", file=sys.stderr)
    except Exception:
        pass


def _show_dialog(summary: str, open_logs: Callable[[], Any] | None) -> None:
    global _dialog_shown
    with _lock:
        if _dialog_shown:
            return
        _dialog_shown = True

    try:
        from tkinter import messagebox
        detail = f"{MESSAGE}\n\nDetails: {summary}"
        if open_logs is not None:
            wants_logs = messagebox.askyesno(
                "ClipStash ran into a problem",
                f"{detail}\n\nOpen the log folder now?",
                icon="error",
            )
            if wants_logs:
                try:
                    open_logs()
                except Exception:
                    pass
        else:
            messagebox.showerror("ClipStash ran into a problem", detail)
    except Exception:
        # A GUI error box may itself be impossible if Tk is the thing that
        # failed. Having already logged, there is nothing further to do.
        pass


def _summarise(exc_type: type, exc_value: BaseException) -> str:
    """One short line naming what went wrong, for the dialog."""
    name = getattr(exc_type, "__name__", str(exc_type))
    text = str(exc_value).strip()
    if len(text) > 160:
        text = text[:157] + "..."
    return f"{name}: {text}" if text else name


def install(open_logs: Callable[[], Any] | None = None, root: Any = None) -> None:
    """
    Route every unhandled exception through the log and one friendly dialog.

    `root` should be the Tk root window; without it, exceptions raised inside
    button handlers and timers keep producing raw Tk error boxes.
    """
    global _installed
    if _installed:
        return
    _installed = True

    def handle(exc_type, exc_value, exc_tb, source: str = "exception") -> None:
        # Ctrl+C is a deliberate quit, not a fault.
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        _write_to_log(source, text)
        _fallback_print(source, text)
        _show_dialog(_summarise(exc_type, exc_value), open_logs)

    def main_hook(exc_type, exc_value, exc_tb):
        handle(exc_type, exc_value, exc_tb, "exception on the main thread")

    def thread_hook(args):
        # A thread dying is logged, but doesn't raise a dialog: background work
        # failing rarely means the app is unusable, and interrupting someone
        # mid-download over it would be worse than staying quiet.
        text = "".join(traceback.format_exception(
            args.exc_type, args.exc_value, args.exc_traceback))
        _write_to_log(f"exception in thread {getattr(args.thread, 'name', '?')}", text)
        _fallback_print("thread", text)

    sys.excepthook = main_hook
    try:
        threading.excepthook = thread_hook  # type: ignore[assignment]
    except Exception:
        pass

    if root is not None:
        def tk_hook(exc_type, exc_value, exc_tb):
            handle(exc_type, exc_value, exc_tb, "exception in a window callback")
        try:
            root.report_callback_exception = tk_hook
        except Exception:
            pass


def reset_dialog() -> None:
    """Allow one more dialog, e.g. after the user has acknowledged the last."""
    global _dialog_shown
    with _lock:
        _dialog_shown = False

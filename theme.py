#!/usr/bin/env python3
"""
ClipStash colour palette and Tkinter theme.

Every colour here is lifted from the logo artwork, so the app, the build tool
and the installer all read as the same product.

Two things make this work on Windows, and both are easy to miss:

1. The default ttk theme there ("vista") draws most widgets with native Win32
   calls and silently ignores background and fieldbackground settings. Styling
   has to start by switching to "clam", which is drawn by Tk itself and so
   honours what it's told.

2. A handful of widgets aren't ttk at all under the hood. The dropdown list of
   a Combobox is a classic Tk Listbox, reachable only through the option
   database, and tk.Text and tk.Toplevel need colouring directly.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

PALETTE = {
    # Surfaces, from the icon's background gradient.
    "bg":          "#1B2436",
    "panel":       "#222D42",
    "panel_hi":    "#2B3850",
    "field":       "#101A2C",
    "border":      "#3B4A63",
    "border_lit":  "#4C5F7E",

    # Text.
    "fg":          "#E8EEF6",
    "muted":       "#93A4BE",
    "dim":         "#6F819C",

    # The beanie.
    "accent":      "#D9453C",
    "accent_hi":   "#E85C53",
    "accent_lo":   "#B3322B",

    # The television screens.
    "info":        "#3E9FD6",
    "info_hi":     "#8FD4F5",

    # The sack.
    "sand":        "#E0B584",

    # Status.
    "ok":          "#4CAF7D",
    "warn":        "#E0A33E",
    "error":       "#FF6B6B",
}


def apply(root: tk.Misc) -> dict[str, str]:
    """Theme a Tk root or Toplevel. Returns the palette for direct use."""
    p = PALETTE
    style = ttk.Style(root)

    # "clam" is the prerequisite for everything below — see the module docstring.
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    try:
        root.configure(background=p["bg"])
    except tk.TclError:
        pass

    # --- containers and text ---------------------------------------------- #
    style.configure(".", background=p["bg"], foreground=p["fg"],
                    fieldbackground=p["field"], bordercolor=p["border"],
                    lightcolor=p["border"], darkcolor=p["bg"],
                    focuscolor=p["accent"])
    style.configure("TFrame", background=p["bg"])
    style.configure("TLabel", background=p["bg"], foreground=p["fg"])
    style.configure("Muted.TLabel", background=p["bg"], foreground=p["muted"])
    style.configure("Heading.TLabel", background=p["bg"], foreground=p["fg"],
                    font=("", 15, "bold"))

    style.configure("TLabelframe", background=p["bg"], bordercolor=p["border"],
                    lightcolor=p["border"], darkcolor=p["border"], relief="solid",
                    borderwidth=1)
    style.configure("TLabelframe.Label", background=p["bg"], foreground=p["sand"],
                    font=("", 9, "bold"))

    # --- buttons ----------------------------------------------------------- #
    style.configure("TButton", background=p["panel_hi"], foreground=p["fg"],
                    bordercolor=p["border"], lightcolor=p["panel_hi"],
                    darkcolor=p["panel_hi"], focusthickness=1,
                    focuscolor=p["accent"], padding=(12, 6), relief="flat")
    style.map("TButton",
              background=[("pressed", p["border"]), ("active", p["border_lit"]),
                          ("disabled", p["panel"])],
              foreground=[("disabled", p["dim"])],
              bordercolor=[("active", p["border_lit"])])

    # The primary action, in the beanie red.
    style.configure("Accent.TButton", background=p["accent"], foreground="#FFFFFF",
                    bordercolor=p["accent_lo"], lightcolor=p["accent"],
                    darkcolor=p["accent"], padding=(16, 6), relief="flat")
    style.map("Accent.TButton",
              background=[("pressed", p["accent_lo"]), ("active", p["accent_hi"]),
                          ("disabled", p["panel"])],
              foreground=[("disabled", p["dim"])],
              bordercolor=[("disabled", p["border"])])

    # --- inputs ------------------------------------------------------------ #
    for widget in ("TEntry", "TSpinbox"):
        style.configure(widget, fieldbackground=p["field"], background=p["field"],
                        foreground=p["fg"], bordercolor=p["border"],
                        lightcolor=p["border"], darkcolor=p["border"],
                        insertcolor=p["accent_hi"], padding=5, relief="flat")
        style.map(widget,
                  bordercolor=[("focus", p["accent"])],
                  lightcolor=[("focus", p["accent"])],
                  fieldbackground=[("disabled", p["panel"])],
                  foreground=[("disabled", p["dim"])])

    style.configure("TSpinbox", arrowcolor=p["muted"])
    style.map("TSpinbox", arrowcolor=[("active", p["accent_hi"])])

    style.configure("TCombobox", fieldbackground=p["field"], background=p["panel_hi"],
                    foreground=p["fg"], bordercolor=p["border"],
                    lightcolor=p["border"], darkcolor=p["border"],
                    arrowcolor=p["muted"], padding=5, relief="flat")
    style.map("TCombobox",
              fieldbackground=[("readonly", p["field"]), ("disabled", p["panel"])],
              foreground=[("disabled", p["dim"])],
              bordercolor=[("focus", p["accent"])],
              arrowcolor=[("active", p["accent_hi"])])

    # The dropdown list is a plain Tk Listbox — only the option database reaches it.
    root.option_add("*TCombobox*Listbox.background", p["field"])
    root.option_add("*TCombobox*Listbox.foreground", p["fg"])
    root.option_add("*TCombobox*Listbox.selectBackground", p["accent"])
    root.option_add("*TCombobox*Listbox.selectForeground", "#FFFFFF")
    root.option_add("*TCombobox*Listbox.borderWidth", 0)

    # --- checkbuttons ------------------------------------------------------ #
    style.configure("TCheckbutton", background=p["bg"], foreground=p["fg"],
                    indicatorbackground=p["field"], indicatorforeground=p["accent"],
                    focuscolor=p["accent"], padding=3)
    style.map("TCheckbutton",
              background=[("active", p["bg"])],
              foreground=[("disabled", p["dim"])],
              indicatorbackground=[("selected", p["accent"]),
                                   ("active", p["panel_hi"]),
                                   ("disabled", p["panel"])],
              indicatorforeground=[("selected", "#FFFFFF")])

    # --- progress and scrollbars ------------------------------------------- #
    style.configure("TProgressbar", background=p["info"], troughcolor=p["field"],
                    bordercolor=p["border"], lightcolor=p["info"],
                    darkcolor=p["info"], thickness=10)
    style.configure("Accent.Horizontal.TProgressbar", background=p["accent"],
                    troughcolor=p["field"], bordercolor=p["border"],
                    lightcolor=p["accent"], darkcolor=p["accent"], thickness=10)
    style.configure("Horizontal.TProgressbar", background=p["info"],
                    troughcolor=p["field"], bordercolor=p["border"],
                    lightcolor=p["info"], darkcolor=p["info"], thickness=10)

    style.configure("TScrollbar", background=p["panel_hi"], troughcolor=p["field"],
                    bordercolor=p["bg"], arrowcolor=p["muted"], relief="flat")
    style.map("TScrollbar",
              background=[("active", p["border_lit"]), ("pressed", p["accent"])],
              arrowcolor=[("active", p["fg"])])

    style.configure("TSeparator", background=p["border"])

    return p


class Tooltip:
    """
    A hover description for a widget.

    Deliberately not instant: a tooltip that appears the moment the pointer
    crosses a control flickers constantly as someone moves across a dense form.
    A short delay means it only appears when the pointer actually settles.

    The popup is clamped to the screen so controls near the bottom or right edge
    don't push their description off-screen where it can't be read.
    """

    _open: "Tooltip | None" = None   # only one visible at a time

    def __init__(self, widget: tk.Widget, text: str, delay: int = 450, wrap: int = 330):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.wrap = wrap
        self.window: tk.Toplevel | None = None
        self._after_id: str | None = None

        # add="+" so these don't replace bindings the widget already has.
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")
        widget.bind("<Destroy>", self._hide, add="+")

    def _schedule(self, _event=None) -> None:
        self._cancel()
        self._after_id = self.widget.after(self.delay, self._show)

    def _cancel(self) -> None:
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def _show(self) -> None:
        if self.window is not None:
            return
        if Tooltip._open is not None and Tooltip._open is not self:
            Tooltip._open._hide()

        try:
            if not self.widget.winfo_viewable():
                return
        except tk.TclError:
            return

        p = PALETTE
        win = tk.Toplevel(self.widget)
        win.wm_overrideredirect(True)
        try:
            win.attributes("-topmost", True)
        except tk.TclError:
            pass

        frame = tk.Frame(win, background=p["border_lit"], borderwidth=0)
        frame.pack()
        tk.Label(
            frame,
            text=self.text,
            justify="left",
            wraplength=self.wrap,
            background=p["panel_hi"],
            foreground=p["fg"],
            borderwidth=0,
            padx=10,
            pady=7,
        ).pack(padx=1, pady=1)

        win.update_idletasks()
        width, height = win.winfo_reqwidth(), win.winfo_reqheight()

        x = self.widget.winfo_rootx()
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6

        # Keep it on screen: flip above the widget if it would fall off the
        # bottom, and slide left if it would run past the right edge.
        screen_w = self.widget.winfo_screenwidth()
        screen_h = self.widget.winfo_screenheight()
        if x + width > screen_w - 8:
            x = max(8, screen_w - width - 8)
        if y + height > screen_h - 8:
            y = self.widget.winfo_rooty() - height - 6

        win.wm_geometry(f"+{int(x)}+{int(y)}")
        self.window = win
        Tooltip._open = self

    def _hide(self, _event=None) -> None:
        self._cancel()
        if self.window is not None:
            try:
                self.window.destroy()
            except Exception:
                pass
            self.window = None
        if Tooltip._open is self:
            Tooltip._open = None


def tip(text: str, *widgets: tk.Widget) -> None:
    """Attach the same description to several widgets, e.g. a label and its input."""
    for widget in widgets:
        if widget is not None:
            Tooltip(widget, text)


def style_text(widget: tk.Text) -> None:
    """Colour a tk.Text widget, which ttk styling doesn't reach."""
    p = PALETTE
    widget.configure(
        background=p["field"],
        foreground=p["fg"],
        insertbackground=p["accent_hi"],
        selectbackground=p["accent"],
        selectforeground="#FFFFFF",
        highlightthickness=1,
        highlightbackground=p["border"],
        highlightcolor=p["border"],
        borderwidth=0,
        padx=8,
        pady=6,
    )

from __future__ import annotations

from copy import deepcopy
from tkinter import ttk


BASE_THEME = {
    "name": "plain",
    "description": "Neutral utility styling.",
    "bg": "#f3f3f3",
    "panel": "#ffffff",
    "panel_alt": "#f7f7f7",
    "text": "#1f1f1f",
    "text_muted": "#5a5a5a",
    "accent": "#2f5f9f",
    "accent_alt": "#5c7b95",
    "canvas_bg": "#1f1f1f",
    "border": "#d0d0d0",
    "input_bg": "#ffffff",
    "input_fg": "#1f1f1f",
    "overlay_strip": "#ff4d4d",
    "overlay_strip_text": "#ff8c8c",
    "overlay_cut": "#4cff85",
    "overlay_box": "#ffb347",
    "overlay_handle": "#ffd480",
    "log_bg": "#ffffff",
    "log_fg": "#1f1f1f",
}


class ThemeManager:
    def __init__(self, root):
        self.root = root
        self.style = ttk.Style(root)
        if "clam" in self.style.theme_names():
            self.style.theme_use("clam")
        self.current_theme = deepcopy(BASE_THEME)

    def get_theme(self) -> dict:
        return deepcopy(BASE_THEME)

    def apply(self) -> dict:
        theme = self.get_theme()
        self.current_theme = theme

        self.style.configure(
            ".",
            background=theme["bg"],
            foreground=theme["text"],
            fieldbackground=theme["input_bg"],
        )
        self.style.configure("TFrame", background=theme["bg"])
        self.style.configure("Panel.TFrame", background=theme["panel"])
        self.style.configure("Topbar.TFrame", background=theme["panel_alt"])
        self.style.configure("PreviewTop.TFrame", background=theme["panel_alt"])
        self.style.configure("Nav.TFrame", background=theme["panel_alt"])

        self.style.configure("TLabel", background=theme["bg"], foreground=theme["text"])
        self.style.configure("Panel.TLabel", background=theme["panel"], foreground=theme["text"])
        self.style.configure("Body.TLabel", background=theme["panel"], foreground=theme["text_muted"])
        self.style.configure(
            "Section.TLabel",
            background=theme["panel"],
            foreground=theme["text"],
            font=("Segoe UI", 11, "bold"),
        )
        self.style.configure(
            "TopbarTitle.TLabel",
            background=theme["panel_alt"],
            foreground=theme["accent"],
            font=("Segoe UI", 13, "bold"),
        )

        self.style.configure(
            "TButton",
            background=theme["panel_alt"],
            foreground=theme["text"],
            bordercolor=theme["border"],
            focusthickness=1,
            focuscolor=theme["accent"],
            padding=(10, 6),
        )
        self.style.map(
            "TButton",
            background=[("active", theme["panel"]), ("pressed", theme["panel"])],
            foreground=[("disabled", theme["text_muted"])],
        )
        self.style.configure(
            "Accent.TButton",
            background=theme["accent"],
            foreground=theme["bg"],
            bordercolor=theme["accent"],
        )
        self.style.map(
            "Accent.TButton",
            background=[("active", theme["accent_alt"]), ("pressed", theme["accent_alt"])],
            foreground=[("disabled", theme["bg"])],
        )

        self.style.configure(
            "TCombobox",
            fieldbackground=theme["input_bg"],
            foreground=theme["input_fg"],
            bordercolor=theme["border"],
            arrowsize=14,
        )
        self.style.configure(
            "TEntry",
            fieldbackground=theme["input_bg"],
            foreground=theme["input_fg"],
            bordercolor=theme["border"],
        )
        self.style.configure(
            "TCheckbutton",
            background=theme["panel"],
            foreground=theme["text"],
        )
        self.style.map(
            "TCheckbutton",
            background=[("active", theme["panel"])],
            foreground=[("disabled", theme["text_muted"])],
        )
        self.style.configure(
            "Horizontal.TScale",
            background=theme["panel"],
            troughcolor=theme["panel_alt"],
            bordercolor=theme["border"],
        )
        self.style.configure(
            "TScrollbar",
            background=theme["panel_alt"],
            troughcolor=theme["bg"],
            bordercolor=theme["border"],
        )
        self.style.configure("TSeparator", background=theme["border"])

        self.root.configure(background=theme["bg"])
        return theme

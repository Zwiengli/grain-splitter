from __future__ import annotations

import queue
import threading
import traceback
from collections import OrderedDict
from pathlib import Path

import numpy as np
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from app.preview_canvas import PreviewCanvas
from app.settings_manager import SettingsManager
from app.theme_manager import ThemeManager
from core.constants import (
    ASYNC_PREVIEW_MAX_DIM,
    DEFAULT_BG_THRESH,
    DEFAULT_CROP_PAD,
    DEFAULT_JPEG_QUALITY,
    DEFAULT_PNG_COMPRESS_LEVEL,
    DEFAULT_TIFF_COMPRESSION,
    FORMAT_IDS,
    LANGUAGE_IDS,
    MAX_DETECTION_CACHE_ITEMS,
    MAX_DERIVED_CACHE_BYTES,
    MAX_DERIVED_CACHE_ITEMS,
    MAX_ANALYSIS_DIM,
    MAX_IMAGE_CACHE_BYTES,
    MAX_IMAGE_CACHE_ITEMS,
    MAX_PREVIEW_BASE_DIM,
    MAX_UNDO_STEPS,
    OPEN_FILE_PATTERN,
    ORIENTATION_IDS,
    PRESET_FRAME_COUNTS,
    PRESET_IDS,
    SUPPORTED_EXTS,
    TIFF_COMPRESSION_IDS,
)
from core.image_loader import downscale_image, load_image, load_preview_image, rotate_image, to_gray8
from core.splitter_engine import (
    build_box_only_layout,
    build_layout_from_snapshot,
    clone_guides_snapshot,
    detect_layout,
    rebuild_boxes_from_guides,
    rotate_box,
    save_crops,
    snapshot_guides,
)
from core.utils import clamp, coerce_int
from i18n.loader import I18N


class SplitterApp:
    def __init__(self, root):
        self.root = root
        self.root.geometry("1450x920")

        config_dir = Path(__file__).resolve().parent.parent / "config"
        self.settings_manager = SettingsManager(
            config_dir / "default_settings.json",
            config_dir / "user_settings.json",
        )
        self.theme_manager = ThemeManager(self.root)

        self.current_lang = str(self.settings_manager.get("language", "zh"))
        if self.current_lang not in LANGUAGE_IDS:
            self.current_lang = "zh"
        self.status_state = ("status_ready", {})
        self.preset_id = "120_6x6"
        self.orientation_id = "auto"
        self.format_id = "original"
        self.tiff_compression_id = str(self.settings_manager.get("tiff_compression", DEFAULT_TIFF_COMPRESSION))
        if self.tiff_compression_id not in TIFF_COMPRESSION_IDS:
            self.tiff_compression_id = DEFAULT_TIFF_COMPRESSION
        self.language_var = tk.StringVar()
        initial_jpeg_quality = clamp(
            coerce_int(self.settings_manager.get("jpeg_quality", DEFAULT_JPEG_QUALITY), DEFAULT_JPEG_QUALITY),
            50,
            100,
        )
        initial_png_compress = clamp(
            coerce_int(
                self.settings_manager.get("png_compress_level", DEFAULT_PNG_COMPRESS_LEVEL),
                DEFAULT_PNG_COMPRESS_LEVEL,
            ),
            0,
            9,
        )
        self.jpeg_quality_var = tk.DoubleVar(value=initial_jpeg_quality)
        self.jpeg_quality_value_var = tk.StringVar(value=str(initial_jpeg_quality))
        self.png_compress_var = tk.DoubleVar(value=initial_png_compress)
        self.png_compress_value_var = tk.StringVar(value=str(initial_png_compress))
        self.tiff_compression_var = tk.StringVar()

        self.current_path = None
        self.file_paths = []
        self.file_states = {}
        self.current_index = -1
        self.load_info = None
        self.loading = False
        self.load_request_token = 0
        self.async_ui_queue = queue.Queue()
        self.async_ui_job = None

        self.original_bgr = None
        self.display_bgr = None
        self.layout = None
        self.auto_guides = None
        self.rotation = 0

        self.image_cache = OrderedDict()
        self.image_cache_bytes = 0
        self.derived_cache = OrderedDict()
        self.derived_cache_bytes = 0
        self.cache_lock = threading.Lock()
        self.prefetching_paths = set()

        self.last_bg_thresh = DEFAULT_BG_THRESH
        self.last_crop_pad = DEFAULT_CROP_PAD
        self.settings_window = None
        self.settings_widgets_ready = False
        self.settings_title_label = None
        self.settings_close_btn = None
        self.settings_frame = None
        self.label_language = None
        self.language_combo = None
        self.label_jpeg_quality = None
        self.label_png_compress = None
        self.label_tiff_compression = None
        self.tiff_compression_combo = None
        self.undo_btn = None
        self.theme_palette = self.theme_manager.get_theme()
        self.progress_mode = "idle"

        self._build_ui()
        self.schedule_async_ui_pump()
        self.root.bind_all("<Control-z>", self.on_undo_shortcut)
        self.root.bind_all("<Control-Z>", self.on_undo_shortcut)
        self.root.bind("<Destroy>", self.on_root_destroy, add="+")
        self.apply_theme()
        self.apply_language()
        self.set_status("status_ready")

    def tr(self, key: str, **kwargs):
        text = I18N.get(self.current_lang, {}).get(key)
        if text is None:
            text = I18N["zh"].get(key, key)
        return text.format(**kwargs) if kwargs else text

    def rotation_text(self, deg: int) -> str:
        mapping = {
            0: "rotation_original",
            90: "rotation_cw90",
            180: "rotation_180",
            270: "rotation_ccw90",
        }
        return self.tr(mapping.get(deg % 360, "rotation_original"))

    def set_status(self, key: str, **kwargs):
        self.status_state = (key, kwargs)
        self.status_var.set(self.tr(key, **kwargs))

    def refresh_status_text(self):
        key, kwargs = self.status_state
        self.status_var.set(self.tr(key, **kwargs))

    def refresh_choice_maps(self):
        self.preset_id_to_label = {item: self.tr(f"preset_{item}") for item in PRESET_IDS}
        self.preset_label_to_id = {label: item for item, label in self.preset_id_to_label.items()}
        self.preset_combo.configure(values=[self.preset_id_to_label[item] for item in PRESET_IDS])
        self.preset_var.set(self.preset_id_to_label[self.preset_id])

        self.orientation_id_to_label = {item: self.tr(f"orientation_{item}") for item in ORIENTATION_IDS}
        self.orientation_label_to_id = {label: item for item, label in self.orientation_id_to_label.items()}
        self.orientation_combo.configure(values=[self.orientation_id_to_label[item] for item in ORIENTATION_IDS])
        self.orientation_var.set(self.orientation_id_to_label[self.orientation_id])

        self.format_id_to_label = {item: self.tr(f"format_{item}") for item in FORMAT_IDS}
        self.format_label_to_id = {label: item for item, label in self.format_id_to_label.items()}
        self.format_combo.configure(values=[self.format_id_to_label[item] for item in FORMAT_IDS])
        self.format_var.set(self.format_id_to_label[self.format_id])

        self.language_id_to_label = {item: self.tr(f"language_{item}") for item in LANGUAGE_IDS}
        self.language_label_to_id = {label: item for item, label in self.language_id_to_label.items()}
        self.language_var.set(self.language_id_to_label[self.current_lang])
        if self.settings_widgets_ready and self.language_combo is not None:
            self.language_combo.configure(values=[self.language_id_to_label[item] for item in LANGUAGE_IDS])

        self.tiff_comp_id_to_label = {item: self.tr(f"tiff_compression_{item}") for item in TIFF_COMPRESSION_IDS}
        self.tiff_comp_label_to_id = {label: item for item, label in self.tiff_comp_id_to_label.items()}
        self.tiff_compression_var.set(self.tiff_comp_id_to_label[self.tiff_compression_id])
        if self.settings_widgets_ready and self.tiff_compression_combo is not None:
            self.tiff_compression_combo.configure(values=[self.tiff_comp_id_to_label[item] for item in TIFF_COMPRESSION_IDS])

    def apply_language(self):
        self.root.title(self.tr("app_title"))
        self.topbar_title_label.configure(text=self.tr("app_title"))
        self.settings_btn.configure(text=self.tr("btn_settings"))
        self.file_section_label.configure(text=self.tr("section_file"))
        self.detect_section_label.configure(text=self.tr("section_detect"))
        self.help_section_label.configure(text=self.tr("section_help"))
        self.log_section_label.configure(text=self.tr("section_log"))

        self.open_btn.configure(text=self.tr("btn_open"))
        self.batch_btn.configure(text=self.tr("btn_batch"))
        self.rotate_left_btn.configure(text=self.tr("btn_rotate_left"))
        self.rotate_right_btn.configure(text=self.tr("btn_rotate_right"))
        self.reset_rotation_btn.configure(text=self.tr("btn_reset_rotation"))
        self.detect_btn.configure(text=self.tr("btn_detect"))
        self.export_current_btn.configure(text=self.tr("btn_export_current"))
        self.export_all_btn.configure(text=self.tr("btn_export_all"))
        self.fit_btn.configure(text=self.tr("btn_fit"))
        self.preview_1x_btn.configure(text=self.tr("btn_preview_1x"))
        self.undo_btn.configure(text=self.tr("btn_undo"))
        self.reset_guides_btn.configure(text=self.tr("btn_reset_guides"))
        self.prev_btn.configure(text=self.tr("btn_prev"))
        self.next_btn.configure(text=self.tr("btn_next"))
        self.refresh_progress_text()

        self.label_preset.configure(text=self.tr("label_preset"))
        self.label_total_frames.configure(text=self.tr("label_total_frames"))
        self.label_strip_count.configure(text=self.tr("label_strip_count"))
        self.label_orientation.configure(text=self.tr("label_orientation"))
        self.label_bg_thresh.configure(text=self.tr("label_bg_thresh"))
        self.label_crop_pad.configure(text=self.tr("label_crop_pad"))
        self.label_output_format.configure(text=self.tr("label_output_format"))
        if self.settings_widgets_ready and self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.title(self.tr("dialog_settings"))
            self.settings_title_label.configure(text=self.tr("section_settings"))
            self.label_language.configure(text=self.tr("label_language"))
            self.label_jpeg_quality.configure(text=self.tr("label_jpeg_quality"))
            self.label_png_compress.configure(text=self.tr("label_png_compress"))
            self.label_tiff_compression.configure(text=self.tr("label_tiff_compression"))
            self.settings_close_btn.configure(text=self.tr("btn_close"))

        self.help_var.set(self.tr("help_text"))
        self.refresh_choice_maps()
        self.update_setting_value_labels()
        self.refresh_status_text()
        self.update_zoom_label()
        self.update_navigation_ui()
        self.update_undo_ui()

    def persist_settings(self):
        self.settings_manager.remove("beautify_enabled", "theme_style", save=False)
        self.settings_manager.update(
            {
                "language": self.current_lang,
                "jpeg_quality": self.get_jpeg_quality(),
                "png_compress_level": self.get_png_compress_level(),
                "tiff_compression": self.tiff_compression_id,
            }
        )

    def apply_theme(self):
        self.theme_palette = self.theme_manager.apply()

        self.top_bar.configure(style="Topbar.TFrame")
        self.left_panel.configure(style="Panel.TFrame")
        self.preview_top.configure(style="PreviewTop.TFrame")
        self.tool_row.configure(style="PreviewTop.TFrame")
        self.nav_row.configure(style="Nav.TFrame")
        for panel_frame in (self.file_row, self.rot_row, self.detect_grid, self.detect_row, self.export_row):
            panel_frame.configure(style="Panel.TFrame")

        self.topbar_title_label.configure(style="TopbarTitle.TLabel")
        self.file_section_label.configure(style="Section.TLabel")
        self.detect_section_label.configure(style="Section.TLabel")
        self.help_section_label.configure(style="Section.TLabel")
        self.log_section_label.configure(style="Section.TLabel")
        self.help_body.configure(style="Body.TLabel")
        self.label_preset.configure(style="Panel.TLabel")
        self.label_total_frames.configure(style="Panel.TLabel")
        self.label_strip_count.configure(style="Panel.TLabel")
        self.label_orientation.configure(style="Panel.TLabel")
        self.label_bg_thresh.configure(style="Panel.TLabel")
        self.label_crop_pad.configure(style="Panel.TLabel")
        self.label_output_format.configure(style="Panel.TLabel")
        self.status_label.configure(style="Panel.TLabel")
        self.zoom_label.configure(style="Panel.TLabel")
        self.nav_label.configure(style="Panel.TLabel")
        self.progress_text_label.configure(style="Panel.TLabel")
        self.progress_detail_label.configure(style="Panel.TLabel")
        self.progress_frame.configure(style="PreviewTop.TFrame")

        self.detect_btn.configure(style="Accent.TButton")
        self.export_current_btn.configure(style="Accent.TButton")
        self.export_all_btn.configure(style="Accent.TButton")

        self.preview.set_theme(self.theme_palette)
        self.log_text.configure(
            bg=self.theme_palette["log_bg"],
            fg=self.theme_palette["log_fg"],
            insertbackground=self.theme_palette["accent"],
            relief="flat",
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=self.theme_palette["border"],
            highlightcolor=self.theme_palette["accent"],
        )

        if self.settings_widgets_ready and self.settings_frame is not None:
            self.settings_frame.configure(style="Panel.TFrame")
            self.settings_title_label.configure(style="Section.TLabel")
            self.label_language.configure(style="Panel.TLabel")
            self.label_jpeg_quality.configure(style="Panel.TLabel")
            self.label_png_compress.configure(style="Panel.TLabel")
            self.label_tiff_compression.configure(style="Panel.TLabel")

        self.schedule_preview_redraw()

    def _build_ui(self):
        self.top_bar = ttk.Frame(self.root, padding=(10, 10, 10, 0))
        self.top_bar.pack(fill="x")
        self.topbar_title_label = ttk.Label(self.top_bar)
        self.topbar_title_label.pack(side="left")
        self.settings_btn = ttk.Button(self.top_bar, command=self.open_settings_window)
        self.settings_btn.pack(side="right")

        self.container = ttk.Frame(self.root, padding=10)
        self.container.pack(fill="both", expand=True)

        self.left_panel = ttk.Frame(self.container, width=360)
        self.left_panel.pack(side="left", fill="y")
        self.right_panel = ttk.Frame(self.container)
        self.right_panel.pack(side="right", fill="both", expand=True)

        self.file_section_label = ttk.Label(self.left_panel)
        self.file_section_label.pack(anchor="w", pady=(0, 6))
        self.file_row = ttk.Frame(self.left_panel)
        self.file_row.pack(fill="x", pady=(0, 10))
        self.open_btn = ttk.Button(self.file_row, command=self.open_image)
        self.open_btn.pack(side="left", fill="x", expand=True)
        self.batch_btn = ttk.Button(self.file_row, command=self.batch_process_folder)
        self.batch_btn.pack(side="left", fill="x", expand=True, padx=(6, 0))

        self.rot_row = ttk.Frame(self.left_panel)
        self.rot_row.pack(fill="x", pady=(0, 10))
        self.rotate_left_btn = ttk.Button(self.rot_row, command=lambda: self.rotate_current(-90))
        self.rotate_left_btn.pack(side="left", fill="x", expand=True)
        self.rotate_right_btn = ttk.Button(self.rot_row, command=lambda: self.rotate_current(90))
        self.rotate_right_btn.pack(side="left", fill="x", expand=True, padx=6)
        self.reset_rotation_btn = ttk.Button(self.rot_row, command=self.reset_rotation)
        self.reset_rotation_btn.pack(side="left", fill="x", expand=True)

        ttk.Separator(self.left_panel).pack(fill="x", pady=8)
        self.detect_section_label = ttk.Label(self.left_panel)
        self.detect_section_label.pack(anchor="w", pady=(0, 6))

        self.detect_grid = ttk.Frame(self.left_panel)
        self.detect_grid.pack(fill="x")

        self.label_preset = ttk.Label(self.detect_grid)
        self.label_preset.grid(row=0, column=0, sticky="w", pady=4)
        self.preset_var = tk.StringVar()
        self.preset_combo = ttk.Combobox(self.detect_grid, textvariable=self.preset_var, state="readonly")
        self.preset_combo.grid(row=0, column=1, sticky="ew", pady=4)
        self.preset_combo.bind("<<ComboboxSelected>>", self.on_preset_selected)

        self.label_total_frames = ttk.Label(self.detect_grid)
        self.label_total_frames.grid(row=1, column=0, sticky="w", pady=4)
        self.total_frames_var = tk.StringVar(value="12")
        ttk.Entry(self.detect_grid, textvariable=self.total_frames_var).grid(row=1, column=1, sticky="ew", pady=4)

        self.label_strip_count = ttk.Label(self.detect_grid)
        self.label_strip_count.grid(row=2, column=0, sticky="w", pady=4)
        self.strip_count_var = tk.StringVar(value="0")
        ttk.Entry(self.detect_grid, textvariable=self.strip_count_var).grid(row=2, column=1, sticky="ew", pady=4)

        self.label_orientation = ttk.Label(self.detect_grid)
        self.label_orientation.grid(row=3, column=0, sticky="w", pady=4)
        self.orientation_var = tk.StringVar()
        self.orientation_combo = ttk.Combobox(
            self.detect_grid,
            textvariable=self.orientation_var,
            state="readonly",
        )
        self.orientation_combo.grid(row=3, column=1, sticky="ew", pady=4)
        self.orientation_combo.bind("<<ComboboxSelected>>", self.on_orientation_selected)

        self.label_bg_thresh = ttk.Label(self.detect_grid)
        self.label_bg_thresh.grid(row=4, column=0, sticky="w", pady=4)
        self.bg_thresh_var = tk.IntVar(value=DEFAULT_BG_THRESH)
        ttk.Scale(self.detect_grid, from_=0, to=80, variable=self.bg_thresh_var, orient="horizontal").grid(
            row=4, column=1, sticky="ew", pady=4
        )

        self.label_crop_pad = ttk.Label(self.detect_grid)
        self.label_crop_pad.grid(row=5, column=0, sticky="w", pady=4)
        self.pad_var = tk.IntVar(value=DEFAULT_CROP_PAD)
        ttk.Scale(self.detect_grid, from_=0, to=30, variable=self.pad_var, orient="horizontal").grid(
            row=5, column=1, sticky="ew", pady=4
        )

        self.label_output_format = ttk.Label(self.detect_grid)
        self.label_output_format.grid(row=6, column=0, sticky="w", pady=4)
        self.format_var = tk.StringVar()
        self.format_combo = ttk.Combobox(self.detect_grid, textvariable=self.format_var, state="readonly")
        self.format_combo.grid(row=6, column=1, sticky="ew", pady=4)
        self.format_combo.bind("<<ComboboxSelected>>", self.on_format_selected)

        self.detect_grid.columnconfigure(1, weight=1)

        self.detect_row = ttk.Frame(self.left_panel)
        self.detect_row.pack(fill="x", pady=(10, 6))
        self.detect_btn = ttk.Button(self.detect_row, command=self.run_detection)
        self.detect_btn.pack(fill="x")

        self.export_row = ttk.Frame(self.left_panel)
        self.export_row.pack(fill="x", pady=(0, 10))
        self.export_current_btn = ttk.Button(self.export_row, command=self.export_current)
        self.export_current_btn.pack(side="left", fill="x", expand=True)
        self.export_all_btn = ttk.Button(self.export_row, command=self.export_all)
        self.export_all_btn.pack(side="left", fill="x", expand=True, padx=(6, 0))

        self.help_section_label = ttk.Label(self.left_panel)
        self.help_section_label.pack(anchor="w", pady=(6, 4))
        self.help_var = tk.StringVar()
        self.help_body = ttk.Label(self.left_panel, textvariable=self.help_var, justify="left", wraplength=332)
        self.help_body.pack(anchor="w", pady=(0, 8))

        self.log_section_label = ttk.Label(self.left_panel)
        self.log_section_label.pack(anchor="w", pady=(6, 4))
        self.log_text = tk.Text(self.left_panel, height=16, wrap="word")
        self.log_text.pack(fill="both", expand=True)

        self.preview_top = ttk.Frame(self.right_panel)
        self.preview_top.pack(fill="x", pady=(0, 6))

        self.status_var = tk.StringVar()
        self.status_label = ttk.Label(self.preview_top, textvariable=self.status_var)
        self.status_label.pack(side="left")

        self.tool_row = ttk.Frame(self.preview_top)
        self.tool_row.pack(side="right")
        self.preview = PreviewCanvas(
            self.root,
            self.right_panel,
            tr=self.tr,
            on_manual_adjust_done=self.on_preview_manual_adjust_done,
            on_edit_started=self.on_preview_edit_started,
        )
        self.zoom_var = self.preview.zoom_var
        self.zoom_label = ttk.Label(self.tool_row, textvariable=self.zoom_var)
        self.zoom_label.pack(side="left", padx=(0, 8))
        self.fit_btn = ttk.Button(self.tool_row, command=self.fit_preview)
        self.fit_btn.pack(side="left")
        self.preview_1x_btn = ttk.Button(self.tool_row, command=self.reset_preview_zoom)
        self.preview_1x_btn.pack(side="left", padx=(6, 0))
        self.undo_btn = ttk.Button(self.tool_row, command=self.undo_last_action)
        self.undo_btn.pack(side="left", padx=(6, 0))
        self.reset_guides_btn = ttk.Button(self.tool_row, command=self.reset_manual_guides)
        self.reset_guides_btn.pack(side="left", padx=(6, 0))

        self.progress_frame = ttk.Frame(self.right_panel)
        self.progress_text_var = tk.StringVar(value="")
        self.progress_text_label = ttk.Label(self.progress_frame, textvariable=self.progress_text_var)
        self.progress_text_label.pack(side="left")
        self.progress_detail_var = tk.StringVar(value="")
        self.progress_detail_label = ttk.Label(self.progress_frame, textvariable=self.progress_detail_var)
        self.progress_detail_label.pack(side="right")
        self.progress_bar = ttk.Progressbar(self.progress_frame, orient="horizontal", mode="determinate")
        self.progress_bar.pack(fill="x", expand=True, padx=8, side="left")

        self.preview_frame = self.preview.container
        self.canvas = self.preview.canvas

        self.nav_row = ttk.Frame(self.right_panel)
        self.nav_row.pack(fill="x", pady=(6, 0))
        self.prev_btn = ttk.Button(self.nav_row, command=self.show_prev_image)
        self.prev_btn.pack(side="left")
        self.nav_var = tk.StringVar()
        self.nav_label = ttk.Label(self.nav_row, textvariable=self.nav_var, anchor="center")
        self.nav_label.pack(side="left", fill="x", expand=True, padx=8)
        self.next_btn = ttk.Button(self.nav_row, command=self.show_next_image)
        self.next_btn.pack(side="right")

    def log(self, message: str):
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")

    def get_jpeg_quality(self) -> int:
        return clamp(int(round(float(self.jpeg_quality_var.get()))), 50, 100)

    def get_png_compress_level(self) -> int:
        return clamp(int(round(float(self.png_compress_var.get()))), 0, 9)

    def update_setting_value_labels(self):
        self.jpeg_quality_value_var.set(str(self.get_jpeg_quality()))
        self.png_compress_value_var.set(str(self.get_png_compress_level()))

    def refresh_progress_text(self):
        if self.progress_mode == "loading" and self.current_path:
            self.progress_text_var.set(self.tr("progress_loading", name=Path(self.current_path).name))

    def show_progress(self, text: str, *, mode: str = "indeterminate", maximum: float = 1.0, value: float = 0.0):
        self.progress_mode = mode
        self.progress_text_var.set(text)
        if self.progress_frame.winfo_manager() != "pack":
            self.progress_frame.pack(fill="x", pady=(0, 6), before=self.preview_frame)
        self.progress_bar.stop()
        self.progress_bar.configure(mode=mode)
        if mode == "determinate":
            maximum = max(1.0, float(maximum))
            value = clamp(float(value), 0.0, maximum)
            self.progress_bar.configure(maximum=maximum, value=value)
            self.progress_detail_var.set(f"{int(round(value))} / {int(round(maximum))}")
        else:
            self.progress_bar.configure(maximum=100.0, value=0.0)
            self.progress_detail_var.set("")
            self.progress_bar.start(10)
        self.root.update_idletasks()

    def update_progress(self, *, text: str | None = None, value: float | None = None, maximum: float | None = None):
        if text is not None:
            self.progress_text_var.set(text)
        if str(self.progress_bar.cget("mode")) != "determinate":
            self.root.update_idletasks()
            return
        current_max = float(self.progress_bar.cget("maximum") or 1.0)
        if maximum is not None:
            current_max = max(1.0, float(maximum))
            self.progress_bar.configure(maximum=current_max)
        current_value = float(self.progress_bar.cget("value") or 0.0)
        if value is not None:
            current_value = clamp(float(value), 0.0, current_max)
            self.progress_bar.configure(value=current_value)
        self.progress_detail_var.set(f"{int(round(current_value))} / {int(round(current_max))}")
        self.root.update_idletasks()

    def hide_progress(self):
        self.progress_mode = "idle"
        self.progress_bar.stop()
        self.progress_bar.configure(value=0.0, maximum=1.0, mode="determinate")
        self.progress_text_var.set("")
        self.progress_detail_var.set("")
        if self.progress_frame.winfo_manager() == "pack":
            self.progress_frame.pack_forget()
        self.root.update_idletasks()

    def on_jpeg_quality_change(self, _value=None):
        self.update_setting_value_labels()

    def on_png_compress_change(self, _value=None):
        self.update_setting_value_labels()

    def open_settings_window(self):
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.deiconify()
            self.settings_window.lift()
            self.settings_window.focus_force()
            return

        self.settings_window = tk.Toplevel(self.root)
        self.settings_window.resizable(False, False)
        self.settings_window.transient(self.root)
        self.settings_window.protocol("WM_DELETE_WINDOW", self.close_settings_window)

        self.settings_frame = ttk.Frame(self.settings_window, padding=12)
        self.settings_frame.pack(fill="both", expand=True)
        self.settings_frame.columnconfigure(1, weight=1)

        self.settings_title_label = ttk.Label(self.settings_frame)
        self.settings_title_label.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))

        self.label_language = ttk.Label(self.settings_frame)
        self.label_language.grid(row=1, column=0, sticky="w", pady=4)
        self.language_combo = ttk.Combobox(self.settings_frame, textvariable=self.language_var, state="readonly")
        self.language_combo.grid(row=1, column=1, columnspan=2, sticky="ew", pady=4)
        self.language_combo.bind("<<ComboboxSelected>>", self.on_language_selected)

        self.label_jpeg_quality = ttk.Label(self.settings_frame)
        self.label_jpeg_quality.grid(row=2, column=0, sticky="w", pady=4)
        ttk.Scale(
            self.settings_frame,
            from_=50,
            to=100,
            variable=self.jpeg_quality_var,
            orient="horizontal",
            command=self.on_jpeg_quality_change,
        ).grid(row=2, column=1, sticky="ew", pady=4)
        ttk.Label(self.settings_frame, textvariable=self.jpeg_quality_value_var, width=4).grid(
            row=2,
            column=2,
            sticky="e",
            padx=(6, 0),
        )

        self.label_png_compress = ttk.Label(self.settings_frame)
        self.label_png_compress.grid(row=3, column=0, sticky="w", pady=4)
        ttk.Scale(
            self.settings_frame,
            from_=0,
            to=9,
            variable=self.png_compress_var,
            orient="horizontal",
            command=self.on_png_compress_change,
        ).grid(row=3, column=1, sticky="ew", pady=4)
        ttk.Label(self.settings_frame, textvariable=self.png_compress_value_var, width=4).grid(
            row=3,
            column=2,
            sticky="e",
            padx=(6, 0),
        )

        self.label_tiff_compression = ttk.Label(self.settings_frame)
        self.label_tiff_compression.grid(row=4, column=0, sticky="w", pady=4)
        self.tiff_compression_combo = ttk.Combobox(self.settings_frame, textvariable=self.tiff_compression_var, state="readonly")
        self.tiff_compression_combo.grid(row=4, column=1, columnspan=2, sticky="ew", pady=4)
        self.tiff_compression_combo.bind("<<ComboboxSelected>>", self.on_tiff_compression_selected)

        self.settings_close_btn = ttk.Button(self.settings_frame, command=self.close_settings_window)
        self.settings_close_btn.grid(row=5, column=0, columnspan=3, sticky="e", pady=(10, 0))

        self.settings_widgets_ready = True
        self.apply_theme()
        self.apply_language()
        self.settings_window.lift()
        self.settings_window.focus_force()

    def close_settings_window(self):
        self.persist_settings()
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.destroy()
        self.settings_window = None
        self.settings_widgets_ready = False
        self.settings_title_label = None
        self.settings_close_btn = None
        self.settings_frame = None
        self.label_language = None
        self.language_combo = None
        self.label_jpeg_quality = None
        self.label_png_compress = None
        self.label_tiff_compression = None
        self.tiff_compression_combo = None

    def on_language_selected(self, _event=None):
        new_lang = self.language_label_to_id.get(self.language_var.get(), self.current_lang)
        if new_lang != self.current_lang:
            self.current_lang = new_lang
            self.apply_language()
            self.persist_settings()

    def on_preset_selected(self, _event=None):
        self.preset_id = self.preset_label_to_id.get(self.preset_var.get(), self.preset_id)
        total = PRESET_FRAME_COUNTS.get(self.preset_id, 0)
        if total > 0:
            self.total_frames_var.set(str(total))
        elif self.preset_id == "auto":
            self.total_frames_var.set("0")

    def on_orientation_selected(self, _event=None):
        self.orientation_id = self.orientation_label_to_id.get(self.orientation_var.get(), self.orientation_id)

    def on_format_selected(self, _event=None):
        self.format_id = self.format_label_to_id.get(self.format_var.get(), self.format_id)

    def on_tiff_compression_selected(self, _event=None):
        self.tiff_compression_id = self.tiff_comp_label_to_id.get(self.tiff_compression_var.get(), self.tiff_compression_id)
        self.persist_settings()

    def parse_params(self):
        try:
            total_frames = int(self.total_frames_var.get().strip() or "0")
            strip_count = int(self.strip_count_var.get().strip() or "0")
        except ValueError as exc:
            raise RuntimeError(f"{self.tr('label_total_frames')} / {self.tr('label_strip_count')}") from exc

        bg_thresh = int(self.bg_thresh_var.get())
        crop_pad = int(self.pad_var.get())
        return total_frames, strip_count, bg_thresh, crop_pad, self.orientation_id

    def default_file_state(self):
        return {
            "rotation": 0,
            "detected": False,
            "used_rotation": 0,
            "guides": None,
            "auto_guides": None,
            "boxes": None,
            "box_mode": False,
            "last_bg_thresh": DEFAULT_BG_THRESH,
            "last_crop_pad": DEFAULT_CROP_PAD,
            "diagnostics": {},
            "undo_stack": [],
            "detection_cache": OrderedDict(),
        }

    def get_file_state(self, path: str):
        state = self.file_states.setdefault(path, self.default_file_state())
        state.setdefault("diagnostics", {})
        state.setdefault("undo_stack", [])
        state.setdefault("detection_cache", OrderedDict())
        return state

    def build_layout_state_snapshot(
        self,
        layout,
        *,
        rotation: int,
        auto_guides=None,
        bg_thresh: int,
        crop_pad: int,
    ):
        snapshot = {
            "rotation": int(rotation) % 360,
            "detected": False,
            "used_rotation": 0,
            "guides": None,
            "auto_guides": None,
            "boxes": None,
            "box_mode": False,
            "last_bg_thresh": int(bg_thresh),
            "last_crop_pad": int(crop_pad),
            "diagnostics": {},
        }
        if layout is None:
            return snapshot

        guide_snapshot = None if layout.get("box_mode") else clone_guides_snapshot(snapshot_guides(layout))
        auto_snapshot = None if layout.get("box_mode") else (
            clone_guides_snapshot(auto_guides) or clone_guides_snapshot(guide_snapshot)
        )
        snapshot.update(
            {
                "detected": True,
                "used_rotation": int(layout.get("used_rotation", 0)) % 360,
                "guides": guide_snapshot,
                "auto_guides": auto_snapshot,
                "boxes": [tuple(map(int, box)) for box in layout.get("boxes", [])],
                "box_mode": bool(layout.get("box_mode")),
                "diagnostics": dict(layout.get("diagnostics", {})),
            }
        )
        return snapshot

    def build_runtime_state_snapshot(self):
        return self.build_layout_state_snapshot(
            self.layout,
            rotation=self.rotation,
            auto_guides=self.auto_guides,
            bg_thresh=self.last_bg_thresh,
            crop_pad=self.last_crop_pad,
        )

    def apply_runtime_state_snapshot(self, snapshot: dict):
        if self.original_bgr is None:
            return

        self.rotation = int(snapshot.get("rotation", 0)) % 360
        self.display_bgr = rotate_image(self.original_bgr, self.rotation) if self.rotation else self.original_bgr
        self.last_bg_thresh = int(snapshot.get("last_bg_thresh", DEFAULT_BG_THRESH))
        self.last_crop_pad = int(snapshot.get("last_crop_pad", DEFAULT_CROP_PAD))
        self.layout = self.restore_layout_from_state(self.display_bgr, snapshot)
        self.auto_guides = clone_guides_snapshot(snapshot.get("auto_guides"))

        if self.layout is not None:
            self.set_status(
                "status_detection_done",
                strip_count=len(self.layout["strips"]),
                box_count=len(self.layout["boxes"]),
                rotation=self.rotation_text(self.layout["used_rotation"]),
            )
            preview_image = self.layout["oriented_image"]
            preview_rotation = (self.rotation + int(self.layout["used_rotation"])) % 360
        else:
            self.set_status(
                "status_opened",
                name=Path(self.current_path).name if self.current_path else "",
                width=self.original_bgr.shape[1],
                height=self.original_bgr.shape[0],
                backend=self.load_info["backend"] if self.load_info else "unknown",
            )
            preview_image = self.display_bgr
            preview_rotation = self.rotation

        self.set_preview_source(preview_image, reset_view=True, total_rotation=preview_rotation)
        self.save_current_state()
        self.update_undo_ui()

    def push_undo_snapshot(self):
        if not self.current_path or self.original_bgr is None:
            return

        state = self.get_file_state(self.current_path)
        stack = state.setdefault("undo_stack", [])
        stack.append(self.build_runtime_state_snapshot())
        if len(stack) > MAX_UNDO_STEPS:
            del stack[:-MAX_UNDO_STEPS]
        self.update_undo_ui()

    def update_undo_ui(self):
        if self.undo_btn is None:
            return
        if not self.current_path:
            self.undo_btn.configure(state="disabled")
            return
        state = self.get_file_state(self.current_path)
        self.undo_btn.configure(state="normal" if state.get("undo_stack") else "disabled")

    def build_detection_cache_key(
        self,
        *,
        rotation: int,
        total_frames: int,
        strip_count: int,
        bg_thresh: int,
        crop_pad: int,
        orientation: str,
    ):
        return (
            int(rotation) % 360,
            int(total_frames),
            int(strip_count),
            int(bg_thresh),
            int(crop_pad),
            str(orientation),
        )

    def restore_layout_from_detection_snapshot(self, display_bgr: np.ndarray, snapshot: dict):
        layout = self.restore_layout_from_state(display_bgr, snapshot)
        auto_guides = clone_guides_snapshot(snapshot.get("auto_guides"))
        return layout, auto_guides

    def get_cached_detection_result(self, state: dict, display_bgr: np.ndarray, cache_key):
        detection_cache = state.setdefault("detection_cache", OrderedDict())
        snapshot = detection_cache.get(cache_key)
        if snapshot is None:
            return None, None
        detection_cache.move_to_end(cache_key)
        return self.restore_layout_from_detection_snapshot(display_bgr, snapshot)

    def store_detection_result(self, state: dict, cache_key, layout, auto_guides, rotation: int, bg_thresh: int, crop_pad: int):
        detection_cache = state.setdefault("detection_cache", OrderedDict())
        detection_cache[cache_key] = self.build_layout_state_snapshot(
            layout,
            rotation=rotation,
            auto_guides=auto_guides,
            bg_thresh=bg_thresh,
            crop_pad=crop_pad,
        )
        detection_cache.move_to_end(cache_key)
        self._trim_detection_cache(detection_cache)

    def _trim_image_cache_locked(self):
        while self.image_cache and (
            len(self.image_cache) > MAX_IMAGE_CACHE_ITEMS or self.image_cache_bytes > MAX_IMAGE_CACHE_BYTES
        ):
            _path, entry = self.image_cache.popitem(last=False)
            image = entry.get("image")
            if image is not None:
                self.image_cache_bytes = max(0, self.image_cache_bytes - int(getattr(image, "nbytes", 0)))

    def _estimate_derived_entry_bytes(self, entry: dict) -> int:
        total = 0
        for key in ("preview_base", "analysis_bgr", "analysis_gray"):
            value = entry.get(key)
            if value is not None:
                total += int(getattr(value, "nbytes", 0))
        for value in entry.get("preview_rotations", {}).values():
            total += int(getattr(value, "nbytes", 0))
        for rotated in entry.get("analysis_rotations", {}).values():
            total += int(getattr(rotated.get("bgr"), "nbytes", 0))
            total += int(getattr(rotated.get("gray"), "nbytes", 0))
        return total

    def _trim_detection_cache(self, cache: OrderedDict):
        while len(cache) > MAX_DETECTION_CACHE_ITEMS:
            cache.popitem(last=False)

    def _trim_derived_cache_locked(self):
        while self.derived_cache and (
            len(self.derived_cache) > MAX_DERIVED_CACHE_ITEMS or self.derived_cache_bytes > MAX_DERIVED_CACHE_BYTES
        ):
            _path, entry = self.derived_cache.popitem(last=False)
            self.derived_cache_bytes = max(0, self.derived_cache_bytes - int(entry.get("_bytes", 0)))

    def _touch_derived_entry_locked(self, path: str, info: dict | None = None):
        entry = self.derived_cache.get(path)
        if entry is None:
            entry = {
                "info": dict(info or {}),
                "preview_base": None,
                "preview_ratio": None,
                "preview_rotations": {},
                "analysis_bgr": None,
                "analysis_gray": None,
                "analysis_scale": None,
                "analysis_rotations": {},
                "_bytes": 0,
            }
            self.derived_cache[path] = entry
        elif info:
            entry["info"] = dict(info)
        self.derived_cache.move_to_end(path)
        return entry

    def _update_derived_entry_locked(self, path: str, **updates):
        entry = self._touch_derived_entry_locked(path)
        previous_bytes = int(entry.get("_bytes", 0))
        entry.update(updates)
        entry["_bytes"] = self._estimate_derived_entry_bytes(entry)
        self.derived_cache_bytes = max(0, self.derived_cache_bytes + entry["_bytes"] - previous_bytes)
        self._trim_derived_cache_locked()
        return entry

    def _store_cached_image(self, path: str, image: np.ndarray, info: dict):
        with self.cache_lock:
            old = self.image_cache.pop(path, None)
            if old is not None:
                self.image_cache_bytes = max(0, self.image_cache_bytes - int(getattr(old.get("image"), "nbytes", 0)))
            self.image_cache[path] = {
                "image": image,
                "info": dict(info),
            }
            self.image_cache_bytes += int(getattr(image, "nbytes", 0))
            self._trim_image_cache_locked()
            self._touch_derived_entry_locked(path, info=info)

    def load_image_cached(self, path: str):
        with self.cache_lock:
            cached = self.image_cache.get(path)
            if cached is not None:
                self.image_cache.move_to_end(path)
                return cached["image"], dict(cached["info"])

        image, info = load_image(path)
        self._store_cached_image(path, image, info)
        return image, dict(info)

    def has_cached_image(self, path: str) -> bool:
        with self.cache_lock:
            return path in self.image_cache

    def schedule_async_ui_pump(self):
        if self.async_ui_job is not None:
            return
        try:
            self.async_ui_job = self.root.after(30, self.process_async_ui_queue)
        except tk.TclError:
            self.async_ui_job = None

    def on_root_destroy(self, event):
        if event.widget is not self.root:
            return
        if self.async_ui_job is not None:
            try:
                self.root.after_cancel(self.async_ui_job)
            except tk.TclError:
                pass
            self.async_ui_job = None
        try:
            self.progress_bar.stop()
        except Exception:
            pass

    def process_async_ui_queue(self):
        self.async_ui_job = None
        try:
            while True:
                kind, *payload = self.async_ui_queue.get_nowait()
                if kind == "preview_ready":
                    self.on_async_preview_ready(*payload)
                elif kind == "load_ready":
                    self.on_async_load_ready(*payload)
                elif kind == "load_failed":
                    self.on_async_load_failed(*payload)
        except queue.Empty:
            pass
        except tk.TclError:
            return

        self.schedule_async_ui_pump()

    def get_cached_analysis_base(self, path: str, image: np.ndarray):
        with self.cache_lock:
            cached = self.derived_cache.get(path)
            if cached is not None and cached.get("analysis_bgr") is not None and cached.get("analysis_gray") is not None:
                self.derived_cache.move_to_end(path)
                return (
                    cached["analysis_bgr"],
                    cached["analysis_gray"],
                    float(cached["analysis_scale"]),
                )

        analysis_bgr, analysis_scale = downscale_image(image, MAX_ANALYSIS_DIM)
        analysis_gray = to_gray8(analysis_bgr)
        with self.cache_lock:
            self._update_derived_entry_locked(
                path,
                analysis_bgr=analysis_bgr,
                analysis_gray=analysis_gray,
                analysis_scale=float(analysis_scale),
            )
        return analysis_bgr, analysis_gray, float(analysis_scale)

    def get_cached_analysis_rotation(self, path: str, image: np.ndarray, rotation: int):
        rotation = int(rotation) % 360
        analysis_bgr, analysis_gray, analysis_scale = self.get_cached_analysis_base(path, image)
        if rotation == 0:
            return analysis_bgr, analysis_gray, analysis_scale

        with self.cache_lock:
            cached = self.derived_cache.get(path)
            rotated = None if cached is None else cached.get("analysis_rotations", {}).get(rotation)
            if rotated is not None:
                self.derived_cache.move_to_end(path)
                return rotated["bgr"], rotated["gray"], analysis_scale

        rotated_bgr = rotate_image(analysis_bgr, rotation)
        rotated_gray = rotate_image(analysis_gray, rotation)
        with self.cache_lock:
            entry = self._touch_derived_entry_locked(path)
            analysis_rotations = dict(entry.get("analysis_rotations", {}))
            analysis_rotations[rotation] = {"bgr": rotated_bgr, "gray": rotated_gray}
            self._update_derived_entry_locked(path, analysis_rotations=analysis_rotations)
        return rotated_bgr, rotated_gray, analysis_scale

    def prefetch_image(self, path: str):
        if not path:
            return
        with self.cache_lock:
            cached = self.derived_cache.get(path)
            has_preview = cached is not None and cached.get("preview_base") is not None
            if path in self.image_cache or has_preview or path in self.prefetching_paths:
                return
            self.prefetching_paths.add(path)

        def worker():
            try:
                preview_result = load_preview_image(path, ASYNC_PREVIEW_MAX_DIM)
                if preview_result is None:
                    return
                preview_bgr, preview_ratio, preview_info = preview_result
                with self.cache_lock:
                    self._update_derived_entry_locked(
                        path,
                        info=preview_info,
                        preview_base=preview_bgr,
                        preview_ratio=float(preview_ratio),
                        preview_rotations={},
                    )
            except Exception:
                pass
            finally:
                with self.cache_lock:
                    self.prefetching_paths.discard(path)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

    def prefetch_neighbors(self):
        if not self.file_paths or self.current_index < 0:
            return
        for neighbor_index in (self.current_index - 1, self.current_index + 1):
            if 0 <= neighbor_index < len(self.file_paths):
                self.prefetch_image(self.file_paths[neighbor_index])

    def get_cached_preview_base(self, path: str, image: np.ndarray):
        with self.cache_lock:
            cached = self.derived_cache.get(path)
            if cached is not None and cached.get("preview_base") is not None:
                self.derived_cache.move_to_end(path)
                return cached["preview_base"], float(cached["preview_ratio"])

        preview_base, preview_ratio = downscale_image(image, MAX_PREVIEW_BASE_DIM)
        with self.cache_lock:
            self._update_derived_entry_locked(path, preview_base=preview_base, preview_ratio=float(preview_ratio))
        return preview_base, float(preview_ratio)

    def refresh_cached_preview_base(self, path: str, image: np.ndarray):
        preview_base, preview_ratio = downscale_image(image, MAX_PREVIEW_BASE_DIM)
        with self.cache_lock:
            self._update_derived_entry_locked(
                path,
                preview_base=preview_base,
                preview_ratio=float(preview_ratio),
                preview_rotations={},
            )
        return preview_base, float(preview_ratio)

    def try_get_cached_preview_base(self, path: str):
        with self.cache_lock:
            cached = self.derived_cache.get(path)
            if cached is None or cached.get("preview_base") is None:
                return None
            self.derived_cache.move_to_end(path)
            return cached["preview_base"], float(cached["preview_ratio"])

    def get_cached_preview_rotation(self, path: str, image: np.ndarray, rotation: int):
        rotation = int(rotation) % 360
        base_preview, base_ratio = self.get_cached_preview_base(path, image)
        if rotation == 0:
            return base_preview, base_ratio

        with self.cache_lock:
            cached = self.derived_cache.get(path)
            rotated = None if cached is None else cached.get("preview_rotations", {}).get(rotation)
            if rotated is not None:
                self.derived_cache.move_to_end(path)
                return rotated, base_ratio

        rotated = rotate_image(base_preview, rotation)
        with self.cache_lock:
            entry = self._touch_derived_entry_locked(path)
            preview_rotations = dict(entry.get("preview_rotations", {}))
            preview_rotations[rotation] = rotated
            self._update_derived_entry_locked(path, preview_rotations=preview_rotations)
        return rotated, base_ratio

    def update_navigation_ui(self):
        total = len(self.file_paths)
        if total <= 0 or self.current_index < 0 or self.current_index >= total:
            self.nav_var.set(self.tr("nav_empty"))
            self.prev_btn.configure(state="disabled")
            self.next_btn.configure(state="disabled")
            return

        self.nav_var.set(
            self.tr(
                "nav_index",
                index=self.current_index + 1,
                total=total,
                name=Path(self.file_paths[self.current_index]).name,
            )
        )
        self.prev_btn.configure(state="normal" if self.current_index > 0 else "disabled")
        self.next_btn.configure(state="normal" if self.current_index < total - 1 else "disabled")

    def save_current_state(self):
        if not self.current_path or self.original_bgr is None:
            return

        state = self.get_file_state(self.current_path)
        undo_stack = list(state.get("undo_stack", []))
        detection_cache = OrderedDict(state.get("detection_cache", OrderedDict()))
        state.update(self.build_runtime_state_snapshot())
        state["undo_stack"] = undo_stack
        state["detection_cache"] = detection_cache

    def restore_layout_from_state(self, display_bgr: np.ndarray, state: dict):
        if display_bgr is None or not state.get("detected"):
            return None

        used_rotation = int(state.get("used_rotation", 0)) % 360
        oriented_bgr = rotate_image(display_bgr, used_rotation)
        if state.get("box_mode"):
            return build_box_only_layout(
                oriented_bgr,
                used_rotation,
                state.get("boxes"),
            )

        snapshot = state.get("guides")
        if not snapshot:
            return None
        return build_layout_from_snapshot(
            oriented_bgr,
            used_rotation,
            snapshot,
            boxes=state.get("boxes"),
            bg_thresh=int(state.get("last_bg_thresh", DEFAULT_BG_THRESH)),
            crop_pad=int(state.get("last_crop_pad", DEFAULT_CROP_PAD)),
            diagnostics=dict(state.get("diagnostics", {})),
        )

    def load_file_list(self, paths):
        normalized = []
        seen = set()
        for raw_path in paths:
            path = Path(raw_path)
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTS:
                continue
            norm_key = str(path.resolve()).casefold()
            if norm_key in seen:
                continue
            seen.add(norm_key)
            normalized.append(str(path))

        if not normalized:
            messagebox.showinfo(self.tr("dialog_info"), self.tr("msg_no_images"))
            return

        self.file_paths = normalized
        self.file_states = {path: self.default_file_state() for path in normalized}
        self.current_index = -1
        self.current_path = None
        self.load_info = None
        self.original_bgr = None
        self.display_bgr = None
        self.layout = None
        self.auto_guides = None
        self.rotation = 0
        self.last_bg_thresh = DEFAULT_BG_THRESH
        self.last_crop_pad = DEFAULT_CROP_PAD
        self.set_preview_source(None)
        self.log("=" * 60)
        self.log(self.tr("log_loaded_file_list", total=len(normalized)))
        self.update_navigation_ui()
        self.update_undo_ui()
        self.show_image_at(0)

    def load_path_into_view(self, path: str):
        state = self.get_file_state(path)
        img, info = self.load_image_cached(path)
        rotation = int(state.get("rotation", 0)) % 360
        display_bgr = rotate_image(img, rotation) if rotation else img
        layout = self.restore_layout_from_state(display_bgr, state)

        self.current_path = path
        self.load_info = info
        self.original_bgr = img
        self.display_bgr = display_bgr
        self.layout = layout
        self.auto_guides = clone_guides_snapshot(state.get("auto_guides"))
        self.rotation = rotation
        self.last_bg_thresh = int(state.get("last_bg_thresh", DEFAULT_BG_THRESH))
        self.last_crop_pad = int(state.get("last_crop_pad", DEFAULT_CROP_PAD))

        self.log("=" * 60)
        self.log(self.tr("log_open_image", path=path))
        self.log(self.tr("log_size", width=img.shape[1], height=img.shape[0]))
        self.log(self.tr("log_backend", backend=info["backend"]))
        if info["attempts"]:
            self.log(self.tr("log_other_attempts"))
            for attempt in info["attempts"]:
                self.log(f"  {attempt}")

        if layout is not None:
            self.set_status(
                "status_detection_done",
                strip_count=len(layout["strips"]),
                box_count=len(layout["boxes"]),
                rotation=self.rotation_text(layout["used_rotation"]),
            )
            self.set_preview_source(
                layout["oriented_image"],
                reset_view=True,
                total_rotation=(self.rotation + int(layout["used_rotation"])) % 360,
            )
        else:
            self.set_status(
                "status_opened",
                name=Path(path).name,
                width=img.shape[1],
                height=img.shape[0],
                backend=info["backend"],
            )
            self.set_preview_source(display_bgr, reset_view=True, total_rotation=self.rotation)
        self.update_undo_ui()

    def show_loading_preview(self, path: str):
        cached_preview = self.try_get_cached_preview_base(path)
        state = self.get_file_state(path)
        rotation = int(state.get("rotation", 0)) % 360
        if cached_preview is None:
            self.preview.set_content(None, layout=None)
            return

        preview_base, preview_ratio = cached_preview
        rotated_preview = rotate_image(preview_base, rotation) if rotation else preview_base
        self.preview.set_content(
            rotated_preview,
            preview_ratio,
            layout=None,
            reset_view=True,
            bg_thresh=int(state.get("last_bg_thresh", DEFAULT_BG_THRESH)),
            crop_pad=int(state.get("last_crop_pad", DEFAULT_CROP_PAD)),
        )

    def start_async_load(self, path: str, index: int):
        state = self.get_file_state(path)
        self.current_index = index
        self.current_path = path
        self.load_info = None
        self.original_bgr = None
        self.display_bgr = None
        self.layout = None
        self.auto_guides = None
        self.rotation = int(state.get("rotation", 0)) % 360
        self.last_bg_thresh = int(state.get("last_bg_thresh", DEFAULT_BG_THRESH))
        self.last_crop_pad = int(state.get("last_crop_pad", DEFAULT_CROP_PAD))
        self.loading = True
        self.load_request_token += 1
        token = self.load_request_token
        self.set_status("status_loading", name=Path(path).name)
        self.show_progress(self.tr("progress_loading", name=Path(path).name), mode="indeterminate")
        self.update_navigation_ui()
        self.update_undo_ui()
        self.show_loading_preview(path)

        def worker():
            preview_result = None
            if self.try_get_cached_preview_base(path) is None:
                preview_result = load_preview_image(path, ASYNC_PREVIEW_MAX_DIM)
                if preview_result is not None:
                    preview_bgr, preview_ratio, preview_info = preview_result
                    with self.cache_lock:
                        self._update_derived_entry_locked(
                            path,
                            info=preview_info,
                            preview_base=preview_bgr,
                            preview_ratio=float(preview_ratio),
                            preview_rotations={},
                        )
                    self.async_ui_queue.put(("preview_ready", path, token))

            try:
                image, info = load_image(path)
                self._store_cached_image(path, image, info)
                self.refresh_cached_preview_base(path, image)
                self.get_cached_analysis_base(path, image)
            except Exception as exc:
                tb_text = traceback.format_exc()
                self.async_ui_queue.put(("load_failed", path, token, exc, tb_text))
                return

            self.async_ui_queue.put(("load_ready", path, token))

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

    def on_async_preview_ready(self, path: str, token: int):
        if token != self.load_request_token or path != self.current_path or not self.loading:
            return
        self.show_loading_preview(path)

    def on_async_load_failed(self, path: str, token: int, error: Exception, tb_text: str):
        if token != self.load_request_token or path != self.current_path:
            return
        self.loading = False
        self.hide_progress()
        self.preview.set_content(None, layout=None)
        self.update_undo_ui()
        self.log(tb_text)
        messagebox.showerror(self.tr("title_open_failed"), str(error))

    def on_async_load_ready(self, path: str, token: int):
        if token != self.load_request_token or path != self.current_path:
            return
        try:
            self.loading = False
            self.load_path_into_view(path)
            self.update_navigation_ui()
            self.prefetch_neighbors()
        except Exception as exc:
            self.log(traceback.format_exc())
            messagebox.showerror(self.tr("title_open_failed"), str(exc))
        finally:
            self.hide_progress()

    def show_image_at(self, index: int):
        if not self.file_paths:
            self.current_index = -1
            self.current_path = None
            self.update_navigation_ui()
            self.update_undo_ui()
            return

        index = clamp(index, 0, len(self.file_paths) - 1)
        if self.current_index == index and self.current_path == self.file_paths[index] and self.original_bgr is not None:
            self.update_navigation_ui()
            return

        if self.current_path is not None:
            self.save_current_state()

        path = self.file_paths[index]
        try:
            if self.has_cached_image(path):
                self.hide_progress()
                self.load_path_into_view(path)
                self.current_index = index
                self.loading = False
                self.update_navigation_ui()
                self.prefetch_neighbors()
            else:
                self.start_async_load(path, index)
                self.prefetch_neighbors()
        except Exception as exc:
            self.log(traceback.format_exc())
            messagebox.showerror(self.tr("title_open_failed"), str(exc))

    def show_prev_image(self):
        if self.current_index > 0:
            self.show_image_at(self.current_index - 1)

    def show_next_image(self):
        if 0 <= self.current_index < len(self.file_paths) - 1:
            self.show_image_at(self.current_index + 1)

    def open_image(self):
        paths = filedialog.askopenfilenames(
            title=self.tr("dialog_open_images"),
            filetypes=[
                (self.tr("filetypes_supported"), OPEN_FILE_PATTERN),
                (self.tr("filetypes_all"), "*.*"),
            ],
        )
        if paths:
            self.load_file_list(paths)

    def rotate_current(self, deg: int):
        if self.loading:
            messagebox.showinfo(self.tr("dialog_info"), self.tr("msg_still_loading"))
            return
        if self.original_bgr is None:
            return
        self.push_undo_snapshot()
        previous_layout = self.layout
        self.rotation = (self.rotation + deg) % 360
        self.display_bgr = rotate_image(self.original_bgr, self.rotation)
        if previous_layout is not None:
            old_h, old_w = previous_layout["oriented_image"].shape[:2]
            rotated_image = rotate_image(previous_layout["oriented_image"], deg)
            rotated_boxes = [rotate_box(box, old_w, old_h, deg) for box in previous_layout.get("boxes", [])]
            self.layout = build_box_only_layout(
                rotated_image,
                int(previous_layout.get("used_rotation", 0)) % 360,
                rotated_boxes,
                diagnostics=dict(previous_layout.get("diagnostics", {})),
            )
            self.auto_guides = None
        else:
            self.layout = None
            self.auto_guides = None
        self.set_status("status_rotated", rotation=self.rotation_text(self.rotation))
        preview_image = self.layout["oriented_image"] if self.layout is not None else self.display_bgr
        preview_rotation = self.rotation if self.layout is None else (self.rotation + int(self.layout["used_rotation"])) % 360
        self.set_preview_source(preview_image, reset_view=True, total_rotation=preview_rotation)
        self.save_current_state()
        self.update_undo_ui()

    def reset_rotation(self):
        if self.loading:
            messagebox.showinfo(self.tr("dialog_info"), self.tr("msg_still_loading"))
            return
        if self.original_bgr is None:
            return
        if self.rotation == 0 and self.layout is None:
            return
        self.push_undo_snapshot()
        previous_layout = self.layout
        delta = (-self.rotation) % 360
        self.rotation = 0
        self.display_bgr = self.original_bgr
        if previous_layout is not None and delta:
            old_h, old_w = previous_layout["oriented_image"].shape[:2]
            rotated_image = rotate_image(previous_layout["oriented_image"], delta)
            rotated_boxes = [rotate_box(box, old_w, old_h, delta) for box in previous_layout.get("boxes", [])]
            self.layout = build_box_only_layout(
                rotated_image,
                int(previous_layout.get("used_rotation", 0)) % 360,
                rotated_boxes,
                diagnostics=dict(previous_layout.get("diagnostics", {})),
            )
            self.auto_guides = None
        elif previous_layout is not None:
            self.layout = previous_layout
            self.auto_guides = None
        else:
            self.layout = None
            self.auto_guides = None
        self.set_status("status_rotation_reset")
        preview_image = self.layout["oriented_image"] if self.layout is not None else self.display_bgr
        preview_rotation = self.rotation if self.layout is None else (self.rotation + int(self.layout["used_rotation"])) % 360
        self.set_preview_source(preview_image, reset_view=True, total_rotation=preview_rotation)
        self.save_current_state()
        self.update_undo_ui()

    def run_detection(self):
        if self.loading:
            messagebox.showinfo(self.tr("dialog_info"), self.tr("msg_still_loading"))
            return
        if self.display_bgr is None:
            messagebox.showinfo(self.tr("dialog_info"), self.tr("msg_need_open_image"))
            return

        try:
            total_frames, strip_count, bg_thresh, crop_pad, orientation = self.parse_params()
            self.push_undo_snapshot()
            self.last_bg_thresh = bg_thresh
            self.last_crop_pad = crop_pad
            state = self.get_file_state(self.current_path)
            cache_key = self.build_detection_cache_key(
                rotation=self.rotation,
                total_frames=total_frames,
                strip_count=strip_count,
                bg_thresh=bg_thresh,
                crop_pad=crop_pad,
                orientation=orientation,
            )
            cached_layout, cached_auto_guides = self.get_cached_detection_result(state, self.display_bgr, cache_key)
            if cached_layout is not None:
                self.layout = cached_layout
                self.auto_guides = cached_auto_guides
            else:
                analysis_bgr, analysis_gray, analysis_scale = self.get_cached_analysis_rotation(
                    self.current_path,
                    self.original_bgr,
                    self.rotation,
                )
                self.layout = detect_layout(
                    self.display_bgr,
                    bg_thresh=bg_thresh,
                    orientation_mode=orientation,
                    total_frames=total_frames,
                    manual_strips=strip_count,
                    crop_pad=crop_pad,
                    analysis_bgr=analysis_bgr,
                    analysis_gray=analysis_gray,
                    analysis_scale=analysis_scale,
                )
                self.auto_guides = snapshot_guides(self.layout)
                self.store_detection_result(
                    state,
                    cache_key,
                    self.layout,
                    self.auto_guides,
                    rotation=self.rotation,
                    bg_thresh=bg_thresh,
                    crop_pad=crop_pad,
                )

            diag = self.layout["diagnostics"]
            self.log("=" * 60)
            self.log(
                self.tr(
                    "log_detection_done",
                    strip_count=len(self.layout["strips"]),
                    box_count=len(self.layout["boxes"]),
                    rotation=self.rotation_text(self.layout["used_rotation"]),
                )
            )
            self.log(
                self.tr(
                    "log_analysis_size",
                    width=diag["analysis_size"][0],
                    height=diag["analysis_size"][1],
                    scale=diag["analysis_scale"],
                )
            )
            for candidate in diag["candidates"]:
                self.log(
                    self.tr(
                        "log_candidate",
                        rotation=self.rotation_text(candidate["rotation"]),
                        score=candidate["score"],
                        strip_count=candidate["strip_count"],
                        cover=candidate["mean_cover"],
                        aspect=candidate["mean_aspect"],
                    )
                )
            for info in self.layout["strip_infos"]:
                self.log(
                    self.tr(
                        "log_strip_info",
                        index=info["strip_index"] + 1,
                        x_range=info["x_range"],
                        frame_count=info["frame_count"],
                        cuts=info["cuts"],
                    )
                )

            self.set_status(
                "status_detection_done",
                strip_count=len(self.layout["strips"]),
                box_count=len(self.layout["boxes"]),
                rotation=self.rotation_text(self.layout["used_rotation"]),
            )
            self.set_preview_source(
                self.layout["oriented_image"],
                reset_view=True,
                total_rotation=(self.rotation + int(self.layout["used_rotation"])) % 360,
            )
            self.save_current_state()
            self.update_undo_ui()
        except Exception as exc:
            self.log(traceback.format_exc())
            messagebox.showerror(self.tr("title_detect_failed"), str(exc))

    def build_layout_for_path(
        self,
        path: str,
        state: dict,
        total_frames: int,
        strip_count: int,
        bg_thresh: int,
        crop_pad: int,
        orientation: str,
    ):
        img, info = self.load_image_cached(path)
        rotation = int(state.get("rotation", 0)) % 360
        display_bgr = rotate_image(img, rotation) if rotation else img
        layout = self.restore_layout_from_state(display_bgr, state)

        if layout is None:
            cache_key = self.build_detection_cache_key(
                rotation=rotation,
                total_frames=total_frames,
                strip_count=strip_count,
                bg_thresh=bg_thresh,
                crop_pad=crop_pad,
                orientation=orientation,
            )
            layout, auto_guides = self.get_cached_detection_result(state, display_bgr, cache_key)
            if layout is None:
                analysis_bgr, analysis_gray, analysis_scale = self.get_cached_analysis_rotation(path, img, rotation)
                layout = detect_layout(
                    display_bgr,
                    bg_thresh=bg_thresh,
                    orientation_mode=orientation,
                    total_frames=total_frames,
                    manual_strips=strip_count,
                    crop_pad=crop_pad,
                    analysis_bgr=analysis_bgr,
                    analysis_gray=analysis_gray,
                    analysis_scale=analysis_scale,
                )
                auto_guides = snapshot_guides(layout)
                self.store_detection_result(
                    state,
                    cache_key,
                    layout,
                    auto_guides,
                    rotation=rotation,
                    bg_thresh=bg_thresh,
                    crop_pad=crop_pad,
                )

            state.update(
                self.build_layout_state_snapshot(
                    layout,
                    rotation=rotation,
                    auto_guides=auto_guides,
                    bg_thresh=bg_thresh,
                    crop_pad=crop_pad,
                )
            )

        return layout, info

    def export_current(self):
        if self.loading:
            messagebox.showinfo(self.tr("dialog_info"), self.tr("msg_still_loading"))
            return
        if self.layout is None or self.current_path is None:
            messagebox.showinfo(self.tr("dialog_info"), self.tr("msg_need_detection"))
            return

        out_dir = filedialog.askdirectory(title=self.tr("dialog_output_dir"))
        if not out_dir:
            return

        try:
            self.save_current_state()
            total_boxes = max(1, len(self.layout.get("boxes", [])))
            self.show_progress(
                self.tr("progress_export_current", name=Path(self.current_path).name),
                mode="determinate",
                maximum=total_boxes,
                value=0,
            )
            total = save_crops(
                self.layout,
                self.current_path,
                out_dir,
                fmt=self.format_id,
                jpeg_quality=self.get_jpeg_quality(),
                png_compress_level=self.get_png_compress_level(),
                tiff_compression=self.tiff_compression_id,
                progress_callback=lambda processed, maximum: self.update_progress(
                    value=processed,
                    maximum=max(1, maximum),
                ),
            )
            self.log(self.tr("log_export_done", total=total, path=out_dir))
            self.hide_progress()
            messagebox.showinfo(self.tr("dialog_done"), self.tr("msg_export_done", total=total, path=out_dir))
        except Exception as exc:
            self.hide_progress()
            self.log(traceback.format_exc())
            messagebox.showerror(self.tr("title_export_failed"), str(exc))
        finally:
            self.hide_progress()

    def export_all(self):
        if not self.file_paths:
            messagebox.showinfo(self.tr("dialog_info"), self.tr("msg_no_file_list"))
            return

        out_root = filedialog.askdirectory(title=self.tr("dialog_batch_output_dir"))
        if not out_root:
            return

        try:
            self.save_current_state()
            total_frames, strip_count, bg_thresh, crop_pad, orientation = self.parse_params()

            ok = 0
            failed = 0
            exported_total = 0
            total_files = max(1, len(self.file_paths))
            self.show_progress(
                self.tr("progress_export_all", index=0, total=total_files, name=""),
                mode="determinate",
                maximum=total_files,
                value=0,
            )
            for index, path in enumerate(self.file_paths, start=1):
                self.update_progress(
                    text=self.tr("progress_export_all", index=index, total=total_files, name=Path(path).name),
                    value=index - 1,
                )
                try:
                    state = self.get_file_state(path)
                    layout, info = self.build_layout_for_path(
                        path,
                        state,
                        total_frames=total_frames,
                        strip_count=strip_count,
                        bg_thresh=bg_thresh,
                        crop_pad=crop_pad,
                        orientation=orientation,
                    )
                    target = Path(out_root) / f"{Path(path).stem}_split"
                    count = save_crops(
                        layout,
                        path,
                        str(target),
                        fmt=self.format_id,
                        jpeg_quality=self.get_jpeg_quality(),
                        png_compress_level=self.get_png_compress_level(),
                        tiff_compression=self.tiff_compression_id,
                    )
                    ok += 1
                    exported_total += count
                    self.log(self.tr("log_batch_success", name=Path(path).name, backend=info["backend"], count=count))
                except Exception as exc:
                    failed += 1
                    self.log(self.tr("log_batch_failed", name=Path(path).name, error=exc))
                finally:
                    self.update_progress(value=index)

            self.log(self.tr("log_export_all_done", ok=ok, failed=failed, total=exported_total, path=out_root))
            self.hide_progress()
            messagebox.showinfo(
                self.tr("dialog_done"),
                self.tr("msg_export_all_done", total=exported_total, ok=ok, failed=failed, path=out_root),
            )
        except Exception as exc:
            self.hide_progress()
            self.log(traceback.format_exc())
            messagebox.showerror(self.tr("title_export_failed"), str(exc))
        finally:
            self.hide_progress()

    def batch_process_folder(self):
        folder = filedialog.askdirectory(title=self.tr("dialog_open_folder"))
        if not folder:
            return

        try:
            files = [
                path for path in Path(folder).iterdir()
                if path.is_file() and path.suffix.lower() in SUPPORTED_EXTS
            ]
            if not files:
                messagebox.showinfo(self.tr("dialog_info"), self.tr("msg_no_images"))
                return
            self.load_file_list([str(path) for path in sorted(files, key=lambda item: item.name.lower())])
        except Exception as exc:
            self.log(traceback.format_exc())
            messagebox.showerror(self.tr("title_open_failed"), str(exc))

    def set_preview_source(self, img_bgr=None, reset_view: bool = False, total_rotation: int | None = None):
        if img_bgr is None:
            self.preview.set_content(None, layout=None)
            return

        if self.current_path and self.original_bgr is not None:
            if total_rotation is not None:
                preview_base_bgr, base_ratio = self.get_cached_preview_rotation(
                    self.current_path,
                    self.original_bgr,
                    total_rotation,
                )
            else:
                preview_base_bgr, base_ratio = self.get_cached_preview_base(self.current_path, self.original_bgr)
        else:
            preview_base_bgr, base_ratio = downscale_image(img_bgr, MAX_PREVIEW_BASE_DIM)

        self.preview.set_content(
            preview_base_bgr,
            base_ratio,
            layout=self.layout,
            reset_view=reset_view,
            bg_thresh=self.last_bg_thresh,
            crop_pad=self.last_crop_pad,
        )

    def update_zoom_label(self):
        self.preview.update_zoom_label()

    def redraw_preview(self):
        self.preview.redraw()

    def schedule_preview_redraw(self):
        self.preview.schedule_redraw()

    def fit_preview(self):
        self.preview.fit_preview()

    def reset_preview_zoom(self):
        self.preview.reset_zoom()

    def on_preview_edit_started(self):
        self.push_undo_snapshot()

    def on_preview_manual_adjust_done(self, layout):
        self.set_status("status_guides_rebuilt", box_count=len(layout["boxes"]))
        self.log(
            self.tr(
                "log_manual_adjust_done",
                strip_count=len(layout["strips"]),
                box_count=len(layout["boxes"]),
            )
        )
        self.save_current_state()
        self.update_undo_ui()

    def reset_manual_guides(self):
        if self.loading:
            messagebox.showinfo(self.tr("dialog_info"), self.tr("msg_still_loading"))
            return
        if self.layout is None or self.auto_guides is None:
            messagebox.showinfo(self.tr("dialog_info"), self.tr("msg_no_guides"))
            return

        self.push_undo_snapshot()
        self.layout["strips"] = [tuple(strip) for strip in self.auto_guides["strips"]]
        for index, cuts in enumerate(self.auto_guides["cuts"]):
            if index < len(self.layout["strip_infos"]):
                self.layout["strip_infos"][index]["cuts"] = list(cuts)
                self.layout["strip_infos"][index]["x_range"] = self.layout["strips"][index]

        rebuild_boxes_from_guides(self.layout, bg_thresh=self.last_bg_thresh, crop_pad=self.last_crop_pad)
        self.preview.set_layout(self.layout, bg_thresh=self.last_bg_thresh, crop_pad=self.last_crop_pad)
        self.set_status("status_guides_reset")
        self.log(self.tr("log_guides_reset"))
        self.redraw_preview()
        self.save_current_state()
        self.update_undo_ui()

    def undo_last_action(self):
        if not self.current_path or self.original_bgr is None:
            return

        state = self.get_file_state(self.current_path)
        undo_stack = state.get("undo_stack", [])
        if not undo_stack:
            self.update_undo_ui()
            return

        snapshot = undo_stack.pop()
        self.apply_runtime_state_snapshot(snapshot)
        self.set_status("status_undo_done")
        self.log(self.tr("log_undo"))
        self.save_current_state()
        self.update_undo_ui()

    def on_undo_shortcut(self, _event=None):
        self.undo_last_action()
        return "break"


def main():
    root = tk.Tk()
    app = SplitterApp(root)
    root.mainloop()



from __future__ import annotations

import math

import cv2
import tkinter as tk
from PIL import ImageTk
from tkinter import ttk

from core.constants import DEFAULT_BG_THRESH, DEFAULT_CROP_PAD, MIN_FRAME_HEIGHT, MIN_STRIP_WIDTH
from core.image_loader import cv_to_pil
from core.splitter_engine import rebuild_boxes_from_guides
from core.utils import clamp


class PreviewCanvas:
    def __init__(self, root, parent, tr, on_manual_adjust_done=None, on_edit_started=None):
        self.root = root
        self.tr = tr
        self.on_manual_adjust_done = on_manual_adjust_done
        self.on_edit_started = on_edit_started

        self.theme_palette = {
            "canvas_bg": "#1f1f1f",
            "overlay_strip": "#ff4d4d",
            "overlay_strip_text": "#ff8c8c",
            "overlay_cut": "#4cff85",
            "overlay_box": "#ffb347",
            "overlay_handle": "#ffd480",
        }

        self.layout = None
        self.last_bg_thresh = DEFAULT_BG_THRESH
        self.last_crop_pad = DEFAULT_CROP_PAD

        self.preview_base_bgr = None
        self.preview_base_ratio = 1.0
        self.preview_zoom = 1.0
        self.preview_job = None
        self.tk_preview = None

        self.drag_mode = None
        self.drag_payload = None
        self.dragging_guides = False
        self.drag_changed = False
        self.edit_started = False

        self.zoom_var = tk.StringVar()

        self.container = ttk.Frame(parent)
        self.container.pack(fill="both", expand=True)

        self.canvas_frame = ttk.Frame(self.container)
        self.canvas_frame.pack(fill="both", expand=True)

        self.canvas = tk.Canvas(self.canvas_frame, bg=self.theme_palette["canvas_bg"], highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)

        self.y_scroll = ttk.Scrollbar(self.canvas_frame, orient="vertical", command=self.canvas_yview)
        self.y_scroll.pack(side="right", fill="y")
        self.x_scroll = ttk.Scrollbar(self.container, orient="horizontal", command=self.canvas_xview)
        self.x_scroll.pack(fill="x")

        self.canvas.configure(yscrollcommand=self.y_scroll.set, xscrollcommand=self.x_scroll.set)
        self.canvas.bind("<Configure>", self.on_canvas_configure)
        self.canvas.bind("<MouseWheel>", self.on_mousewheel)
        self.canvas.bind("<ButtonPress-1>", self.on_left_press)
        self.canvas.bind("<B1-Motion>", self.on_left_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_left_release)
        self.canvas.bind("<Motion>", self.on_canvas_motion)
        self.canvas.bind("<Leave>", lambda _event: self.canvas.configure(cursor="arrow"))

        self.update_zoom_label()

    def set_theme(self, theme_palette: dict):
        self.theme_palette = dict(theme_palette)
        self.canvas.configure(bg=self.theme_palette["canvas_bg"])
        self.schedule_redraw()

    def set_layout(self, layout, bg_thresh: int | None = None, crop_pad: int | None = None):
        self.layout = layout
        if bg_thresh is not None:
            self.last_bg_thresh = int(bg_thresh)
        if crop_pad is not None:
            self.last_crop_pad = int(crop_pad)

    def set_content(self, base_bgr, base_ratio: float = 1.0, layout=None, reset_view: bool = False, bg_thresh: int | None = None, crop_pad: int | None = None):
        self.set_layout(layout, bg_thresh=bg_thresh, crop_pad=crop_pad)

        if base_bgr is None:
            self.preview_base_bgr = None
            self.preview_base_ratio = 1.0
            self.canvas.delete("all")
            self.update_zoom_label()
            return

        self.preview_base_bgr = base_bgr
        self.preview_base_ratio = float(base_ratio)
        self.canvas.update_idletasks()
        if reset_view:
            self.preview_zoom = self.compute_fit_zoom()
            self.canvas.xview_moveto(0)
            self.canvas.yview_moveto(0)
        self.redraw()

    def compute_fit_zoom(self):
        if self.preview_base_bgr is None:
            return 1.0
        canvas_w = max(1, self.canvas.winfo_width())
        canvas_h = max(1, self.canvas.winfo_height())
        img_h, img_w = self.preview_base_bgr.shape[:2]
        return max(0.05, min(12.0, min(canvas_w / img_w, canvas_h / img_h)))

    def update_zoom_label(self):
        ratio_note = ""
        if self.preview_base_ratio < 0.999:
            ratio_note = f" | {self.tr('preview_ratio_note', ratio=self.preview_base_ratio)}"
        self.zoom_var.set(f"{self.tr('zoom_prefix')} {self.preview_zoom:.2f}x{ratio_note}")

    def redraw(self):
        self.preview_job = None
        self.canvas.delete("all")

        if self.preview_base_bgr is None:
            self.update_zoom_label()
            return

        zoom = max(0.01, float(self.preview_zoom))
        base_h, base_w = self.preview_base_bgr.shape[:2]
        total_w = max(1, int(round(base_w * zoom)))
        total_h = max(1, int(round(base_h * zoom)))
        self.canvas.configure(scrollregion=(0, 0, total_w, total_h))

        canvas_w = max(1, self.canvas.winfo_width())
        canvas_h = max(1, self.canvas.winfo_height())

        x0 = 0 if total_w <= canvas_w else max(0.0, self.canvas.canvasx(0))
        y0 = 0 if total_h <= canvas_h else max(0.0, self.canvas.canvasy(0))
        x1 = min(float(total_w), x0 + canvas_w + 2)
        y1 = min(float(total_h), y0 + canvas_h + 2)

        src_x0 = clamp(int(math.floor(x0 / zoom)), 0, max(0, base_w - 1))
        src_y0 = clamp(int(math.floor(y0 / zoom)), 0, max(0, base_h - 1))
        src_x1 = clamp(int(math.ceil(x1 / zoom)), src_x0 + 1, base_w)
        src_y1 = clamp(int(math.ceil(y1 / zoom)), src_y0 + 1, base_h)

        tile = self.preview_base_bgr[src_y0:src_y1, src_x0:src_x1]
        dst_w = max(1, int(round((src_x1 - src_x0) * zoom)))
        dst_h = max(1, int(round((src_y1 - src_y0) * zoom)))
        interp = cv2.INTER_AREA if zoom < 1.0 else (cv2.INTER_NEAREST if zoom >= 4.0 else cv2.INTER_LINEAR)
        resized = cv2.resize(tile, (dst_w, dst_h), interpolation=interp)

        self.tk_preview = ImageTk.PhotoImage(cv_to_pil(resized))
        self.canvas.create_image(src_x0 * zoom, src_y0 * zoom, anchor="nw", image=self.tk_preview, tags=("preview",))
        self.draw_overlay()
        self.update_zoom_label()

    def schedule_redraw(self):
        if self.preview_job is None:
            self.preview_job = self.root.after(15, self.redraw)

    def draw_overlay(self):
        if not self.layout:
            return

        scale = self.preview_base_ratio * self.preview_zoom
        if scale <= 0:
            return

        img_h, _ = self.layout["oriented_image"].shape[:2]
        canvas_img_h = img_h * scale

        if not self.layout.get("box_mode"):
            for strip_index, (x1, x2) in enumerate(self.layout["strips"], start=1):
                cx1 = x1 * scale
                cx2 = x2 * scale
                self.canvas.create_line(cx1, 0, cx1, canvas_img_h, fill=self.theme_palette["overlay_strip"], width=2, tags="overlay")
                self.canvas.create_line(cx2, 0, cx2, canvas_img_h, fill=self.theme_palette["overlay_strip"], width=2, tags="overlay")
                self.canvas.create_text(cx1 + 6, 12, text=f"S{strip_index}", fill=self.theme_palette["overlay_strip_text"], anchor="nw", tags="overlay")

            for info in self.layout["strip_infos"]:
                x1, x2 = info["x_range"]
                for cut_index, y in enumerate(info["cuts"]):
                    cy = y * scale
                    is_inner = 0 < cut_index < len(info["cuts"]) - 1
                    self.canvas.create_line(
                        x1 * scale,
                        cy,
                        x2 * scale,
                        cy,
                        fill=self.theme_palette["overlay_cut"],
                        width=2 if is_inner else 1,
                        dash=() if is_inner else (4, 2),
                        tags="overlay",
                    )

        if self.dragging_guides and not self.layout.get("box_mode"):
            return

        for index, (x1, y1, x2, y2) in enumerate(self.layout["boxes"], start=1):
            self.canvas.create_rectangle(
                x1 * scale,
                y1 * scale,
                x2 * scale,
                y2 * scale,
                outline=self.theme_palette["overlay_box"],
                width=2,
                tags="overlay",
            )
            self.canvas.create_text(
                x1 * scale + 6,
                y1 * scale + 6,
                text=str(index),
                fill=self.theme_palette["overlay_box"],
                anchor="nw",
                tags="overlay",
            )
            if self.layout.get("box_mode"):
                handle = max(3.0, min(8.0, 4.0 / max(self.preview_base_ratio * self.preview_zoom, 1e-6)))
                mid_x = (x1 + x2) * 0.5 * scale
                mid_y = (y1 + y2) * 0.5 * scale
                for hx, hy in (
                    (x1 * scale, mid_y),
                    (x2 * scale, mid_y),
                    (mid_x, y1 * scale),
                    (mid_x, y2 * scale),
                ):
                    self.canvas.create_rectangle(
                        hx - handle,
                        hy - handle,
                        hx + handle,
                        hy + handle,
                        outline=self.theme_palette["overlay_handle"],
                        fill=self.theme_palette["overlay_handle"],
                        tags="overlay",
                    )

    def fit_preview(self):
        if self.preview_base_bgr is None:
            return
        self.preview_zoom = self.compute_fit_zoom()
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)
        self.redraw()

    def reset_zoom(self):
        if self.preview_base_bgr is None:
            return
        self.preview_zoom = 1.0
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)
        self.redraw()

    def canvas_xview(self, *args):
        self.canvas.xview(*args)
        self.schedule_redraw()

    def canvas_yview(self, *args):
        self.canvas.yview(*args)
        self.schedule_redraw()

    def on_canvas_configure(self, _event=None):
        if self.preview_base_bgr is not None:
            self.schedule_redraw()

    def on_mousewheel(self, event):
        if self.preview_base_bgr is None:
            return

        factor = 1.15 if event.delta > 0 else 1.0 / 1.15
        old_zoom = self.preview_zoom
        new_zoom = clamp(old_zoom * factor, 0.05, 12.0)
        if abs(new_zoom - old_zoom) < 1e-6:
            return

        base_h, base_w = self.preview_base_bgr.shape[:2]
        px = self.canvas.canvasx(event.x) / old_zoom
        py = self.canvas.canvasy(event.y) / old_zoom

        self.preview_zoom = new_zoom
        total_w = max(1, int(round(base_w * new_zoom)))
        total_h = max(1, int(round(base_h * new_zoom)))
        self.canvas.configure(scrollregion=(0, 0, total_w, total_h))

        new_left = px * new_zoom - event.x
        new_top = py * new_zoom - event.y
        self.canvas.xview_moveto(clamp(new_left / max(1, total_w), 0.0, 1.0))
        self.canvas.yview_moveto(clamp(new_top / max(1, total_h), 0.0, 1.0))
        self.redraw()

    def screen_to_image(self, event_x: int, event_y: int):
        scale = self.preview_base_ratio * self.preview_zoom
        if scale <= 0:
            return 0.0, 0.0
        return self.canvas.canvasx(event_x) / scale, self.canvas.canvasy(event_y) / scale

    def hit_test_guide(self, event):
        if not self.layout:
            return None

        img_x, img_y = self.screen_to_image(event.x, event.y)
        scale = self.preview_base_ratio * self.preview_zoom
        tolerance = max(4.0, 10.0 / max(scale, 1e-6))
        hits = []

        if self.layout.get("box_mode"):
            for box_index, (x1, y1, x2, y2) in enumerate(self.layout["boxes"]):
                if not (x1 - tolerance <= img_x <= x2 + tolerance and y1 - tolerance <= img_y <= y2 + tolerance):
                    continue

                edge_hits = []
                if y1 - tolerance <= img_y <= y2 + tolerance:
                    if abs(img_x - x1) <= tolerance:
                        edge_hits.append((abs(img_x - x1), {"kind": "box_edge", "box_index": box_index, "edge": "left"}))
                    if abs(img_x - x2) <= tolerance:
                        edge_hits.append((abs(img_x - x2), {"kind": "box_edge", "box_index": box_index, "edge": "right"}))
                if x1 - tolerance <= img_x <= x2 + tolerance:
                    if abs(img_y - y1) <= tolerance:
                        edge_hits.append((abs(img_y - y1), {"kind": "box_edge", "box_index": box_index, "edge": "top"}))
                    if abs(img_y - y2) <= tolerance:
                        edge_hits.append((abs(img_y - y2), {"kind": "box_edge", "box_index": box_index, "edge": "bottom"}))

                if edge_hits:
                    hits.extend(edge_hits)
                    continue

                if x1 <= img_x <= x2 and y1 <= img_y <= y2:
                    hits.append((tolerance + 1.0, {"kind": "box_move", "box_index": box_index}))

            if not hits:
                return None
            hits.sort(key=lambda item: item[0])
            return hits[0][1]

        for strip_index, strip in enumerate(self.layout["strips"]):
            x1, x2 = strip
            if abs(img_x - x1) <= tolerance:
                hits.append((abs(img_x - x1), {"kind": "strip_boundary", "strip_index": strip_index, "side": "left"}))
            if abs(img_x - x2) <= tolerance:
                hits.append((abs(img_x - x2), {"kind": "strip_boundary", "strip_index": strip_index, "side": "right"}))

            if x1 - tolerance <= img_x <= x2 + tolerance:
                cuts = self.layout["strip_infos"][strip_index]["cuts"]
                for cut_index in range(1, len(cuts) - 1):
                    y = cuts[cut_index]
                    if abs(img_y - y) <= tolerance:
                        hits.append((abs(img_y - y), {"kind": "cut_line", "strip_index": strip_index, "cut_index": cut_index}))

        if not hits:
            return None
        hits.sort(key=lambda item: item[0])
        return hits[0][1]

    def on_canvas_motion(self, event):
        if self.drag_mode == "pan":
            self.canvas.configure(cursor="fleur")
            return
        guide = self.hit_test_guide(event)
        if not guide:
            self.canvas.configure(cursor="arrow")
        elif guide["kind"] == "box_move":
            self.canvas.configure(cursor="fleur")
        elif guide["kind"] == "box_edge":
            self.canvas.configure(cursor="sb_h_double_arrow" if guide["edge"] in {"left", "right"} else "sb_v_double_arrow")
        elif guide["kind"] == "cut_line":
            self.canvas.configure(cursor="sb_v_double_arrow")
        else:
            self.canvas.configure(cursor="sb_h_double_arrow")

    def on_left_press(self, event):
        if self.preview_base_bgr is None:
            return

        guide = self.hit_test_guide(event)
        self.drag_changed = False
        self.edit_started = False
        if guide is not None:
            if guide["kind"] == "box_move":
                img_x, img_y = self.screen_to_image(event.x, event.y)
                box = self.layout["boxes"][guide["box_index"]]
                guide = dict(guide)
                guide["offset_x"] = img_x - box[0]
                guide["offset_y"] = img_y - box[1]
            self.drag_mode = guide["kind"]
            self.drag_payload = guide
            self.dragging_guides = True
            self.canvas.configure(cursor="crosshair")
        else:
            self.drag_mode = "pan"
            self.drag_payload = None
            self.canvas.scan_mark(event.x, event.y)
            self.canvas.configure(cursor="fleur")

    def apply_guide_drag(self, event):
        if not self.layout or not self.drag_payload:
            return False

        img_h, img_w = self.layout["oriented_image"].shape[:2]
        img_x, img_y = self.screen_to_image(event.x, event.y)
        changed = False
        min_box_size = 20

        if self.drag_payload["kind"] == "box_move":
            box_index = self.drag_payload["box_index"]
            x1, y1, x2, y2 = self.layout["boxes"][box_index]
            box_w = x2 - x1
            box_h = y2 - y1
            new_x1 = clamp(int(round(img_x - self.drag_payload.get("offset_x", 0.0))), 0, max(0, img_w - box_w))
            new_y1 = clamp(int(round(img_y - self.drag_payload.get("offset_y", 0.0))), 0, max(0, img_h - box_h))
            new_box = (new_x1, new_y1, new_x1 + box_w, new_y1 + box_h)
            if new_box != self.layout["boxes"][box_index]:
                self.layout["boxes"][box_index] = new_box
                changed = True

        elif self.drag_payload["kind"] == "box_edge":
            box_index = self.drag_payload["box_index"]
            edge = self.drag_payload["edge"]
            x1, y1, x2, y2 = self.layout["boxes"][box_index]
            if edge == "left":
                new_x1 = clamp(int(round(img_x)), 0, x2 - min_box_size)
                new_box = (new_x1, y1, x2, y2)
            elif edge == "right":
                new_x2 = clamp(int(round(img_x)), x1 + min_box_size, img_w)
                new_box = (x1, y1, new_x2, y2)
            elif edge == "top":
                new_y1 = clamp(int(round(img_y)), 0, y2 - min_box_size)
                new_box = (x1, new_y1, x2, y2)
            else:
                new_y2 = clamp(int(round(img_y)), y1 + min_box_size, img_h)
                new_box = (x1, y1, x2, new_y2)
            if new_box != self.layout["boxes"][box_index]:
                self.layout["boxes"][box_index] = new_box
                changed = True

        elif self.drag_payload["kind"] == "cut_line":
            strip_index = self.drag_payload["strip_index"]
            cut_index = self.drag_payload["cut_index"]
            cuts = self.layout["strip_infos"][strip_index]["cuts"]
            if 0 < cut_index < len(cuts) - 1:
                min_gap = max(MIN_FRAME_HEIGHT, int(img_h * 0.015))
                lower = cuts[cut_index - 1] + min_gap
                upper = cuts[cut_index + 1] - min_gap
                if lower <= upper:
                    new_y = clamp(int(round(img_y)), lower, upper)
                    if new_y != cuts[cut_index]:
                        cuts[cut_index] = new_y
                        changed = True

        elif self.drag_payload["kind"] == "strip_boundary":
            strip_index = self.drag_payload["strip_index"]
            side = self.drag_payload["side"]
            strips = list(self.layout["strips"])
            x1, x2 = strips[strip_index]
            min_width = max(MIN_STRIP_WIDTH, int(img_w * 0.02))

            if side == "left":
                lower = 0 if strip_index == 0 else self.layout["strips"][strip_index - 1][1] + 2
                upper = x2 - min_width
                new_x = clamp(int(round(img_x)), lower, upper)
                if new_x != x1:
                    strips[strip_index] = (new_x, x2)
                    changed = True
            else:
                lower = x1 + min_width
                upper = img_w - 1 if strip_index >= len(strips) - 1 else self.layout["strips"][strip_index + 1][0] - 2
                new_x = clamp(int(round(img_x)), lower, upper)
                if new_x != x2:
                    strips[strip_index] = (x1, new_x)
                    changed = True

            if changed:
                self.layout["strips"] = strips
                self.layout["strip_infos"][strip_index]["x_range"] = strips[strip_index]

        return changed

    def on_left_drag(self, event):
        if self.drag_mode == "pan":
            self.canvas.scan_dragto(event.x, event.y, gain=1)
            self.schedule_redraw()
        elif self.drag_mode in {"cut_line", "strip_boundary", "box_edge", "box_move"}:
            if self.apply_guide_drag(event):
                if not self.edit_started and self.on_edit_started is not None:
                    self.on_edit_started()
                    self.edit_started = True
                self.drag_changed = True
                self.schedule_redraw()

    def on_left_release(self, event):
        if self.drag_mode in {"cut_line", "strip_boundary", "box_edge", "box_move"} and self.layout is not None:
            if self.drag_changed and not self.layout.get("box_mode"):
                rebuild_boxes_from_guides(self.layout, bg_thresh=self.last_bg_thresh, crop_pad=self.last_crop_pad)
            self.dragging_guides = False
            if self.drag_changed:
                if self.on_manual_adjust_done is not None:
                    self.on_manual_adjust_done(self.layout)
                self.redraw()
            else:
                self.schedule_redraw()
        elif self.drag_mode == "pan":
            self.canvas.configure(cursor="arrow")

        self.drag_mode = None
        self.drag_payload = None
        self.dragging_guides = False
        self.drag_changed = False
        self.edit_started = False
        self.on_canvas_motion(event)

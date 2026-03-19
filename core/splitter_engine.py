from __future__ import annotations

from pathlib import Path

import cv2
import math
import numpy as np
from PIL import Image

from core.constants import (
    DEFAULT_BG_THRESH,
    DEFAULT_CROP_PAD,
    DEFAULT_JPEG_QUALITY,
    DEFAULT_PNG_COMPRESS_LEVEL,
    DEFAULT_TIFF_COMPRESSION,
    EXPORTABLE_ORIGINAL_EXTS,
    MAX_ANALYSIS_DIM,
    MIN_FRAME_HEIGHT,
    MIN_STRIP_WIDTH,
)
from core.image_loader import downscale_image, normalize_to_uint8, rotate_image, to_gray8
from core.utils import clamp
def smooth_1d(arr, sigma: float):
    data = np.asarray(arr, dtype=np.float32)
    if data.size <= 1:
        return data
    sigma = max(0.8, float(sigma))
    radius = max(1, int(math.ceil(sigma * 3.0)))
    x = np.arange(-radius, radius + 1, dtype=np.float32)
    kernel = np.exp(-(x * x) / (2.0 * sigma * sigma))
    kernel /= kernel.sum()
    return np.convolve(data, kernel, mode="same")


def normalize_signal(arr: np.ndarray) -> np.ndarray:
    data = np.asarray(arr, dtype=np.float32)
    if data.size == 0:
        return data
    low = float(data.min())
    high = float(data.max())
    if high <= low:
        return np.zeros_like(data, dtype=np.float32)
    return (data - low) / (high - low + 1e-6)


def contiguous_ranges(mask: np.ndarray, merge_gap: int = 5):
    ranges = []
    start = None
    for idx, value in enumerate(mask.astype(bool)):
        if value and start is None:
            start = idx
        elif not value and start is not None:
            ranges.append((start, idx - 1))
            start = None
    if start is not None:
        ranges.append((start, len(mask) - 1))

    merged = []
    for a, b in ranges:
        if merged and a - merged[-1][1] <= merge_gap:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    return merged


def find_peaks_simple(signal: np.ndarray, distance: int = 1, prominence: float = 0.0) -> np.ndarray:
    data = np.asarray(signal, dtype=np.float32)
    if data.size < 3:
        return np.empty((0,), dtype=np.int32)

    candidates = np.where((data[1:-1] > data[:-2]) & (data[1:-1] >= data[2:]))[0] + 1
    if candidates.size == 0:
        return np.empty((0,), dtype=np.int32)

    if prominence > 0.0:
        kept = []
        span = max(1, int(distance))
        for idx in candidates.tolist():
            left = data[max(0, idx - span): idx + 1]
            right = data[idx: min(data.size, idx + span + 1)]
            left_min = float(np.min(left)) if left.size else float(data[idx])
            right_min = float(np.min(right)) if right.size else float(data[idx])
            base = max(left_min, right_min)
            if float(data[idx] - base) >= prominence:
                kept.append(idx)
        candidates = np.asarray(kept, dtype=np.int32)

    if candidates.size == 0 or distance <= 1:
        return candidates.astype(np.int32)

    order = candidates[np.argsort(data[candidates])[::-1]]
    selected = []
    for idx in order.tolist():
        if all(abs(idx - existing) >= distance for existing in selected):
            selected.append(idx)
    return np.asarray(sorted(selected), dtype=np.int32)


def foreground_bounds(strip_gray: np.ndarray, bg_thresh: int = DEFAULT_BG_THRESH):
    occ = smooth_1d((strip_gray > bg_thresh).mean(axis=1), sigma=2.0)
    idx = np.where(occ > 0.20)[0]
    if idx.size == 0:
        return 0, strip_gray.shape[0]
    return int(idx[0]), int(idx[-1]) + 1


def separator_score(strip_gray: np.ndarray):
    if strip_gray.size == 0:
        return np.zeros((0,), dtype=np.float32)

    p92 = normalize_signal(smooth_1d(np.percentile(strip_gray, 92, axis=1), sigma=2.0))
    p80_value = float(np.percentile(strip_gray, 80))
    bright = normalize_signal(smooth_1d((strip_gray > p80_value).mean(axis=1), sigma=2.0))
    gy = cv2.Sobel(strip_gray, cv2.CV_32F, 0, 1, ksize=3)
    gy = normalize_signal(smooth_1d(np.mean(np.abs(gy), axis=1), sigma=2.0))
    var = normalize_signal(smooth_1d(np.std(strip_gray.astype(np.float32), axis=1), sigma=2.0))
    return (0.45 * p92 + 0.25 * bright + 0.25 * gy + 0.05 * (1.0 - var)).astype(np.float32)


def estimate_frames_for_strip(strip_gray: np.ndarray, bg_thresh: int = DEFAULT_BG_THRESH):
    top, bottom = foreground_bounds(strip_gray, bg_thresh)
    if bottom - top < MIN_FRAME_HEIGHT * 2:
        return 1, [top, bottom]

    core = strip_gray[top:bottom]
    score = separator_score(core)
    min_dist = max(24, int(strip_gray.shape[1] * 0.65))
    peaks = find_peaks_simple(score, distance=min_dist, prominence=0.08)
    peaks = peaks[(peaks > 0.08 * core.shape[0]) & (peaks < 0.92 * core.shape[0])]
    return max(1, int(peaks.size + 1)), [top] + [int(p + top) for p in peaks.tolist()] + [bottom]


def normalize_cut_positions(cuts, low: int, high: int, min_gap: int):
    low = int(low)
    high = int(high)
    if high <= low:
        return [low, high]

    inner = sorted(int(round(c)) for c in cuts[1:-1])
    result = [low]
    remaining = len(inner)
    for idx, cut in enumerate(inner):
        min_allowed = result[-1] + min_gap
        max_allowed = high - min_gap * (remaining - idx)
        if max_allowed < min_allowed:
            max_allowed = min_allowed
        result.append(clamp(cut, min_allowed, max_allowed))
    result.append(high)
    return result


def refine_cuts_with_frame_count(strip_gray: np.ndarray, frame_count: int, bg_thresh: int = DEFAULT_BG_THRESH):
    h = strip_gray.shape[0]
    top, bottom = foreground_bounds(strip_gray, bg_thresh)
    if bottom - top < MIN_FRAME_HEIGHT or frame_count <= 1:
        return [top, bottom]

    core = strip_gray[top:bottom]
    score = separator_score(core)
    expected = max(1.0, core.shape[0] / max(1, frame_count))
    search_radius = int(max(18, min(120, expected * 0.28)))

    cuts = [top]
    for index in range(1, frame_count):
        center = int(round(top + index * expected))
        a = max(top, center - search_radius)
        b = min(bottom - 1, center + search_radius)
        local = score[(a - top):(b - top + 1)]
        y = a + int(np.argmax(local)) if local.size else center
        cuts.append(y)
    cuts.append(bottom)

    normalized = normalize_cut_positions(cuts, top, bottom, min_gap=int(max(MIN_FRAME_HEIGHT, expected * 0.45)))
    if normalized[-1] <= normalized[0]:
        return [0, h]
    return normalized


def refine_cuts_with_seed(strip_gray: np.ndarray, seed_cuts, bg_thresh: int = DEFAULT_BG_THRESH):
    h = strip_gray.shape[0]
    if len(seed_cuts) < 2:
        return [0, h]

    top, bottom = foreground_bounds(strip_gray, bg_thresh)
    if bottom - top < MIN_FRAME_HEIGHT:
        return [top, bottom]

    core = strip_gray[top:bottom]
    score = separator_score(core)
    avg_gap = max(1.0, float(seed_cuts[-1] - seed_cuts[0]) / max(1, len(seed_cuts) - 1))
    search_radius = int(max(18, min(120, avg_gap * 0.25)))

    cuts = [top]
    for seed in seed_cuts[1:-1]:
        target = clamp(int(round(seed)), top + 1, bottom - 1)
        a = max(top, target - search_radius)
        b = min(bottom - 1, target + search_radius)
        local = score[(a - top):(b - top + 1)]
        y = a + int(np.argmax(local)) if local.size else target
        cuts.append(y)
    cuts.append(bottom)

    normalized = normalize_cut_positions(
        cuts,
        top,
        bottom,
        min_gap=int(max(MIN_FRAME_HEIGHT, ((bottom - top) / max(1, len(seed_cuts) - 1)) * 0.4)),
    )
    if normalized[-1] <= normalized[0]:
        return [0, h]
    return normalized


def trim_bbox(frame_gray: np.ndarray, bg_thresh: int = DEFAULT_BG_THRESH, pad: int = DEFAULT_CROP_PAD):
    mask = frame_gray > bg_thresh
    ys = np.where(mask.mean(axis=1) > 0.05)[0]
    xs = np.where(mask.mean(axis=0) > 0.05)[0]
    if xs.size == 0 or ys.size == 0:
        return 0, 0, frame_gray.shape[1], frame_gray.shape[0]
    x1 = max(0, int(xs[0]) - pad)
    x2 = min(frame_gray.shape[1], int(xs[-1]) + 1 + pad)
    y1 = max(0, int(ys[0]) - pad)
    y2 = min(frame_gray.shape[0], int(ys[-1]) + 1 + pad)
    return x1, y1, x2, y2


def distribute_frames(total_frames: int, strip_count: int):
    if strip_count <= 0:
        return []
    if total_frames <= 0:
        return [0] * strip_count
    base = total_frames // strip_count
    rem = total_frames % strip_count
    return [base + (1 if idx < rem else 0) for idx in range(strip_count)]


def scale_range_to_full(rng, scale: float, limit: int):
    if scale >= 0.999:
        return int(rng[0]), int(rng[1])
    x1 = int(math.floor(rng[0] / scale))
    x2 = int(math.ceil((rng[1] + 1) / scale)) - 1
    x1 = clamp(x1, 0, max(0, limit - 2))
    x2 = clamp(x2, x1 + 1, max(1, limit - 1))
    return x1, x2


def scale_positions_to_full(values, scale: float, limit: int):
    if scale >= 0.999:
        return [clamp(int(v), 0, limit) for v in values]
    return [clamp(int(round(float(v) / scale)), 0, limit) for v in values]


def detect_strips(gray: np.ndarray, bg_thresh: int = DEFAULT_BG_THRESH, orientation_mode: str = "auto"):
    options = [0, 90] if orientation_mode == "auto" else ([0] if orientation_mode == "vertical" else [90])
    candidates = []

    for rotation in options:
        oriented = gray if rotation == 0 else cv2.rotate(gray, cv2.ROTATE_90_CLOCKWISE)
        mask = oriented > bg_thresh
        col_occ = smooth_1d(mask.mean(axis=0), sigma=max(1.2, oriented.shape[1] / 280.0))
        max_occ = float(col_occ.max()) if col_occ.size else 0.0
        threshold = max(0.04, min(0.55, max_occ * 0.34))

        raw_ranges = contiguous_ranges(col_occ > threshold, merge_gap=max(6, oriented.shape[1] // 160))
        good = []
        covers = []
        width_fracs = []
        aspects = []
        min_width = max(MIN_STRIP_WIDTH, int(oriented.shape[1] * 0.04))

        for a, b in raw_ranges:
            width = b - a + 1
            if width < min_width:
                continue
            strip_mask = mask[:, a:b + 1]
            row_occ = smooth_1d(strip_mask.mean(axis=1), sigma=max(1.0, oriented.shape[0] / 260.0))
            idx = np.where(row_occ > 0.12)[0]
            if idx.size == 0:
                continue
            cover = float((idx[-1] - idx[0] + 1) / oriented.shape[0])
            width_frac = float(width / oriented.shape[1])
            aspect = float((cover * oriented.shape[0]) / max(1, width))
            if cover < 0.35:
                continue
            good.append((int(a), int(b)))
            covers.append(cover)
            width_fracs.append(width_frac)
            aspects.append(aspect)

        widths = sorted([(b - a + 1) for a, b in good], reverse=True)
        score = float(sum(widths[:4]))
        strip_count = len(good)

        if strip_count == 2:
            score += 1200.0
        elif strip_count == 3:
            score += 1000.0
        elif strip_count == 1:
            score -= 1600.0
        else:
            score -= 350.0 * abs(strip_count - 2)

        mean_cover = float(np.mean(covers)) if covers else 0.0
        mean_aspect = float(np.mean(aspects)) if aspects else 0.0
        if widths:
            width_array = np.asarray(widths, dtype=np.float32)
            uniformity = 1.0 - min(1.0, float(np.std(width_array) / (np.mean(width_array) + 1e-6)))
            oversize_penalty = float(sum(max(0.0, frac - 0.55) for frac in width_fracs))
            score += 900.0 * mean_cover
            score += 220.0 * uniformity
            score += 250.0 * min(mean_aspect, 4.0)
            score -= 1900.0 * oversize_penalty

        separation = float(np.percentile(col_occ, 95) - np.percentile(col_occ, 50)) if col_occ.size else 0.0
        score += 700.0 * separation

        candidates.append(
            {
                "rotation": rotation,
                "score": score,
                "image": oriented,
                "strips": good,
                "threshold": threshold,
                "mean_cover": mean_cover,
                "mean_aspect": mean_aspect,
                "profile": col_occ,
            }
        )

    candidates.sort(key=lambda item: item["score"], reverse=True)
    best = candidates[0]
    diagnostics = {
        "orientation": best["rotation"],
        "score": best["score"],
        "profile_threshold": best["threshold"],
        "profile": best["profile"],
        "candidates": [
            {
                "rotation": item["rotation"],
                "score": float(item["score"]),
                "strip_count": len(item["strips"]),
                "mean_cover": float(item["mean_cover"]),
                "mean_aspect": float(item["mean_aspect"]),
            }
            for item in candidates
        ],
    }
    return best["image"], best["strips"], best["rotation"], diagnostics


def sanitize_cuts(cuts, limit: int):
    cleaned = sorted(set(clamp(int(round(c)), 0, limit) for c in cuts))
    if len(cleaned) < 2:
        return [0, limit]

    result = [cleaned[0]]
    for cut in cleaned[1:-1]:
        if cut - result[-1] >= MIN_FRAME_HEIGHT:
            result.append(cut)
    if cleaned[-1] - result[-1] < MIN_FRAME_HEIGHT and len(result) > 1:
        result.pop()
    result.append(cleaned[-1])

    if result[-1] <= result[0]:
        return [0, limit]
    return result


def rebuild_boxes_from_guides(layout: dict, bg_thresh: int = DEFAULT_BG_THRESH, crop_pad: int = DEFAULT_CROP_PAD):
    oriented_gray = to_gray8(layout["oriented_image"])
    img_h, img_w = oriented_gray.shape[:2]
    boxes = []
    new_infos = []

    for index, strip in enumerate(layout["strips"]):
        x1 = clamp(int(round(strip[0])), 0, max(0, img_w - 2))
        x2 = clamp(int(round(strip[1])), x1 + 1, max(1, img_w - 1))
        strip_gray = oriented_gray[:, x1:x2 + 1]
        current_info = layout["strip_infos"][index] if index < len(layout["strip_infos"]) else {}
        cuts = sanitize_cuts(current_info.get("cuts", [0, img_h]), img_h)

        local_count = 0
        for cut_index in range(len(cuts) - 1):
            y1 = int(cuts[cut_index])
            y2 = int(cuts[cut_index + 1])
            if y2 - y1 < MIN_FRAME_HEIGHT:
                continue
            patch_gray = strip_gray[y1:y2, :]
            tx1, ty1, tx2, ty2 = trim_bbox(patch_gray, bg_thresh=bg_thresh, pad=crop_pad)
            bx1 = int(x1 + tx1)
            by1 = int(y1 + ty1)
            bx2 = int(x1 + tx2)
            by2 = int(y1 + ty2)
            if bx2 - bx1 < 20 or by2 - by1 < 20:
                continue
            boxes.append((bx1, by1, bx2, by2))
            local_count += 1

        new_infos.append(
            {
                "strip_index": index,
                "x_range": (x1, x2),
                "cuts": cuts,
                "frame_count": local_count,
            }
        )

    layout["strips"] = [info["x_range"] for info in new_infos]
    layout["strip_infos"] = new_infos
    layout["boxes"] = boxes
    return layout


def detect_layout(
    img_bgr: np.ndarray,
    bg_thresh: int = DEFAULT_BG_THRESH,
    orientation_mode: str = "auto",
    total_frames: int = 0,
    manual_strips: int = 0,
    crop_pad: int = DEFAULT_CROP_PAD,
    analysis_bgr: np.ndarray | None = None,
    analysis_gray: np.ndarray | None = None,
    analysis_scale: float | None = None,
):
    if analysis_bgr is None or analysis_scale is None:
        analysis_bgr, analysis_scale = downscale_image(img_bgr, MAX_ANALYSIS_DIM)
    if analysis_gray is None:
        analysis_gray = to_gray8(analysis_bgr)
    oriented_small_gray, strips_small, used_rotation, diagnostics = detect_strips(
        analysis_gray,
        bg_thresh=bg_thresh,
        orientation_mode=orientation_mode,
    )

    if manual_strips > 0 and len(strips_small) > manual_strips:
        strips_small = sorted(strips_small, key=lambda item: (item[1] - item[0] + 1), reverse=True)[:manual_strips]
        strips_small = sorted(strips_small, key=lambda item: item[0])

    if not strips_small:
        raise RuntimeError("No strips were detected. Try increasing the background threshold or rotating the image first.")

    oriented_bgr = rotate_image(img_bgr, used_rotation)
    oriented_gray = to_gray8(oriented_bgr)

    strip_infos = []
    strips_full = []
    per_strip_counts = distribute_frames(total_frames, len(strips_small)) if total_frames > 0 else [0] * len(strips_small)

    for index, small_strip in enumerate(strips_small):
        sx1, sx2 = small_strip
        strip_small_gray = oriented_small_gray[:, sx1:sx2 + 1]

        x1, x2 = scale_range_to_full(small_strip, analysis_scale, oriented_bgr.shape[1])
        strip_full_gray = oriented_gray[:, x1:x2 + 1]

        expected_frames = per_strip_counts[index]
        if expected_frames > 0:
            cuts = refine_cuts_with_frame_count(strip_full_gray, expected_frames, bg_thresh=bg_thresh)
        else:
            estimated_frames, rough_small_cuts = estimate_frames_for_strip(strip_small_gray, bg_thresh=bg_thresh)
            rough_full_cuts = scale_positions_to_full(rough_small_cuts, analysis_scale, strip_full_gray.shape[0])
            cuts = refine_cuts_with_seed(strip_full_gray, rough_full_cuts, bg_thresh=bg_thresh)
            if len(cuts) < 2 or len(cuts) != len(rough_small_cuts):
                cuts = refine_cuts_with_frame_count(strip_full_gray, estimated_frames, bg_thresh=bg_thresh)

        strips_full.append((x1, x2))
        strip_infos.append(
            {
                "strip_index": index,
                "x_range": (x1, x2),
                "cuts": cuts,
                "frame_count": max(0, len(cuts) - 1),
            }
        )

    diagnostics["analysis_scale"] = float(analysis_scale)
    diagnostics["analysis_size"] = (int(analysis_bgr.shape[1]), int(analysis_bgr.shape[0]))

    layout = {
        "oriented_image": oriented_bgr,
        "used_rotation": used_rotation,
        "strips": strips_full,
        "boxes": [],
        "strip_infos": strip_infos,
        "diagnostics": diagnostics,
    }
    return rebuild_boxes_from_guides(layout, bg_thresh=bg_thresh, crop_pad=crop_pad)


def save_crops(
    layout: dict,
    src_path: str,
    out_dir: str,
    fmt: str = "original",
    jpeg_quality: int = DEFAULT_JPEG_QUALITY,
    png_compress_level: int = DEFAULT_PNG_COMPRESS_LEVEL,
    tiff_compression: str = DEFAULT_TIFF_COMPRESSION,
    progress_callback=None,
):
    src = Path(src_path)
    out_root = Path(out_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    if fmt == "original":
        ext = src.suffix.lower() if src.suffix.lower() in EXPORTABLE_ORIGINAL_EXTS else ".png"
    elif fmt == "jpg":
        ext = ".jpg"
    elif fmt == "png":
        ext = ".png"
    elif fmt == "tiff":
        ext = ".tif"
    else:
        ext = ".png"

    rgb_full = cv2.cvtColor(normalize_to_uint8(layout["oriented_image"]), cv2.COLOR_BGR2RGB)
    total = 0
    total_boxes = max(0, len(layout["boxes"]))
    for index, (x1, y1, x2, y2) in enumerate(layout["boxes"], start=1):
        crop = rgb_full[y1:y2, x1:x2]
        if crop.size == 0:
            if progress_callback is not None:
                progress_callback(index, total_boxes)
            continue
        image = Image.fromarray(crop)
        file_path = out_root / f"{src.stem}_{index:02d}{ext}"
        save_kwargs = {}
        if ext in {".jpg", ".jpeg"}:
            save_kwargs["quality"] = clamp(int(jpeg_quality), 50, 100)
            save_kwargs["subsampling"] = 0
        elif ext == ".png":
            save_kwargs["compress_level"] = clamp(int(png_compress_level), 0, 9)
        elif ext in {".tif", ".tiff"} and tiff_compression:
            save_kwargs["compression"] = tiff_compression
        image.save(file_path, **save_kwargs)
        total += 1
        if progress_callback is not None:
            progress_callback(index, total_boxes)
    return total


def snapshot_guides(layout: dict):
    return {
        "strips": [tuple(map(int, strip)) for strip in layout["strips"]],
        "cuts": [[int(cut) for cut in info["cuts"]] for info in layout["strip_infos"]],
    }


def clone_guides_snapshot(snapshot):
    if not snapshot:
        return None
    return {
        "strips": [tuple(map(int, strip)) for strip in snapshot["strips"]],
        "cuts": [[int(cut) for cut in cuts] for cuts in snapshot["cuts"]],
    }


def rotate_box(box, width: int, height: int, deg: int):
    x1, y1, x2, y2 = map(int, box)
    deg = deg % 360
    if deg == 0:
        return x1, y1, x2, y2
    if deg == 90:
        return height - y2, x1, height - y1, x2
    if deg == 180:
        return width - x2, height - y2, width - x1, height - y1
    if deg == 270:
        return y1, width - x2, y2, width - x1
    raise ValueError("rotation must be one of 0/90/180/270")


def interval_overlap(a1: int, a2: int, b1: int, b2: int) -> int:
    return max(0, min(a2, b2) - max(a1, b1))


def transform_snapshot_and_boxes(snapshot, boxes, width: int, height: int, deg: int):
    if not snapshot:
        return None, None

    strips = snapshot.get("strips", [])
    cut_sets = snapshot.get("cuts", [])
    expected_boxes = sum(max(0, len(cuts) - 1) for cuts in cut_sets)
    usable_boxes = boxes if boxes and len(boxes) == expected_boxes else None

    slots = []
    box_index = 0
    for strip_index, strip in enumerate(strips):
        if strip_index >= len(cut_sets):
            break
        x1, x2 = map(int, strip)
        cuts = [int(cut) for cut in cut_sets[strip_index]]
        for frame_index in range(max(0, len(cuts) - 1)):
            y1 = cuts[frame_index]
            y2 = cuts[frame_index + 1]
            full_rect = (x1, y1, x2 + 1, y2)
            rotated_full_rect = rotate_box(full_rect, width, height, deg)
            rotated_trim_box = None
            if usable_boxes is not None:
                rotated_trim_box = rotate_box(usable_boxes[box_index], width, height, deg)
            slots.append(
                {
                    "frame_rect": rotated_full_rect,
                    "trim_box": rotated_trim_box,
                }
            )
            box_index += 1

    if not slots:
        return None, None

    slots.sort(key=lambda item: (((item["frame_rect"][0] + item["frame_rect"][2]) * 0.5), item["frame_rect"][1]))
    groups = []
    for slot in slots:
        x1, _, x2, _ = slot["frame_rect"]
        center = (x1 + x2) * 0.5
        width_now = max(1, x2 - x1)
        best_group = None
        best_score = None

        for group in groups:
            overlap = interval_overlap(x1, x2, group["x1"], group["x2"])
            overlap_ratio = overlap / float(max(1, min(width_now, group["width"])))
            center_gap = abs(center - group["center"])
            center_limit = max(6.0, min(width_now, group["width"]) * 0.22)
            if overlap_ratio < 0.18 and center_gap > center_limit:
                continue
            score = overlap_ratio - (center_gap / float(max(width_now, group["width"], 1)))
            if best_score is None or score > best_score:
                best_group = group
                best_score = score

        if best_group is None:
            groups.append(
                {
                    "x1": x1,
                    "x2": x2,
                    "center": center,
                    "width": float(width_now),
                    "slots": [slot],
                }
            )
            continue

        best_group["x1"] = min(best_group["x1"], x1)
        best_group["x2"] = max(best_group["x2"], x2)
        best_group["slots"].append(slot)
        best_group["center"] = sum((item["frame_rect"][0] + item["frame_rect"][2]) * 0.5 for item in best_group["slots"]) / len(best_group["slots"])
        best_group["width"] = max(1.0, best_group["x2"] - best_group["x1"])

    if not groups:
        return None, None

    groups.sort(key=lambda item: item["x1"])
    if deg == 90:
        groups.reverse()

    new_strips = []
    new_cuts = []
    ordered_boxes = []
    for group in groups:
        ordered_slots = sorted(group["slots"], key=lambda item: (item["frame_rect"][1], item["frame_rect"][0]))
        strip_x1 = min(item["frame_rect"][0] for item in ordered_slots)
        strip_x2 = max(item["frame_rect"][2] for item in ordered_slots) - 1
        cuts = [ordered_slots[0]["frame_rect"][1]]
        for prev_item, next_item in zip(ordered_slots, ordered_slots[1:]):
            cuts.append(int(round((prev_item["frame_rect"][3] + next_item["frame_rect"][1]) / 2.0)))
        cuts.append(ordered_slots[-1]["frame_rect"][3])
        new_strips.append((strip_x1, strip_x2))
        new_cuts.append(cuts)
        for item in ordered_slots:
            if item["trim_box"] is not None:
                ordered_boxes.append(item["trim_box"])

    return {
        "strips": new_strips,
        "cuts": [sanitize_cuts(cuts, width if deg in {90, 270} else height) for cuts in new_cuts],
    }, ordered_boxes if len(ordered_boxes) == expected_boxes else None


def build_layout_from_snapshot(
    oriented_bgr: np.ndarray,
    used_rotation: int,
    snapshot,
    boxes=None,
    bg_thresh: int = DEFAULT_BG_THRESH,
    crop_pad: int = DEFAULT_CROP_PAD,
    diagnostics=None,
):
    if oriented_bgr is None or not snapshot:
        return None

    img_h, img_w = oriented_bgr.shape[:2]
    strips = []
    strip_infos = []
    cut_sets = snapshot.get("cuts", [])
    for index, strip in enumerate(snapshot.get("strips", [])):
        if index >= len(cut_sets):
            break
        x1 = clamp(int(strip[0]), 0, max(0, img_w - 2))
        x2 = clamp(int(strip[1]), x1 + 1, max(1, img_w - 1))
        cuts = sanitize_cuts(cut_sets[index], img_h)
        strips.append((x1, x2))
        strip_infos.append(
            {
                "strip_index": index,
                "x_range": (x1, x2),
                "cuts": cuts,
                "frame_count": max(0, len(cuts) - 1),
            }
        )

    if not strips:
        return None

    layout = {
        "oriented_image": oriented_bgr,
        "used_rotation": int(used_rotation) % 360,
        "strips": strips,
        "boxes": [],
        "strip_infos": strip_infos,
        "diagnostics": diagnostics or {},
    }
    if boxes:
        img_h, img_w = oriented_bgr.shape[:2]
        normalized_boxes = []
        for box in boxes:
            if len(box) != 4:
                continue
            x1 = clamp(int(box[0]), 0, max(0, img_w - 1))
            y1 = clamp(int(box[1]), 0, max(0, img_h - 1))
            x2 = clamp(int(box[2]), x1 + 1, img_w)
            y2 = clamp(int(box[3]), y1 + 1, img_h)
            normalized_boxes.append((x1, y1, x2, y2))
        if normalized_boxes:
            layout["boxes"] = normalized_boxes
            return layout
    return rebuild_boxes_from_guides(layout, bg_thresh=bg_thresh, crop_pad=crop_pad)


def rotate_layout_preserving_split(layout: dict, deg: int):
    if not layout:
        return None

    deg = deg % 360
    if deg == 0:
        return layout

    old_image = layout["oriented_image"]
    old_h, old_w = old_image.shape[:2]
    rotated_image = rotate_image(old_image, deg)
    rotated_snapshot, rotated_boxes = transform_snapshot_and_boxes(
        snapshot_guides(layout),
        layout.get("boxes", []),
        old_w,
        old_h,
        deg,
    )
    if not rotated_snapshot:
        return None
    return build_layout_from_snapshot(
        rotated_image,
        int(layout.get("used_rotation", 0)) % 360,
        rotated_snapshot,
        boxes=rotated_boxes,
        diagnostics=dict(layout.get("diagnostics", {})),
    )


def build_box_only_layout(oriented_bgr: np.ndarray, used_rotation: int, boxes, diagnostics=None):
    if oriented_bgr is None:
        return None

    img_h, img_w = oriented_bgr.shape[:2]
    normalized_boxes = []
    for box in boxes or []:
        if len(box) != 4:
            continue
        x1 = clamp(int(box[0]), 0, max(0, img_w - 1))
        y1 = clamp(int(box[1]), 0, max(0, img_h - 1))
        x2 = clamp(int(box[2]), x1 + 1, img_w)
        y2 = clamp(int(box[3]), y1 + 1, img_h)
        normalized_boxes.append((x1, y1, x2, y2))

    return {
        "oriented_image": oriented_bgr,
        "used_rotation": int(used_rotation) % 360,
        "strips": [],
        "boxes": normalized_boxes,
        "strip_infos": [],
        "diagnostics": diagnostics or {},
        "box_mode": True,
    }




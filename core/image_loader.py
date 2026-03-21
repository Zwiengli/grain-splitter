from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from core.constants import MAX_PREVIEW_BASE_DIM

Image.MAX_IMAGE_PIXELS = None

try:
    import tifffile
except Exception:
    tifffile = None


TIFF_LIKE_EXTS = {".tif", ".tiff", ".fff"}


def normalize_to_uint8(arr: np.ndarray) -> np.ndarray:
    arr = np.asarray(arr)
    if arr.dtype == np.uint8:
        return arr
    if arr.dtype == np.bool_:
        return arr.astype(np.uint8) * 255

    data = arr.astype(np.float32, copy=False)
    if not np.isfinite(data).all():
        data = np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0)

    data_min = float(data.min()) if data.size else 0.0
    data_max = float(data.max()) if data.size else 0.0
    if data_max <= data_min:
        return np.zeros(arr.shape, dtype=np.uint8)

    scaled = (data - data_min) * (255.0 / (data_max - data_min))
    return np.clip(scaled, 0, 255).astype(np.uint8)


def array_to_bgr(arr: np.ndarray, assume_rgb: bool = True) -> np.ndarray:
    arr = np.asarray(arr)
    while arr.ndim > 3:
        arr = arr[0]

    if arr.ndim == 2:
        gray = normalize_to_uint8(arr)
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    if arr.ndim != 3:
        raise RuntimeError(f"涓嶆敮鎸佺殑鏁扮粍缁村害: {arr.ndim}")

    if arr.shape[0] in {3, 4} and arr.shape[2] not in {3, 4}:
        arr = np.moveaxis(arr, 0, -1)

    if arr.shape[2] == 1:
        gray = normalize_to_uint8(arr[:, :, 0])
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    arr = arr[:, :, :3]
    arr = normalize_to_uint8(arr)
    if assume_rgb:
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    return arr


def read_with_cv2(path: str) -> np.ndarray:
    data = np.fromfile(path, dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise RuntimeError("OpenCV failed to decode the image file")

    if img.ndim == 2:
        return cv2.cvtColor(normalize_to_uint8(img), cv2.COLOR_GRAY2BGR)

    if img.ndim != 3:
        raise RuntimeError("OpenCV failed to decode the image file")

    if img.shape[2] == 4:
        img = cv2.cvtColor(normalize_to_uint8(img), cv2.COLOR_BGRA2BGR)
    else:
        img = normalize_to_uint8(img[:, :, :3])
    return img


def read_with_tifffile(path: str) -> np.ndarray:
    if tifffile is None:
        raise RuntimeError("tifffile is not installed")
    arr = tifffile.imread(path)
    return array_to_bgr(arr, assume_rgb=True)


def choose_reader(path: str):
    suffix = Path(path).suffix.lower()
    if suffix in TIFF_LIKE_EXTS and tifffile is not None:
        return "tifffile", read_with_tifffile
    return "OpenCV", read_with_cv2


def load_preview_image(path: str, max_dim: int = MAX_PREVIEW_BASE_DIM):
    backend_name, reader = choose_reader(path)
    try:
        img = reader(path)
        preview_bgr, ratio = downscale_image(img, max_dim)
        return preview_bgr, float(ratio), {"backend": f"{backend_name}-preview", "suffix": Path(path).suffix.lower()}
    except Exception:
        return None


def load_image(path: str):
    suffix = Path(path).suffix.lower()
    backend_name, reader = choose_reader(path)
    try:
        result = reader(path)
    except Exception as exc:
        raise RuntimeError(f"Unable to read image with {backend_name}: {exc}") from exc

    if result is None or result.size == 0:
        raise RuntimeError(f"Unable to read image with {backend_name}: empty result")

    return result, {"backend": backend_name, "attempts": [], "suffix": suffix}


def rotate_image(img_bgr: np.ndarray, deg: int) -> np.ndarray:
    deg = deg % 360
    if deg == 0:
        return img_bgr
    if deg == 90:
        return cv2.rotate(img_bgr, cv2.ROTATE_90_CLOCKWISE)
    if deg == 180:
        return cv2.rotate(img_bgr, cv2.ROTATE_180)
    if deg == 270:
        return cv2.rotate(img_bgr, cv2.ROTATE_90_COUNTERCLOCKWISE)
    raise ValueError("rotation must be one of 0/90/180/270")


def cv_to_pil(img_bgr: np.ndarray) -> Image.Image:
    img_bgr = normalize_to_uint8(img_bgr)
    rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)


def to_gray8(img_bgr: np.ndarray) -> np.ndarray:
    if img_bgr.ndim == 2:
        return normalize_to_uint8(img_bgr)
    return cv2.cvtColor(normalize_to_uint8(img_bgr), cv2.COLOR_BGR2GRAY)


def downscale_image(img: np.ndarray, max_dim: int):
    h, w = img.shape[:2]
    scale = min(1.0, float(max_dim) / float(max(h, w)))
    if scale >= 0.999:
        return img, 1.0
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
    return resized, scale


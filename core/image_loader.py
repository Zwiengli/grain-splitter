from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from core.constants import MAX_PREVIEW_BASE_DIM

Image.MAX_IMAGE_PIXELS = None

try:
    import rawpy
except Exception:
    rawpy = None

try:
    import tifffile
except Exception:
    tifffile = None
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


def read_with_pillow(path: str) -> np.ndarray:
    with Image.open(path) as im:
        if getattr(im, "n_frames", 1) > 1:
            im.seek(0)
        if im.mode not in {"RGB", "RGBA", "L", "I;16", "I;16B", "I;16L", "I"}:
            im = im.convert("RGB")
        arr = np.array(im)

    if arr.ndim == 2:
        return cv2.cvtColor(normalize_to_uint8(arr), cv2.COLOR_GRAY2BGR)

    if arr.ndim != 3:
        raise RuntimeError(f"Pillow 杩斿洖浜嗕笉鏀寔鐨勭淮搴? {arr.ndim}")

    if arr.shape[2] == 4:
        arr = arr[:, :, :3]
    return cv2.cvtColor(normalize_to_uint8(arr), cv2.COLOR_RGB2BGR)


def load_preview_image(path: str, max_dim: int = MAX_PREVIEW_BASE_DIM):
    try:
        with Image.open(path) as im:
            if getattr(im, "n_frames", 1) > 1:
                im.seek(0)
            orig_w, orig_h = im.size
            try:
                im.draft("RGB", (max_dim, max_dim))
            except Exception:
                pass
            if im.mode not in {"RGB", "RGBA", "L", "I;16", "I;16B", "I;16L", "I"}:
                im = im.convert("RGB")
            im.thumbnail((max_dim, max_dim), Image.Resampling.BILINEAR)
            arr = np.array(im)

        if arr.ndim == 2:
            preview_bgr = cv2.cvtColor(normalize_to_uint8(arr), cv2.COLOR_GRAY2BGR)
        elif arr.ndim == 3:
            if arr.shape[2] == 4:
                arr = arr[:, :, :3]
            preview_bgr = cv2.cvtColor(normalize_to_uint8(arr), cv2.COLOR_RGB2BGR)
        else:
            return None

        ratio = min(1.0, float(max_dim) / float(max(orig_h, orig_w))) if max(orig_h, orig_w) > 0 else 1.0
        return preview_bgr, float(ratio), {"backend": "Pillow-preview", "suffix": Path(path).suffix.lower()}
    except Exception:
        return None


def read_with_tifffile(path: str) -> np.ndarray:
    if tifffile is None:
        raise RuntimeError("鏈畨瑁?tifffile")
    arr = tifffile.imread(path)
    return array_to_bgr(arr, assume_rgb=True)


def read_with_rawpy(path: str) -> np.ndarray:
    if rawpy is None:
        raise RuntimeError("鏈畨瑁?rawpy")
    with rawpy.imread(path) as raw:
        rgb = raw.postprocess(
            use_camera_wb=True,
            no_auto_bright=True,
            auto_bright_thr=0.0,
            output_bps=8,
        )
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def load_image(path: str):
    suffix = Path(path).suffix.lower()
    if suffix == ".fff":
        backends = [
            ("tifffile", read_with_tifffile),
            ("Pillow", read_with_pillow),
            ("OpenCV", read_with_cv2),
            ("rawpy", read_with_rawpy),
        ]
    else:
        backends = [
            ("OpenCV", read_with_cv2),
            ("Pillow", read_with_pillow),
            ("tifffile", read_with_tifffile),
        ]

    attempts = []
    used_backend = None
    result = None
    for name, reader in backends:
        try:
            img = reader(path)
            if img is None or img.size == 0:
                raise RuntimeError("璇诲彇缁撴灉涓虹┖")
            result = img
            used_backend = name
            break
        except Exception as exc:
            attempts.append(f"{name}: {exc}")

    if result is None:
        details = "\n".join(attempts) if attempts else "no available image readers"
        raise RuntimeError(f"Unable to read image:\n{details}")

    return result, {"backend": used_backend, "attempts": attempts, "suffix": suffix}


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


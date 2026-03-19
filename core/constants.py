from __future__ import annotations

SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp", ".fff"}
EXPORTABLE_ORIGINAL_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
OPEN_FILE_PATTERN = "*.jpg *.jpeg *.png *.tif *.tiff *.bmp *.webp *.fff"

MAX_ANALYSIS_DIM = 2600
MAX_PREVIEW_BASE_DIM = 4096
ASYNC_PREVIEW_MAX_DIM = 1800
MAX_IMAGE_CACHE_ITEMS = 2
MAX_IMAGE_CACHE_BYTES = 1500 * 1024 * 1024
MAX_DERIVED_CACHE_ITEMS = 12
MAX_DERIVED_CACHE_BYTES = 700 * 1024 * 1024
MAX_DETECTION_CACHE_ITEMS = 6
MAX_UNDO_STEPS = 20
MIN_FRAME_HEIGHT = 20
MIN_STRIP_WIDTH = 20

DEFAULT_BG_THRESH = 20
DEFAULT_CROP_PAD = 4
DEFAULT_JPEG_QUALITY = 95
DEFAULT_PNG_COMPRESS_LEVEL = 6
DEFAULT_TIFF_COMPRESSION = "tiff_lzw"

PRESET_IDS = ["auto", "120_6x6", "120_6x4_5", "120_6x7", "120_6x9", "135_manual"]
PRESET_FRAME_COUNTS = {
    "auto": 0,
    "120_6x6": 12,
    "120_6x4_5": 16,
    "120_6x7": 10,
    "120_6x9": 8,
    "135_manual": 0,
}
ORIENTATION_IDS = ["auto", "vertical", "horizontal"]
FORMAT_IDS = ["original", "png", "jpg", "tiff"]
LANGUAGE_IDS = ["zh", "en", "de"]
TIFF_COMPRESSION_IDS = ["raw", "tiff_lzw", "tiff_adobe_deflate"]

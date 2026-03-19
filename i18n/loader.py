from __future__ import annotations

import json

from core.runtime_paths import get_resource_path

LANGUAGE_FILES = {
    "zh": "zh_cn.json",
    "en": "en.json",
    "de": "de.json",
}

def _load_json(name: str) -> dict:
    path = get_resource_path("i18n", name)
    with path.open("r", encoding="utf-8-sig") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise RuntimeError(f"Invalid i18n file: {path}")
    return data


def load_i18n() -> dict[str, dict]:
    english = _load_json(LANGUAGE_FILES["en"])
    catalogs: dict[str, dict] = {}
    for lang_id, file_name in LANGUAGE_FILES.items():
        data = _load_json(file_name)
        catalogs[lang_id] = {**english, **data} if lang_id != "en" else data
    return catalogs


I18N = load_i18n()


from __future__ import annotations

import json
from pathlib import Path


class SettingsManager:
    def __init__(self, default_path: str | Path, user_path: str | Path):
        self.default_path = Path(default_path)
        self.user_path = Path(user_path)
        self.data = self._load()

    def _read_json(self, path: Path) -> dict:
        if not path.exists():
            return {}
        try:
            with path.open("r", encoding="utf-8-sig") as fh:
                data = json.load(fh)
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _load(self) -> dict:
        defaults = self._read_json(self.default_path)
        user = self._read_json(self.user_path)
        return {**defaults, **user}

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def set(self, key: str, value, save: bool = True):
        self.data[key] = value
        if save:
            self.save()

    def update(self, mapping: dict, save: bool = True):
        self.data.update(mapping)
        if save:
            self.save()

    def remove(self, *keys: str, save: bool = True):
        changed = False
        for key in keys:
            if key in self.data:
                del self.data[key]
                changed = True
        if changed and save:
            self.save()

    def save(self):
        self.user_path.parent.mkdir(parents=True, exist_ok=True)
        with self.user_path.open("w", encoding="utf-8") as fh:
            json.dump(self.data, fh, ensure_ascii=False, indent=2)

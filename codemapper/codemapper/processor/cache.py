import hashlib
import json
from pathlib import Path
from typing import TypedDict


class CacheEntry(TypedDict):
    hash: str
    timestamp: float


class HashCache:
    def __init__(self, root: Path, lock_file: str = "mapper.lock") -> None:
        self._lock_path = root / lock_file
        self._cache: dict[str, CacheEntry] = self._load()

    def _load(self) -> dict[str, CacheEntry]:
        if self._lock_path.exists():
            try:
                return json.loads(self._lock_path.read_text())
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def save(self) -> None:
        self._lock_path.write_text(json.dumps(self._cache, indent=2))

    @staticmethod
    def compute_hash(code: str) -> str:
        return hashlib.sha256(code.encode()).hexdigest()

    def is_changed(self, symbol_id: str, current_hash: str) -> bool:
        entry = self._cache.get(symbol_id)
        if not entry:
            return True
        return entry["hash"] != current_hash

    def update(self, symbol_id: str, code_hash: str, timestamp: float) -> None:
        self._cache[symbol_id] = {"hash": code_hash, "timestamp": timestamp}

    def remove(self, symbol_id: str) -> None:
        self._cache.pop(symbol_id, None)

    def get_all_keys(self) -> set[str]:
        return set(self._cache.keys())

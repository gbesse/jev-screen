"""Purpose: Exact-input JSON cache so a resumed or re-run screening never pays twice for the same request."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from .client import JevResult, estimate_cost_usd


class ResultCache:
    """Maps sha256 request keys to validated answers. Errors are never stored (a failed call must be retried)."""

    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)
        self._entries: dict[str, dict[str, Any]] = {}
        self._dirty = False
        self._lock = threading.Lock()
        if self.path.exists():
            with self.path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                raise ValueError(f"cache file {self.path} is not a JSON object")
            self._entries = data

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, key: str) -> JevResult | None:
        with self._lock:
            entry = self._entries.get(key)
        if entry is None:
            return None
        usage = dict(entry.get("usage", {}))
        return JevResult(
            model=entry["model"],
            answers=entry["answers"],
            usage=usage,
            estimated_cost_usd=estimate_cost_usd(int(usage.get("input_tokens", 0))),
            cached=True,
        )

    def put(self, key: str, result: JevResult) -> None:
        with self._lock:
            self._entries[key] = {
                "model": result.model,
                "answers": result.answers,
                "usage": result.usage,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            self._dirty = True

    def save(self) -> None:
        """Write temp file then rename, so an interrupted run never leaves a truncated cache behind."""
        with self._lock:
            if not self._dirty:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(prefix=self.path.name, suffix=".tmp", dir=self.path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(self._entries, handle, ensure_ascii=False, sort_keys=True)
                os.replace(tmp, self.path)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            self._dirty = False

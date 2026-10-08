"""Disk-backed store for modeled bordereau jobs.

Jobs are written as one JSON file per event and reloaded when the process starts.
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

from fastapi.encoders import jsonable_encoder

_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")


class JobStore:
    def __init__(self, directory: str | os.PathLike[str], keep: int = 32) -> None:
        self.directory = Path(directory)
        self.keep = max(1, int(keep))
        self._lock = threading.Lock()
        self._jobs: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self.directory.mkdir(parents=True, exist_ok=True)
        self._load()

    def _path(self, event_id: str) -> Path:
        name = event_id if _SAFE_ID.fullmatch(event_id) else re.sub(r"[^A-Za-z0-9._-]+", "_", event_id)
        return self.directory / f"{name}.json"

    def _load(self) -> None:
        files = [path for path in self.directory.glob("*.json") if not path.name.endswith(".tmp")]
        files.sort(key=lambda path: path.stat().st_mtime)
        for path in files:
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, UnicodeError):
                continue
            if not isinstance(job, dict):
                continue
            event_id = str(job.get("event_id") or path.stem)
            self._jobs[event_id] = job
            self._jobs.move_to_end(event_id)
        self._trim()

    def remember(self, result: dict[str, Any]) -> dict[str, Any]:
        job = jsonable_encoder(result)
        event_id = str(job["event_id"])
        with self._lock:
            self._jobs[event_id] = job
            self._jobs.move_to_end(event_id)
            self._write(event_id, job)
            self._trim()
        return job

    def _write(self, event_id: str, job: dict[str, Any]) -> None:
        path = self._path(event_id)
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(job), encoding="utf-8")
        os.replace(temporary, path)

    def _trim(self) -> None:
        while len(self._jobs) > self.keep:
            old_id, _job = self._jobs.popitem(last=False)
            try:
                self._path(old_id).unlink(missing_ok=True)
            except OSError:
                pass

    def get(self, event_id: str) -> dict[str, Any] | None:
        return self._jobs.get(event_id)

    def values(self) -> list[dict[str, Any]]:
        return list(self._jobs.values())

    def latest(self) -> dict[str, Any] | None:
        if not self._jobs:
            return None
        return next(reversed(self._jobs.values()))

    def __bool__(self) -> bool:
        return bool(self._jobs)

    def __len__(self) -> int:
        return len(self._jobs)

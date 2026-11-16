"""Incremental state: what was exported, so a rerun only fetches what is new.

Written atomically (temp file + rename) so a crash never leaves half a state.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

SCHEMA_VERSION = 1


@dataclass
class State:
    schema_version: int = SCHEMA_VERSION
    portal: str = "canvas"
    last_export_at: str | None = None
    # course_id -> {fingerprint, rows, run_id, status, exported_at}
    courses: dict[str, dict] = field(default_factory=dict)
    # record_key -> {hash, first_seen_at, last_changed_at}
    records: dict[str, dict] = field(default_factory=dict)
    # doc_key -> {sha256, updated_at, size, path}
    docs: dict[str, dict] = field(default_factory=dict)
    # run_id -> {course_id, status, steps, started_at}
    runs: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "State":
        if not path.exists():
            return cls()
        data = json.loads(path.read_text())
        if data.get("schema_version") != SCHEMA_VERSION:
            raise SystemExit(f"{path} is schema v{data.get('schema_version')}, expected v{SCHEMA_VERSION}")
        return cls(**data)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".state-", suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump(asdict(self), f, indent=1, sort_keys=True, default=str)
        os.replace(tmp, path)

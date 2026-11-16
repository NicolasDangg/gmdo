"""Write the export: records, courses and documents as CSV + JSON, plus a manifest."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable

from .state import SCHEMA_VERSION

DOC_FIELDS = ["doc_key", "kind", "file_id", "course_id", "course_code", "assignment_id",
              "filename", "content_type", "size", "sha256", "path", "status", "updated_at"]


def _cell(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    return v


def write_table(out: Path, name: str, fields: list[str], rows: Iterable[dict], meta: dict) -> int:
    rows = [{k: r.get(k) for k in fields} for r in rows]
    out.mkdir(parents=True, exist_ok=True)
    with open(out / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: _cell(v) for k, v in r.items()})
    (out / f"{name}.json").write_text(json.dumps(
        {"schema_version": SCHEMA_VERSION, **meta, "count": len(rows), name: rows},
        ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return len(rows)


def load_table(out: Path, name: str) -> list[dict]:
    p = out / f"{name}.json"
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8")).get(name, [])


def append_changes(out: Path, changes: list[dict]) -> None:
    if not changes:
        return
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "changes.ndjson", "a", encoding="utf-8") as f:
        for c in changes:
            f.write(json.dumps(c, ensure_ascii=False, default=str) + "\n")

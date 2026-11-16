"""Download documents through the signed-in TinyFish profile browser.

A file is only reported as downloaded if its bytes arrived and match the size the
portal reports. Unchanged files (same id, size and updated_at) are skipped on reruns.
"""
from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

from .session import PortalBrowser
from .state import State

log = logging.getLogger("gmdo.docs")


def safe_name(name: str | None, max_len: int = 120) -> str:
    name = re.sub(r"[^\w.\- ()\[\]]+", "_", name or "file", flags=re.UNICODE).strip(" .")
    return (name or "file")[:max_len]


def target_path(root: Path, d: dict) -> Path:
    folder = root / d["kind"] / safe_name(d.get("course_code") or "personal", 60)
    return folder / f"{d['file_id']}-{safe_name(d.get('filename'))}"


def sync_documents(pb: PortalBrowser, docs: list[dict], state: State, root: Path,
                   max_bytes: int | None = None, progress=None) -> list[dict]:
    rows = []
    by_sha = {v.get("sha256"): v.get("path") for v in state.docs.values() if v.get("sha256")}
    for i, d in enumerate(docs, 1):
        path = target_path(root, d)
        prev = state.docs.get(d["doc_key"])
        row = {**d, "path": str(path), "sha256": None}
        if prev and prev.get("updated_at") == d.get("updated_at") and prev.get("size") == d.get("size") \
                and Path(prev["path"]).exists():
            row.update(sha256=prev["sha256"], path=prev["path"], status="unchanged")
        elif max_bytes and (d.get("size") or 0) > max_bytes:
            row["status"] = "skipped_too_large"
        elif not d.get("url"):
            row["status"] = "no_download_link"
        else:
            log.info("download %d/%d %s (%s bytes)", i, len(docs), d["doc_key"], d.get("size"))
            status, body = None, b""
            for timeout_ms in (90_000, 300_000):          # one retry with a longer wait
                try:
                    status, _, body = pb.download(d["url"], timeout_ms=timeout_ms)
                    if status == 200:
                        break
                except Exception as e:                    # Playwright timeout / dropped connection
                    log.warning("download %s failed: %s", d["doc_key"], type(e).__name__)
                    status = "timeout"
            if status == "timeout":
                row["status"] = "failed_timeout"
            elif status != 200:
                row["status"] = f"failed_http_{status}"
            elif d.get("size") is not None and len(body) != d["size"]:
                row["status"] = "failed_size_mismatch"
            else:
                sha = hashlib.sha256(body).hexdigest()
                row["sha256"] = sha
                if sha in by_sha and by_sha[sha] and Path(by_sha[sha]).exists():
                    row.update(path=by_sha[sha], status="duplicate_of_existing")
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(body)
                    by_sha[sha] = str(path)
                    row["status"] = "new" if not prev else "updated"
        if row["status"] in {"new", "updated", "unchanged", "duplicate_of_existing"}:
            state.docs[d["doc_key"]] = {"sha256": row["sha256"], "updated_at": d.get("updated_at"),
                                       "size": d.get("size"), "path": row["path"]}
        rows.append(row)
        if progress:
            progress(i, len(docs), row["status"])
    return rows

"""Canvas LMS adapter (tested on lms.vinschool.edu.vn).

Split of work:
- TinyFish Agent: opens each course's Grades page in the signed-in profile and
  reads every row the student sees (name, group, dates, score, out-of, comments).
- Portal browser (same profile): lists courses, reads the counts and timestamps
  Canvas reports, so each agent run can be checked and reruns only touch
  courses that changed.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import re
import unicodedata
from typing import Any

from ..session import PortalBrowser

NAME = "canvas"

GOAL = (
    "You are on a Canvas LMS course Grades page for the signed-in student. "
    "If a 'Show All Details' button is present, click it once so comments are visible. "
    "Scroll to the bottom of the grades table. Return EVERY assignment row in table order "
    "(skip group subtotal rows and the final Total row), copying text exactly as displayed; "
    "use null for anything not shown. Do not open individual assignments. "
    "Do not click Submit, What-If, or change anything. Also return the course total, the number "
    "of rows, and whether you reached the end. Field notes: assignment_id is the number after "
    "/assignments/ in the row's link; group is the assignment group label under the name; due and "
    "submitted are dates exactly as displayed; status is a label such as Late, Missing, Excused or "
    "empty; score is the score cell exactly as displayed; out_of is the points possible; comments "
    "are the teacher comment texts for that row; rows_visible is the number of assignment rows you "
    "returned; reached_end is true only if you saw the last row."
)

_S = {"type": "string", "nullable": True}
OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "course_name": _S,
        "course_total": _S,
        "rows_visible": {"type": "integer"},
        "reached_end": {"type": "boolean"},
        "records": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "assignment_id": _S, "name": {"type": "string"}, "group": _S, "due": _S,
                    "submitted": _S, "status": _S, "score": _S, "out_of": _S,
                    "comments": {"type": "array", "nullable": True, "items": {"type": "string"}},
                },
            },
        },
    },
}

# Columns of records.csv, in order. Changing this is a schema_version bump.
RECORD_FIELDS = [
    "record_key", "course_id", "course_code", "course_name", "term",
    "assignment_id", "assignment_name", "group",
    "due_display", "due_at", "submitted_display", "submitted_at",
    "status", "score_display", "score", "out_of", "late", "missing", "excused",
    "portal_state", "comments", "score_verified", "source_run_id", "source_run_url",
    "first_seen_at", "last_changed_at",
]
# Fields whose change counts as "this record changed" on a rerun.
TRACKED = ["assignment_name", "group", "due_at", "submitted_at", "status", "score_display",
           "score", "out_of", "late", "missing", "excused", "portal_state", "comments"]

COURSE_FIELDS = ["course_id", "course_code", "course_name", "term", "start_at", "end_at",
                 "state", "restricted", "course_total", "portal_assignments", "agent_rows",
                 "complete", "note", "run_id", "run_url", "steps"]


def course_url(origin: str, course_id: int | str) -> str:
    return f"{origin}/courses/{course_id}/grades"


# ---------------------------------------------------------------- inventory
def list_courses(pb: PortalBrowser) -> list[dict]:
    raw = pb.get_all("/api/v1/courses?per_page=100&enrollment_state=all&state[]=available"
                     "&state[]=completed&include[]=term") or []
    out = []
    for c in raw:
        out.append({
            "course_id": c["id"],
            "course_code": c.get("course_code"),
            "course_name": c.get("name"),
            "term": (c.get("term") or {}).get("name"),
            "start_at": c.get("start_at"), "end_at": c.get("end_at"),
            "state": c.get("workflow_state"),
            "restricted": bool(c.get("access_restricted_by_date")),
        })
    return sorted(out, key=lambda c: (str(c["term"] or ""), str(c["course_code"] or "")))


def course_feed(pb: PortalBrowser, course_id: int) -> dict[str, dict]:
    """What Canvas itself reports for each assignment, keyed by assignment id."""
    items = pb.get_all(f"/api/v1/courses/{course_id}/assignments?per_page=100"
                       "&include[]=submission&order_by=position") or []
    feed = {}
    for a in items:
        s = a.get("submission") or {}
        feed[str(a["id"])] = {
            "name": a.get("name"), "due_at": a.get("due_at"),
            "points_possible": a.get("points_possible"), "updated_at": a.get("updated_at"),
            "grading_type": a.get("grading_type"),
            "submitted_at": s.get("submitted_at"), "graded_at": s.get("graded_at"),
            "score": s.get("score"), "workflow_state": s.get("workflow_state"),
            "late": s.get("late"), "missing": s.get("missing"), "excused": s.get("excused"),
            # Canvas withholds a score from the student's page until it is posted
            "posted": (bool(s.get("posted_at")) if "posted_at" in s else None),
            "attachments": [
                {"id": f["id"], "filename": f.get("filename") or f.get("display_name"),
                 "url": f.get("url"), "size": f.get("size"),
                 "content_type": f.get("content-type"), "updated_at": f.get("updated_at")}
                for f in (s.get("attachments") or [])
            ],
        }
    return feed


def feed_fingerprint(feed: dict[str, dict]) -> str:
    """Changes whenever an assignment or the student's submission/grade changes."""
    keys = ("name", "due_at", "points_possible", "updated_at", "submitted_at", "graded_at",
            "score", "workflow_state", "late", "missing", "excused")
    rows = sorted((aid, [v.get(k) for k in keys]) for aid, v in feed.items())
    return hashlib.sha256(json.dumps(rows, default=str).encode()).hexdigest()[:16]


# ---------------------------------------------------------------- normalize
_NUM = re.compile(r"^-?\d+(\.\d+)?$")


def _num(s: Any) -> float | None:
    if s is None:
        return None
    t = str(s).strip().replace(",", ".")
    return float(t) if _NUM.match(t) else None


_ESC = re.compile(r"\\u([0-9a-fA-F]{4})")


def _clean(s: Any) -> str | None:
    if s is None:
        return None
    t = _ESC.sub(lambda m: chr(int(m.group(1), 16)), str(s))  # agent sometimes returns literal \u escapes
    t = re.sub(r"\s+", " ", t).strip()
    return t or None


def _fmt(n: float | None) -> str | None:
    if n is None:
        return None
    return str(int(n)) if float(n).is_integer() else str(n)


_FRACTION = re.compile(r"^\s*(-?\d+(?:[.,]\d+)?)\s*/\s*(\d+(?:[.,]\d+)?)\s*$")


def parse_score(display: str | None) -> tuple[float | None, float | None]:
    """'9.5' -> (9.5, None); '9.5 / 10' -> (9.5, 10); '-' or text -> (None, None)."""
    if not display:
        return None, None
    m = _FRACTION.match(display)
    if m:
        return _num(m.group(1)), _num(m.group(2))
    return _num(display), None


def verify(score: float | None, display: str | None, f: dict) -> bool | None:
    """Does the score the agent read match Canvas? None when there is nothing to compare: no
    Canvas entry, or a score Canvas holds but does not show the student yet (pending review,
    not posted)."""
    if not f:
        return None
    feed_score = f.get("score")
    hidden = f.get("workflow_state") == "pending_review" or (feed_score is not None and f.get("posted") is False)
    if score is None and hidden:
        return None
    return (score is None and feed_score is None) or (
        score is not None and feed_score is not None and same_shown(score, float(feed_score), display))


def same_shown(shown: float, stored: float, display: str | None) -> bool:
    """The page rounds (4.6666… shows as 4.67): compare at the precision displayed."""
    m = re.match(r"\s*-?\d+(?:[.,](\d+))?", display or "")
    places = len(m.group(1)) if m and m.group(1) else 0
    return abs(round(stored, places) - shown) < 10 ** -(places + 1) or abs(stored - shown) < 1e-6


def _key(name: str | None) -> str:
    return (_clean(name) or "").casefold()


def on_grades_page(f: dict) -> bool:
    """Canvas leaves ungraded items ("not graded" type, no points) off the student's Grades page."""
    if f.get("grading_type"):
        return f["grading_type"] != "not_graded"
    return f.get("points_possible") is not None


def _ellipsis_match(page: str, full: str) -> bool:
    """The Grades page shortens long names in the middle: 'Bài 12. Đường thẳn...phẳng song song'."""
    parts = [x.strip() for x in re.split(r"\.\.\.|…", page) if x.strip()]
    if len(parts) < 2:
        return False
    head, tail = _loose(parts[0]), _loose(parts[-1])
    return len(head) + len(tail) >= 12 and full.startswith(head) and full.endswith(tail)


def _loose(name: str | None) -> str:
    """Name key that survives the agent's small copying changes: case, spacing, emoji, punctuation."""
    t = _key(name)
    t = "".join(ch for ch in t if unicodedata.category(ch)[0] not in "SC")   # emoji, symbols, controls
    return re.sub(r"[\W_]+", " ", t).strip()


def resolve_ids(rows: list[dict], feed: dict[str, dict]) -> list[dict]:
    """Give every row the Canvas assignment id it belongs to.

    1. An id the agent copied from the row's link is kept only if Canvas lists it.
    2. Otherwise match on the assignment name. When several assignments share a name, narrow by
       points, then pair them in due-date order (the order the Grades page lists them).
    3. Last, a close spelling match (98% similar) when exactly one unclaimed name is that close.
    Each filled id records how it was found in `_id_from`.
    """
    order = {aid: i for i, aid in enumerate(feed)}            # feed is in Canvas position order
    taken: set[str] = set()
    for r in rows:
        aid = str(r.get("assignment_id") or "").strip()
        if aid in feed and aid not in taken:
            r["assignment_id"] = aid
            taken.add(aid)
        else:
            r["assignment_id"] = None

    by_name: dict[str, list[str]] = {}
    for aid, f in feed.items():
        by_name.setdefault(_loose(f.get("name")), []).append(aid)

    def due_order(aid: str):
        return (feed[aid].get("due_at") or "9999", order[aid])

    for r in rows:
        if r["assignment_id"]:
            continue
        cands = [a for a in by_name.get(_loose(r.get("name")), []) if a not in taken]
        if len(cands) > 1:
            pts = _num(r.get("out_of"))
            if pts is not None:
                same_pts = [a for a in cands if feed[a].get("points_possible") is not None
                            and abs(float(feed[a]["points_possible"]) - pts) < 1e-6]
                cands = same_pts or cands
        if not cands:
            continue
        cands.sort(key=due_order)
        r["assignment_id"] = cands[0]
        r["_id_from"] = "name" if len(by_name[_loose(r.get("name"))]) == 1 else "name+order"
        taken.add(cands[0])

    free = [a for a in feed if a not in taken]
    for r in rows:                                            # names cut short with no ellipsis
        if r["assignment_id"] or not free:
            continue
        head = _loose(r.get("name"))
        hits = [a for a in free if len(head) >= 15 and _loose(feed[a].get("name")).startswith(head)]
        if len(hits) == 1:
            r["assignment_id"] = hits[0]
            r["_id_from"] = "name-start"
            taken.add(hits[0]); free.remove(hits[0])
    for r in rows:                                            # names shortened with an ellipsis
        if r["assignment_id"] or not free:
            continue
        hits = [a for a in free if _ellipsis_match(r.get("name") or "", _loose(feed[a].get("name")))]
        if len(hits) == 1:
            r["assignment_id"] = hits[0]
            r["_id_from"] = "shortened-name"
            taken.add(hits[0]); free.remove(hits[0])
    for r in rows:
        if r["assignment_id"] or not free:
            continue
        scored = sorted(((difflib.SequenceMatcher(None, _loose(r.get("name")), _loose(feed[a].get("name"))).ratio(), a)
                         for a in free), reverse=True)
        if scored and scored[0][0] >= 0.98 and (len(scored) == 1 or scored[1][0] < scored[0][0]):
            r["assignment_id"] = scored[0][1]
            r["_id_from"] = "close-name"
            taken.add(scored[0][1]); free.remove(scored[0][1])
    return rows


def normalize(row: dict, course: dict, feed: dict[str, dict], run_id: str, run_url: str,
              course_total: str | None = None) -> dict:
    aid = _clean(row.get("assignment_id"))
    f = feed.get(aid or "", {})
    score_display = _clean(row.get("score"))
    score, frac_out_of = parse_score(score_display)
    feed_score = f.get("score")
    verified = verify(score, score_display, f)
    out_of = _num(row.get("out_of"))
    if out_of is None:
        out_of = frac_out_of
    if out_of is None and f.get("points_possible") is not None:
        out_of = float(f["points_possible"])  # Canvas leaves 0-point "out of" cells blank
    comments = [c for c in (_clean(c) for c in (row.get("comments") or [])) if c]
    return {
        "record_key": f"canvas:{course['course_id']}:{aid or _fallback_key(course, row)}",
        "course_id": course["course_id"], "course_code": course.get("course_code"),
        "course_name": course.get("course_name"), "term": course.get("term"),
        "assignment_id": aid, "assignment_name": _clean(row.get("name")),
        "group": _clean(row.get("group")),
        "due_display": _clean(row.get("due")), "due_at": f.get("due_at"),
        "submitted_display": _clean(row.get("submitted")), "submitted_at": f.get("submitted_at"),
        "status": _clean(row.get("status")),
        "score_display": score_display, "score": _fmt(score), "out_of": _fmt(out_of),
        "late": f.get("late"), "missing": f.get("missing"), "excused": f.get("excused"),
        "portal_state": f.get("workflow_state"),
        "comments": " | ".join(comments) or None,
        "score_verified": verified,
        "source_run_id": run_id, "source_run_url": run_url,
    }


def _fallback_key(course: dict, row: dict) -> str:
    basis = f"{course['course_id']}|{_clean(row.get('name'))}|{_clean(row.get('due'))}"
    return "h" + hashlib.sha1(basis.encode()).hexdigest()[:12]


def content_hash(rec: dict) -> str:
    return hashlib.sha256(json.dumps([rec.get(k) for k in TRACKED], default=str).encode()).hexdigest()[:16]


# ---------------------------------------------------------------- documents
def list_documents(pb: PortalBrowser, courses: list[dict], feeds: dict[int, dict],
                   kinds: set[str]) -> list[dict]:
    docs: list[dict] = []

    def add(kind: str, f: dict, course: dict | None = None, assignment_id: str | None = None):
        docs.append({
            "doc_key": f"canvas:file:{f['id']}", "kind": kind, "file_id": f["id"],
            "course_id": course["course_id"] if course else None,
            "course_code": course.get("course_code") if course else None,
            "assignment_id": assignment_id,
            "filename": f.get("filename") or f.get("display_name"),
            "content_type": f.get("content-type") or f.get("content_type"),
            "size": f.get("size"), "updated_at": f.get("updated_at"), "url": f.get("url"),
        })

    if "own" in kinds:
        for f in pb.get_all("/api/v1/users/self/files?per_page=100") or []:
            add("own", f)
    by_id = {c["course_id"]: c for c in courses}
    if "submissions" in kinds:
        for cid, feed in feeds.items():
            for aid, a in feed.items():
                for f in a.get("attachments", []):
                    add("submission", {**f, "content-type": f.get("content_type")}, by_id.get(cid), aid)
    if "course" in kinds:
        for c in courses:
            if c["restricted"]:
                continue
            for f in pb.get_all(f"/api/v1/courses/{c['course_id']}/files?per_page=100") or []:
                add("course", f, c)
    # one file can appear in several places (e.g. own upload also attached to a submission)
    seen, uniq = set(), []
    for d in docs:
        if d["doc_key"] in seen:
            continue
        seen.add(d["doc_key"])
        uniq.append(d)
    return uniq

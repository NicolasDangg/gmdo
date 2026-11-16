"""Turn a *showcase* export (names already removed by `gmdo showcase`) into site/data.js.

Usage: python docs/landing/build_data.py showcase/ [rerun-manifest.json]
Only reads the redacted copy, so nothing personal can reach the page.
"""
import json
import sys
from pathlib import Path

src = Path(sys.argv[1] if len(sys.argv) > 1 else "showcase")
rerun_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None


def load(name):
    return json.loads((src / f"{name}.json").read_text(encoding="utf-8"))


records = load("records")["records"]
courses = load("courses")["courses"]

# Display names for the landing page only (the showcase export itself is unchanged).
LABEL_OVERRIDES = {"Physics · Grade 12": "A-Level Physics · Grade 12"}   # owner's choice, 16 Nov
for c in courses:
    c["course_name"] = LABEL_OVERRIDES.get(c["course_name"], c["course_name"])
for r in records:
    r["course_name"] = LABEL_OVERRIDES.get(r.get("course_name"), r.get("course_name"))
docs = load("documents")["documents"]
manifest = json.loads((src / "manifest.json").read_text())
rerun = json.loads(rerun_path.read_text()) if rerun_path and rerun_path.exists() else None

# guard: the redacted copy must say so
assert "showcase" in manifest, "build_data.py only reads a showcase copy"

course_rows = []
for c in sorted(courses, key=lambda c: not (c["course_name"] or "").startswith("A-Level Physics")):
    course_rows.append({
        "id": c["course_id"], "label": c["course_name"], "term": c.get("term"),
        "listed": c.get("portal_assignments"), "read": c.get("agent_rows"),
        "complete": c.get("complete"), "steps": c.get("steps"), "note": c.get("note"),
        "run": (c.get("run_id") or "")[:8] or None,
    })

# a few real rows for the records table: prefer a course with fraction scores and comments
def score_rows(cid, n=7):
    rows = [r for r in records if r["course_id"] == cid]
    return [{k: r.get(k) for k in ("record_key", "assignment_name", "group", "due_at", "submitted_at",
                                   "score_display", "score", "out_of", "portal_state", "comments",
                                   "score_verified")} for r in rows[:n]]

FEATURE = "A-Level Physics"     # the subject the mockups lead with
label_of = {c["course_id"]: c["course_name"] or "" for c in courses}
ranked = sorted({r["course_id"] for r in records},
                key=lambda cid: (not label_of.get(cid, "").startswith(FEATURE),
                                 -sum(1 for r in records if r["course_id"] == cid and r.get("score"))))
sample_course = ranked[0] if ranked else None

doc_status = {}
for d in docs:
    doc_status[d["status"]] = doc_status.get(d["status"], 0) + 1

data = {
    "portal": "canvas.your-school.edu",
    "terms_checked": manifest.get("terms_checked"),
    "totals": {
        "records": len(records),
        "scored": sum(1 for r in records if r.get("score") is not None),
        "verified": sum(1 for r in records if r.get("score_verified") is True),
        "mismatched": sum(1 for r in records if r.get("score_verified") is False),
        "courses": len(courses),
        "in_scope": sum(1 for c in courses if c.get("note") != "term not selected"),
        "docs": len(docs),
        "doc_mb": round(sum(d.get("size") or 0 for d in docs) / 1e6),
        "doc_status": doc_status,
    },
    "first_run": {k: manifest[k] for k in ("mode", "records", "changes", "courses", "documents", "score_checks")}
                 | {"runs": manifest["agent"]["runs"], "steps": manifest["agent"]["steps"],
                    "cost": manifest["agent"]["est_cost_usd"]},
    "rerun": None if not rerun else {
        "changes": rerun["changes"], "runs": rerun["agent"]["runs"], "steps": rerun["agent"]["steps"],
        "cost": rerun["agent"]["est_cost_usd"], "sent": rerun["courses"]["sent_to_agent"]},
    "courses": course_rows,
    "sample": {"course": next((c["course_name"] for c in courses if c["course_id"] == sample_course), None),
               "rows": score_rows(sample_course)},
    # the hero animation: a few real courses (featured one first), each with its first scored rows
    "stage": [
        {"id": cid, "label": label_of.get(cid), "listed": next((c.get("portal_assignments") for c in courses if c["course_id"] == cid), None),
         "rows": [{"key": r["record_key"], "name": r.get("assignment_name"), "score": r.get("score"), "out_of": r.get("out_of")}
                  for r in sorted((r for r in records if r["course_id"] == cid), key=lambda r: r.get("score") is None)[:8]]}
        for cid in ranked[:5]
    ],
    "doc_names": [d.get("filename") for d in docs if d.get("filename")][:12],
}
out = Path(__file__).resolve().parents[2] / "site" / "data.js"
out.write_text("window.GMDO = " + json.dumps(data, ensure_ascii=False, indent=1) + ";\n", encoding="utf-8")
print(f"wrote {out} ({len(course_rows)} courses, {len(data['sample']['rows'])} sample rows)")

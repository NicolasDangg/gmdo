"""The export pipeline.

1. Portal browser (TinyFish profile session): list courses, read what Canvas
   reports per course, download documents.
2. Pick the courses whose fingerprint changed since the last export.
3. TinyFish Agent: one run per picked course on its Grades page, submitted as a
   batch, each checked against the portal's own count and retried once if short.
4. Merge into the existing export: new rows added, changed rows updated and
   logged, nothing duplicated.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import export as ex
from .client import RUN_LINK, TERMINAL, RunResult, TinyFishClient, TinyFishError, parse_result
from .documents import sync_documents
from .portals import canvas
from .session import portal_browser
from .state import State

log = logging.getLogger("gmdo")
STEP_PRICE = 0.016       # USD per agent step (wallet rate, Nov 2026)
MAX_TRIES = 2            # an unchanged course still short after this many exports waits for --full
MAX_PENDING = 18         # account limit is 20 queued runs; keep a little room
POLL_SECONDS = 8


def est_steps(rows: int) -> int:
    """Observed: 6-12 steps for 8-22 rows; long tables need extra scroll/extract steps."""
    return 9 + rows // 20 * 2


def term_key(term: str | None) -> str:
    return "".join((term or "").split())


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass
class Config:
    origin: str
    profile_id: str
    out: Path = Path("export")
    docs_dir: Path = Path("documents")
    state_path: Path = Path("state.json")
    full: bool = False
    doc_kinds: set[str] = field(default_factory=lambda: {"own", "submissions"})
    max_doc_mb: float | None = 50
    budget_usd: float = 3.0
    only_courses: set[int] | None = None
    only_terms: set[str] | None = None      # e.g. {"2025-2026", "2026-2027"}; spaces ignored
    dry_run: bool = False
    yes: bool = False
    batch: bool = True


WINDOW = 50              # long Grades tables are re-read in windows of this many rows


def agent_request(cfg: Config, course_id: int, window: tuple[int, int] | None = None) -> dict:
    goal = canvas.GOAL
    if window:
        a, b = window
        goal += (f" IMPORTANT: return only assignment rows {a} to {b} of the table, counting from the top "
                 f"starting at 1 (skip subtotal and Total rows when counting). Set reached_end to true only "
                 f"if the table has no row after the last one you returned.")
    return {
        "url": canvas.course_url(cfg.origin, course_id),
        "goal": goal,
        "output_schema": canvas.OUTPUT_SCHEMA,
        "use_profile": True,
        "profile_id": cfg.profile_id,
        "browser_profile": "lite",
        "agent_config": {"max_duration_seconds": 300},
    }


def check_run(res: RunResult, feed: dict) -> tuple[bool, list[str], list[dict]]:
    """Return (complete, missing_assignment_ids, rows)."""
    if res.status != "COMPLETED" or not isinstance(res.result, dict):
        return False, sorted(feed), []
    rows = canvas.resolve_ids([r for r in (res.result.get("records") or []) if isinstance(r, dict)], feed)
    got = {str(r.get("assignment_id")) for r in rows if r.get("assignment_id")}
    expected = {a for a, f in feed.items() if canvas.on_grades_page(f)}
    missing = sorted(expected - got)
    return (not missing and bool(res.result.get("reached_end", True))), missing, rows


def run(cfg: Config, client: TinyFishClient, say=print) -> dict:
    st = State.load(cfg.state_path)
    started = now()

    # ---- 1. inventory + documents in the signed-in profile browser
    say("Opening your signed-in TinyFish browser profile …")
    with portal_browser(client, cfg.profile_id, cfg.origin) as pb:
        say("Signed in. Listing courses …")
        courses = canvas.list_courses(pb)
        if cfg.only_courses:
            courses = [c for c in courses if c["course_id"] in cfg.only_courses]
        feeds: dict[int, dict] = {}
        by_id0 = {c["course_id"]: c for c in courses}
        for n, c in enumerate(courses, 1):
            say(f"  reading course {n}/{len(courses)}", end="\r")
            feeds[c["course_id"]] = {} if c["restricted"] else canvas.course_feed(pb, c["course_id"])
            c["portal_assignments"] = len(feeds[c["course_id"]])
        def in_scope(c):
            return not cfg.only_terms or term_key(c.get("term")) in cfg.only_terms
        docs = canvas.list_documents(pb, [c for c in courses if in_scope(c)],
                                     {k: v for k, v in feeds.items() if in_scope(by_id0[k])}, cfg.doc_kinds)
        say(f"Portal: {len(courses)} courses, {sum(len(f) for f in feeds.values())} assignments, "
            f"{len(docs)} documents ({sum(d.get('size') or 0 for d in docs) / 1e6:.0f} MB)")

        todo, recheck = [], []
        for c in courses:
            cid = str(c["course_id"])
            fp = canvas.feed_fingerprint(feeds[c["course_id"]])
            c["fingerprint"] = fp
            prev = st.courses.get(cid, {})
            if not in_scope(c):
                c["note"] = "term not selected"
                continue
            if c["portal_assignments"] == 0:
                c["note"] = "no assignments"
                continue
            if cfg.full or prev.get("seen_fingerprint", prev.get("fingerprint")) != fp:
                todo.append(c)                       # new or changed since the last export
            elif prev.get("status") != "complete" and prev.get("tries", 0) < MAX_TRIES:
                todo.append(c)                       # unchanged but still short: try again, a limited number of times
            elif prev.get("status") != "complete":
                recheck.append(c)                    # out of paid tries: only the free re-check of saved runs
        est = sum(est_steps(c["portal_assignments"]) for c in todo) * STEP_PRICE
        say(f"Changed since last export: {len(todo)} course(s) → agent runs (est. ~${est:.2f})")
        if cfg.dry_run:
            return {"dry_run": True, "courses": len(courses), "todo": [c["course_id"] for c in todo],
                    "documents": len(docs), "est_usd": round(est, 2)}
        if est > cfg.budget_usd and not cfg.yes:
            raise SystemExit(f"Estimated ${est:.2f} is over the ${cfg.budget_usd:.2f} budget. "
                             "Pass --budget or --yes to go ahead.")

        max_bytes = int(cfg.max_doc_mb * 1e6) if cfg.max_doc_mb else None
        doc_rows = sync_documents(pb, docs, st, cfg.docs_dir, max_bytes,
                                  progress=lambda i, n, s: say(f"  docs {i}/{n}", end="\r") if i % 25 == 0 or i == n else None)
        say("")
        st.save(cfg.state_path)

    # ---- 1b. a course that failed the check last time may pass now (better matching):
    #          re-check its saved runs for free before paying for a new one
    results: dict[int, RunResult] = {}
    reused = set()
    recheck_ids = {c["course_id"] for c in recheck}
    for c in todo + recheck:
        cid = c["course_id"]
        if st.courses.get(str(cid), {}).get("status") != "incomplete":
            continue
        saved = sorted((rid for rid, r in st.runs.items() if r.get("course_id") == cid),
                       key=lambda rid: st.runs[rid].get("finished_at") or "", reverse=True)
        for rid in saved:
            try:
                run = client.get_run(rid)
            except TinyFishError:
                continue
            res = RunResult(rid, run.get("status"), parse_result(run.get("result")), run.get("error"),
                            run.get("streaming_url"), run.get("num_of_steps"))
            ok_saved, _, rows_saved = check_run(res, feeds[cid])
            if ok_saved:
                results[cid] = res
                reused.add(cid)
                break
            best = results.get(cid)
            if best is None or len(rows_saved) > len(check_run(best, feeds[cid])[2]):
                results[cid] = res
        if cid not in reused and len(saved) > 1:
            union = []
            for rid in saved:
                try:
                    r = parse_result(client.get_run(rid).get("result"))
                except TinyFishError:
                    continue
                if isinstance(r, dict):
                    union += r.get("records") or []
            combo = RunResult(saved[0], "COMPLETED", {"records": union, "reached_end": True})
            if check_run(combo, feeds[cid])[0]:
                results[cid] = combo
                reused.add(cid)
        if cid in recheck_ids:
            if cid not in reused:
                results.pop(cid, None)   # out of paid tries: keep last export's rows, no agent run
            continue
        if cid not in reused and cid in results:
            n = sum(1 for f in feeds[cid].values() if canvas.on_grades_page(f))
            if n > WINDOW and len(check_run(results[cid], feeds[cid])[2]) < n // 2:
                reused.add(cid)          # long table that came back empty: step 3 re-reads it in windows
            else:
                results.pop(cid)         # an ordinary short run: send it to the agent again
    passed_now = [c for c in recheck if c["course_id"] in reused]
    todo += passed_now                   # merged below like any other course, at no cost
    if reused:
        say(f"Re-checked saved runs: {len(reused)} course(s) pass now, no new agent run needed")
    todo_agent = [c for c in todo if c["course_id"] not in reused]

    # ---- 2. agent runs in batches, kept under the account's queue limit, each persisted
    #         the moment it is submitted so a crash re-attaches instead of paying again
    active: dict[int, str] = {}
    fp = {c["course_id"]: c["fingerprint"] for c in todo}
    for c in todo_agent:
        prev = st.courses.get(str(c["course_id"]), {})
        if prev.get("status") == "running" and prev.get("fingerprint") == c["fingerprint"] and prev.get("run_id"):
            active[c["course_id"]] = prev["run_id"]          # resume
    queue = [c for c in todo_agent if c["course_id"] not in active]

    def remember(cid: int, rid: str) -> None:
        active[cid] = rid
        st.courses.setdefault(str(cid), {}).update(run_id=rid, status="running", fingerprint=fp[cid])
        st.runs[rid] = {"course_id": cid, "status": "RUNNING", "started_at": now()}

    if not cfg.batch:
        for c in queue:
            results[c["course_id"]] = client.run_sse(agent_request(cfg, c["course_id"]))
        queue = []
    submitted = 0
    deadline = time.monotonic() + 3600
    while queue or active:
        room = MAX_PENDING - len(active)
        if queue and room > 0:
            chunk, queue = queue[:room], queue[room:]
            try:
                ids = client.run_batch([agent_request(cfg, c["course_id"]) for c in chunk])
            except TinyFishError as e:
                if e.code != "RATE_LIMIT_EXCEEDED":
                    raise
                queue = chunk + queue                          # queue is full: wait and try again
                ids = []
            for c, rid in zip(chunk, ids):
                remember(c["course_id"], rid)
            submitted += len(ids)
            if ids:
                st.save(cfg.state_path)
                say(f"Agent: {submitted}/{len(todo)} course(s) submitted in batches")
        for cid, rid in list(active.items()):
            try:
                run = client.get_run(rid)
            except TinyFishError:
                continue
            if run.get("status") in TERMINAL:
                results[cid] = RunResult(rid, run["status"], parse_result(run.get("result")), run.get("error"),
                                         run.get("streaming_url"), run.get("num_of_steps"))
                active.pop(cid)
                say(f"  {len(results)}/{len(todo)} runs finished", end="\r")
        if time.monotonic() > deadline:
            for cid, rid in active.items():
                results[cid] = RunResult(rid, "FAILED", None, {"message": "still running after an hour"})
            break
        if queue or active:
            time.sleep(POLL_SECONDS)
    say("")

    # ---- 3. check each run against the portal; retry short ones once
    by_id = {c["course_id"]: c for c in courses}
    course_rows: dict[int, list[dict]] = {}
    run_log = []
    for c in todo:
        cid = c["course_id"]
        res = results[cid]
        ok, missing, rows = check_run(res, feeds[cid])
        attempts = [res]
        if not ok and res.status != "CANCELLED":
            n = sum(1 for f in feeds[cid].values() if canvas.on_grades_page(f))
            try:
                if n > WINDOW and len(rows) < n // 2:
                    # a long table that came back mostly empty: read it again in windows
                    say(f"  course {cid}: {len(rows)}/{n} rows; re-reading in windows of {WINDOW}")
                    parts = [client.run_sse(agent_request(cfg, cid, (a, min(a + WINDOW - 1, n))))
                             for a in range(1, n + 1, WINDOW)]
                    attempts += parts
                    merged = [r for p in parts if isinstance(p.result, dict) for r in (p.result.get("records") or [])]
                    last = parts[-1]
                    combo = RunResult(last.run_id, "COMPLETED" if all(p.status == "COMPLETED" for p in parts) else "FAILED",
                                      {**(last.result if isinstance(last.result, dict) else {}), "records": merged})
                    ok2, missing2, rows2 = check_run(combo, feeds[cid])
                    if ok2 or len(rows2) > len(rows):
                        res, ok, missing, rows = combo, ok2, missing2, rows2
                else:
                    say(f"  course {cid}: {len(missing)} row(s) short or run {res.status}; retrying once")
                    res2 = client.run_sse(agent_request(cfg, cid))
                    ok2, missing2, rows2 = check_run(res2, feeds[cid])
                    attempts.append(res2)
                    if ok2 or len(rows2) > len(rows):
                        res, ok, missing, rows = res2, ok2, missing2, rows2
            except TinyFishError as e:
                say(f"  retry failed: {e}")
        steps = 0
        for i, a in enumerate(attempts):
            was_saved = i == 0 and cid in reused            # a run paid for in an earlier export
            try:
                info = client.get_run(a.run_id)
                a.steps = info.get("num_of_steps")
            except TinyFishError:
                pass
            if not was_saved:
                steps += a.steps or 0
                st.runs[a.run_id] = {"course_id": cid, "status": a.status, "steps": a.steps, "finished_at": now()}
            run_log.append({"course_id": cid, "run_id": a.run_id, "run_url": RUN_LINK.format(run_id=a.run_id),
                            "status": a.status, "steps": a.steps, "new": not was_saved})
        total = res.result.get("course_total") if isinstance(res.result, dict) else None
        course_rows[cid] = [canvas.normalize(r, c, feeds[cid], res.run_id, res.link, total) for r in rows]
        c.update(agent_rows=len(rows), complete=ok, run_id=res.run_id, run_url=res.link, steps=steps,
                 course_total=total, missing_ids=missing)
        prev_c = st.courses.get(str(cid), {})
        tries = 0 if ok else (prev_c.get("tries", 0) + 1 if prev_c.get("seen_fingerprint", prev_c.get("fingerprint")) == c["fingerprint"] else 1)
        st.courses[str(cid)] = {"fingerprint": c["fingerprint"] if ok else None, "seen_fingerprint": c["fingerprint"],
                                "tries": tries, "rows": len(rows),
                                "run_id": res.run_id, "status": "complete" if ok else "incomplete",
                                "exported_at": now(), "course_total": total}

    # ---- 4. merge into the previous export
    t = now()
    old = {r["record_key"]: r for r in ex.load_table(cfg.out, "records")}
    first_export = not old and not st.last_export_at
    changes = []
    for cid, rows in course_rows.items():
        new_keys = set()
        for r in rows:
            k = r["record_key"]
            if k in new_keys:
                continue                                     # agent repeated a row
            new_keys.add(k)
            h = canvas.content_hash(r)
            prev = st.records.get(k)
            if prev is None:
                r["first_seen_at"] = r["last_changed_at"] = t
                st.records[k] = {"hash": h, "first_seen_at": t, "last_changed_at": t}
                if not first_export:
                    changes.append({"at": t, "change": "added", "record_key": k})
            else:
                r["first_seen_at"] = prev["first_seen_at"]
                if prev["hash"] != h:
                    before = old.get(k, {})
                    diff = {f: [before.get(f), r.get(f)] for f in canvas.TRACKED if before.get(f) != r.get(f)}
                    changes.append({"at": t, "change": "changed", "record_key": k, "fields": diff})
                    prev.update(hash=h, last_changed_at=t)
                r["last_changed_at"] = prev["last_changed_at"]
            old[k] = r
        if by_id[cid].get("complete"):
            for k in [k for k, r in old.items() if r["course_id"] == cid and k not in new_keys]:
                changes.append({"at": t, "change": "removed_from_portal", "record_key": k})
                old.pop(k)
                st.records.pop(k, None)

    # carry forward per-course stats for courses not re-run this time
    prev_courses = {c["course_id"]: c for c in ex.load_table(cfg.out, "courses")}
    for c in courses:
        if c["course_id"] not in course_rows:
            p = prev_courses.get(c["course_id"], {})
            for k in ("agent_rows", "complete", "run_id", "run_url", "steps", "course_total"):
                c.setdefault(k, p.get(k))
            if c.get("note") == "term not selected":
                c.update(agent_rows=None, complete=None)
            elif c["portal_assignments"] == 0:
                c.update(agent_rows=0, complete=True)

    for r in old.values():                               # re-check every score against today's Canvas data
        f = feeds.get(r["course_id"], {}).get(str(r.get("assignment_id") or ""))
        if f:
            r["score_verified"] = canvas.verify(canvas._num(r.get("score")), r.get("score_display"), f)
            r["portal_state"] = f.get("workflow_state")
    records = sorted(old.values(), key=lambda r: (str(r.get("term") or ""), str(r.get("course_code") or ""),
                                                  str(r.get("assignment_id") or "")))
    meta = {"portal": cfg.origin, "exported_at": t}
    n_rec = ex.write_table(cfg.out, "records", canvas.RECORD_FIELDS, records, meta)
    ex.write_table(cfg.out, "courses", canvas.COURSE_FIELDS, courses, meta)
    ex.write_table(cfg.out, "documents", ex.DOC_FIELDS, doc_rows, meta)
    ex.append_changes(cfg.out, changes)

    steps = sum(r["steps"] or 0 for r in run_log if r.get("new", True))
    doc_status: dict[str, int] = {}
    for d in doc_rows:
        doc_status[d["status"]] = doc_status.get(d["status"], 0) + 1
    manifest = {
        "schema_version": st.schema_version, "portal": cfg.origin, "started_at": started, "finished_at": now(),
        "mode": "full" if cfg.full or not st.last_export_at else "incremental",
        "since": st.last_export_at,
        "records": n_rec,
        "scope": {"terms": sorted(cfg.only_terms) if cfg.only_terms else "all",
                  "document_kinds": sorted(cfg.doc_kinds)},
        "courses": {"total": len(courses), "sent_to_agent": len(todo),
                    "out_of_scope": sum(1 for c in courses if c.get("note") == "term not selected"),
                    "complete": sum(1 for c in courses if c.get("complete")),
                    "incomplete": [{"course_id": c["course_id"], "missing_ids": c.get("missing_ids")}
                                   for c in courses if c.get("complete") is False]},
        "changes": {k: sum(1 for c in changes if c["change"] == k) for k in ("added", "changed", "removed_from_portal")},
        "documents": doc_status,
        "agent": {"runs": sum(1 for r in run_log if r.get("new", True)), "reused_runs": sum(1 for r in run_log if not r.get("new", True)), "steps": steps, "est_cost_usd": round(steps * STEP_PRICE, 3), "run_log": run_log},
        "score_checks": {"verified": sum(1 for r in records if r.get("score_verified") is True),
                         "mismatched": sum(1 for r in records if r.get("score_verified") is False)},
    }
    import json
    (cfg.out / "manifest.json").write_text(json.dumps(manifest, indent=1, default=str))
    st.last_export_at = t
    st.save(cfg.state_path)
    return manifest

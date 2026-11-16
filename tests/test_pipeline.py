"""Offline tests built from real (scrubbed) TinyFish runs on the Canvas portal."""
import json
from pathlib import Path

import httpx
import pytest
import respx

from getmydataout import export as ex
from getmydataout.client import BASE, ReauthRequired, RunResult, TinyFishClient, TinyFishError, parse_result
from getmydataout.extract import check_run
from getmydataout.portals import canvas
from getmydataout.redact import scrub
from getmydataout.state import State

FX = Path(__file__).parent / "fixtures"
RUNS = json.loads((FX / "canvas_runs.json").read_text())
COURSE = {"course_id": 0, "course_code": "C", "course_name": "Course", "term": "2025-2026"}


def client(**kw):
    return TinyFishClient(api_key="test", sleep=lambda s: None, **kw)


def result(cid):
    r = RUNS[cid]
    return RunResult(r["run_id"], "COMPLETED", r["result"]), r["feed"]


# ---------------------------------------------------------------- client
@respx.mock
def test_sse_stream_returns_parsed_result():
    respx.post(f"{BASE}/v1/automation/run-sse").respond(200, text=(FX / "golden_run.sse").read_text(),
                                                         headers={"content-type": "text/event-stream"})
    events = []
    res = client().run_sse({"url": "https://x", "goal": "g"}, on_event=events.append)
    assert res.status == "COMPLETED"
    assert res.run_id == RUNS["37598"]["run_id"]
    assert res.streaming_url
    assert len(res.result["records"]) == 22          # string-wrapped JSON was decoded
    assert {e["type"] for e in events} >= {"STARTED", "PROGRESS", "COMPLETE"}


@respx.mock
def test_stream_drop_falls_back_to_polling():
    stream = 'data: {"type":"STARTED","run_id":"r1"}\n\n'
    respx.post(f"{BASE}/v1/automation/run-sse").respond(200, text=stream)
    respx.get(f"{BASE}/v1/runs/r1").mock(side_effect=[
        httpx.Response(200, json={"run_id": "r1", "status": "RUNNING"}),
        httpx.Response(200, json={"run_id": "r1", "status": "COMPLETED", "result": {"records": []}, "num_of_steps": 4}),
    ])
    res = client().run_sse({"url": "https://x", "goal": "g"})
    assert res.status == "COMPLETED" and res.steps == 4


@respx.mock
def test_retries_rate_limit_then_succeeds():
    route = respx.get(f"{BASE}/v1/runs/r1").mock(side_effect=[
        httpx.Response(429, json={"error": {"code": "RATE_LIMIT_EXCEEDED", "message": "slow"}}, headers={"Retry-After": "1"}),
        httpx.Response(200, json={"run_id": "r1", "status": "COMPLETED"}),
    ])
    assert client().get_run("r1")["status"] == "COMPLETED"
    assert route.call_count == 2


@respx.mock
def test_agent_failure_is_not_retried():
    route = respx.get(f"{BASE}/v1/runs/r1").respond(
        400, json={"error": {"code": "INVALID_INPUT", "message": "bad", "category": "AGENT_FAILURE"}})
    with pytest.raises(TinyFishError):
        client().get_run("r1")
    assert route.call_count == 1


@respx.mock
def test_auth_wall_raises_reauth():
    respx.get(f"{BASE}/v1/runs/r1").respond(200, json={
        "run_id": "r1", "status": "FAILED", "error": {"profile_hint": {"reason": "auth_wall", "message": "signed out"}}})
    with pytest.raises(ReauthRequired):
        client().wait("r1")


@respx.mock
def test_batch_moves_shared_fields_to_envelope():
    route = respx.post(f"{BASE}/v1/automation/run-batch").respond(200, json={"run_ids": ["a", "b"], "error": None})
    runs = [{"url": f"https://x/{i}", "goal": "g", "output_schema": canvas.OUTPUT_SCHEMA, "profile_id": "p",
             "use_profile": True} for i in range(2)]
    assert client().run_batch(runs) == ["a", "b"]
    body = json.loads(route.calls[0].request.content)
    assert body["output_schema"] == canvas.OUTPUT_SCHEMA and body["profile_id"] == "p"
    assert all("output_schema" not in r for r in body["runs"])


def test_parse_result_shapes():
    assert parse_result({"result": '{"a": 1}'}) == {"a": 1}
    assert parse_result({"a": 1}) == {"a": 1}


# ---------------------------------------------------------------- checking runs
def test_golden_course_is_complete():
    res, feed = result("37598")
    ok, missing, rows = check_run(res, feed)
    assert ok and not missing and len(rows) == 22


def test_rows_without_ids_are_matched_by_name():
    res, feed = result("80374")
    assert not any(r.get("assignment_id") for r in res.result["records"])
    ok, missing, rows = check_run(res, feed)
    assert ok, missing
    assert all(r["_id_from"] == "name" for r in rows)


def test_short_run_is_flagged():
    res, feed = result("37598")
    res = RunResult(res.run_id, "COMPLETED", {**res.result, "records": res.result["records"][:-3]})
    ok, missing, _ = check_run(res, feed)
    assert not ok and len(missing) == 3


def test_failed_run_is_incomplete():
    _, feed = result("37598")
    ok, missing, rows = check_run(RunResult("x", "FAILED", None), feed)
    assert not ok and rows == [] and len(missing) == 22


# ---------------------------------------------------------------- normalizing
def test_fraction_scores_and_verification():
    res, feed = result("166048")
    _, _, rows = check_run(res, feed)
    recs = [canvas.normalize(r, COURSE, feed, "run", "url") for r in rows]
    fr = [r for r in recs if r["score_display"] and "/" in r["score_display"]]
    assert fr and all(r["score"] is not None and r["out_of"] == "10" for r in fr)
    assert all(r["score_verified"] is not False for r in recs)


def test_every_course_verifies_against_portal():
    for cid in RUNS:
        res, feed = result(cid)
        _, _, rows = check_run(res, feed)
        recs = [canvas.normalize(r, COURSE, feed, "run", "url") for r in rows]
        bad = [r["assignment_id"] for r in recs if r["score_verified"] is False]
        assert not bad, (cid, bad)


def test_unicode_escapes_are_decoded():
    assert canvas._clean("B\\u00e0i T\\u1eadp") == "Bài Tập"


def test_parse_score():
    assert canvas.parse_score("9.5 / 10") == (9.5, 10)
    assert canvas.parse_score("8") == (8, None)
    assert canvas.parse_score("-") == (None, None)
    assert canvas.parse_score("Instructor has not posted this grade") == (None, None)


def test_content_hash_ignores_run_ids():
    res, feed = result("37598")
    _, _, rows = check_run(res, feed)
    a = canvas.normalize(rows[0], COURSE, feed, "run1", "u1")
    b = canvas.normalize(rows[0], COURSE, feed, "run2", "u2")
    assert canvas.content_hash(a) == canvas.content_hash(b)
    b["score"] = "99"
    assert canvas.content_hash(a) != canvas.content_hash(b)


def test_fingerprint_changes_when_a_grade_lands():
    _, feed = result("37598")
    fp = canvas.feed_fingerprint(feed)
    feed2 = json.loads(json.dumps(feed))
    next(iter(feed2.values()))["graded_at"] = "2026-11-20T00:00:00Z"
    assert canvas.feed_fingerprint(feed2) != fp


# ---------------------------------------------------------------- export + state
def test_export_tables_have_fixed_columns(tmp_path):
    res, feed = result("37598")
    _, _, rows = check_run(res, feed)
    recs = [canvas.normalize(r, COURSE, feed, "run", "url") for r in rows]
    ex.write_table(tmp_path, "records", canvas.RECORD_FIELDS, recs, {})
    header = (tmp_path / "records.csv").read_text().splitlines()[0].split(",")
    assert header == canvas.RECORD_FIELDS
    data = json.loads((tmp_path / "records.json").read_text())
    assert data["count"] == 22 and len({r["record_key"] for r in data["records"]}) == 22


def test_state_roundtrip_is_atomic(tmp_path):
    p = tmp_path / "state.json"
    st = State(last_export_at="2026-11-16T00:00:00+00:00")
    st.records["k"] = {"hash": "h"}
    st.save(p)
    assert State.load(p).records == {"k": {"hash": "h"}}
    assert not list(tmp_path.glob(".state-*"))


def test_scrub_masks_personal_data():
    s = scrub("mail a.b@school.edu.vn call +84 912 345 678 X-API-Key: sk-123 https://f?verifier=abc")
    assert "school.edu" not in s and "912" not in s and "sk-123" not in s and "abc" not in s


# ---------------------------------------------------------------- matching rules from the backfill
def _feed(*items):
    return {str(i): {"name": n, "points_possible": p, "due_at": d, "grading_type": g}
            for i, (n, p, d, g) in enumerate(items, 1)}


def test_shortened_names_match_by_start_and_end():
    feed = _feed(("[Quiz] Bài 12. Đường thẳng và mặt phẳng song song", 10, None, "points"))
    rows = canvas.resolve_ids([{"name": "[Quiz] Bài 12. Đường thẳn...phẳng song song"}], feed)
    assert rows[0]["assignment_id"] == "1" and rows[0]["_id_from"] == "shortened-name"


def test_repeated_names_pair_in_due_order_and_points():
    feed = _feed(("Quiz", 10, "2026-03-01", "points"), ("Quiz", 10, "2026-01-01", "points"), ("Quiz", 5, "2026-02-01", "points"))
    rows = canvas.resolve_ids([{"name": "Quiz", "out_of": "10"}, {"name": "Quiz", "out_of": "10"}, {"name": "Quiz", "out_of": "5"}], feed)
    assert [r["assignment_id"] for r in rows] == ["2", "1", "3"]


def test_agent_ids_not_in_canvas_are_dropped():
    feed = _feed(("Essay", 10, None, "points"))
    rows = canvas.resolve_ids([{"assignment_id": "999", "name": "Essay"}], feed)
    assert rows[0]["assignment_id"] == "1"


def test_ungraded_items_are_not_expected_on_the_grades_page():
    feed = _feed(("Essay", 10, None, "points"), ("Reading", None, None, "not_graded"))
    res = RunResult("r", "COMPLETED", {"records": [{"name": "Essay"}], "reached_end": True})
    ok, missing, _ = check_run(res, feed)
    assert ok and missing == []


def test_rounded_scores_still_verify():
    feed = {"7": {"name": "Q", "score": 4.666666, "points_possible": 5, "workflow_state": "graded"}}
    rec = canvas.normalize({"assignment_id": "7", "name": "Q", "score": "4.67"}, COURSE, feed, "r", "u")
    assert rec["score_verified"] is True


def test_unposted_grades_are_not_counted_as_mismatches():
    feed = {"7": {"name": "Q", "score": 8.0, "points_possible": 10, "workflow_state": "graded", "posted": False}}
    rec = canvas.normalize({"assignment_id": "7", "name": "Q", "score": None}, COURSE, feed, "r", "u")
    assert rec["score_verified"] is None

"""Thin client for the TinyFish Agent API (runs, batches, profiles).

Shapes follow docs/SPEC.md. Every call sends only the API key header; no portal
credentials ever pass through this module.
"""
from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterator

import httpx

BASE = "https://agent.tinyfish.ai"
RUN_LINK = "https://agent.tinyfish.ai/runs/{run_id}"
RETRYABLE_HTTP = {429, 500, 502, 503, 504}
RETRYABLE_CODES = {"RATE_LIMIT_EXCEEDED", "SERVICE_BUSY", "TIMEOUT", "INTERNAL_ERROR", "RETRY_REQUIRED"}
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}


class TinyFishError(Exception):
    def __init__(self, code: str, message: str, status: int | None = None,
                 category: str | None = None, retry_after: float | None = None):
        super().__init__(f"{code}: {message}")
        self.code, self.message, self.status = code, message, status
        self.category, self.retry_after = category, retry_after

    @property
    def retryable(self) -> bool:
        if self.category in {"AGENT_FAILURE", "BILLING_FAILURE"}:
            return False
        return self.code in RETRYABLE_CODES or (self.status in RETRYABLE_HTTP)


class ReauthRequired(TinyFishError):
    """The saved profile hit a sign-in wall; rerun `gmdo setup`."""


@dataclass
class RunResult:
    run_id: str
    status: str
    result: Any
    error: dict | None = None
    streaming_url: str | None = None
    steps: int | None = None

    @property
    def link(self) -> str:
        return RUN_LINK.format(run_id=self.run_id)


def parse_result(raw: Any) -> Any:
    """COMPLETE.result may be an object or {"result": "<json string>"}."""
    if isinstance(raw, dict) and set(raw) == {"result"} and isinstance(raw["result"], str):
        raw = raw["result"]
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    return raw


def iter_sse(lines: Iterator[str]) -> Iterator[dict]:
    for line in lines:
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload:
            continue
        try:
            yield json.loads(payload)
        except json.JSONDecodeError:
            continue


class TinyFishClient:
    def __init__(self, api_key: str | None = None, base: str = BASE,
                 transport: httpx.BaseTransport | None = None, max_retries: int = 4, max_net_retries: int = 10,
                 sleep: Callable[[float], None] = time.sleep):
        key = api_key or os.environ.get("TINYFISH_API_KEY")
        if not key:
            raise TinyFishError("MISSING_API_KEY", "set TINYFISH_API_KEY in your environment or .env")
        self.http = httpx.Client(base_url=base, headers={"X-API-Key": key},
                                 timeout=httpx.Timeout(60, read=120), transport=transport)
        self.max_retries, self.max_net_retries, self.sleep = max_retries, max_net_retries, sleep

    # ---- plumbing -------------------------------------------------------
    def _raise(self, r: httpx.Response) -> None:
        if r.status_code < 400:
            return
        try:
            err = r.json().get("error", {})
        except ValueError:
            err = {}
        ra = r.headers.get("Retry-After")
        raise TinyFishError(err.get("code", f"HTTP_{r.status_code}"), err.get("message", r.text[:200]),
                            status=r.status_code, category=err.get("category"),
                            retry_after=float(ra) if ra and ra.replace(".", "").isdigit() else None)

    def _call(self, method: str, path: str, **kw) -> Any:
        api_tries = net_tries = 0
        while True:
            try:
                r = self.http.request(method, path, **kw)
                self._raise(r)
                return r.json() if r.content else None
            except TinyFishError as e:
                api_tries += 1
                if not e.retryable or api_tries > self.max_retries:
                    raise
                self.sleep(e.retry_after or min(60, 2 ** api_tries + random.random()))
            except httpx.TransportError:
                # network blips (DNS, Wi-Fi) get a longer leash than API errors: about 4 minutes
                net_tries += 1
                if net_tries > self.max_net_retries:
                    raise
                self.sleep(min(30, 2 ** net_tries + random.random()))

    # ---- runs -----------------------------------------------------------
    def run_sse(self, req: dict, on_event: Callable[[dict], None] | None = None,
                idle_timeout: float = 90) -> RunResult:
        """Stream one run. If the stream drops, fall back to polling the run."""
        run_id = streaming_url = None
        try:
            with self.http.stream("POST", "/v1/automation/run-sse", json=req,
                                  headers={"Accept": "text/event-stream"},
                                  timeout=httpx.Timeout(60, read=idle_timeout)) as r:
                if r.status_code >= 400:
                    r.read()
                    self._raise(r)
                for ev in iter_sse(r.iter_lines()):
                    if on_event:
                        on_event(ev)
                    t = ev.get("type")
                    if t == "STARTED":
                        run_id = ev.get("run_id")
                    elif t == "STREAMING_URL":
                        streaming_url = ev.get("streaming_url")
                    elif t == "COMPLETE":
                        res = RunResult(ev.get("run_id") or run_id, ev.get("status"), parse_result(ev.get("result")),
                                        {"message": ev.get("error"), "profile_hint": ev.get("profile_hint")} if ev.get("error") or ev.get("profile_hint") else None,
                                        streaming_url)
                        self._check_auth(res)
                        return res
        except (httpx.ReadTimeout, httpx.RemoteProtocolError, httpx.ReadError):
            if not run_id:
                raise
        if not run_id:
            raise TinyFishError("NO_RUN_ID", "stream ended before the run started")
        return self.wait(run_id, streaming_url=streaming_url)

    def run_batch(self, runs: list[dict]) -> list[str]:
        """Shared fields (output_schema, profile_id) go on the envelope, not per run."""
        runs = [dict(r) for r in runs]
        body: dict[str, Any] = {}
        for key in ("output_schema", "profile_id"):
            vals = {json.dumps(r.pop(key), sort_keys=True) for r in runs if key in r}
            if len(vals) > 1:
                raise ValueError(f"batch runs must share one {key}")
            if vals:
                body[key] = json.loads(vals.pop())
        out = self._call("POST", "/v1/automation/run-batch", json={"runs": runs, **body})
        if out.get("error"):
            raise TinyFishError("BATCH_REJECTED", str(out["error"]))
        return out["run_ids"]

    def get_run(self, run_id: str) -> dict:
        return self._call("GET", f"/v1/runs/{run_id}", params={"screenshots": "none", "html": "none"})

    def list_runs(self, **params) -> Iterator[dict]:
        cursor = None
        while True:
            q = {k: v for k, v in {**params, "cursor": cursor}.items() if v is not None}
            page = self._call("GET", "/v1/runs", params=q)
            yield from page.get("data", [])
            pg = page.get("pagination") or {}
            cursor = pg.get("next_cursor") or page.get("next_cursor")
            if not cursor or not (pg.get("has_more", True)):
                return

    def cancel_run(self, run_id: str) -> None:
        self._call("POST", f"/v1/runs/{run_id}/cancel")

    def wait(self, run_id: str, poll: float = 5, timeout: float = 1800, streaming_url: str | None = None) -> RunResult:
        deadline = time.monotonic() + timeout
        while True:
            run = self.get_run(run_id)
            if run.get("status") in TERMINAL:
                res = RunResult(run_id, run["status"], parse_result(run.get("result")), run.get("error"),
                                run.get("streaming_url") or streaming_url, run.get("num_of_steps"))
                self._check_auth(res)
                return res
            if time.monotonic() > deadline:
                raise TinyFishError("TIMEOUT", f"run {run_id} still {run.get('status')} after {timeout}s")
            self.sleep(poll)

    @staticmethod
    def _check_auth(res: RunResult) -> None:
        hint = (res.error or {}).get("profile_hint") or {}
        if hint.get("reason") == "auth_wall":
            raise ReauthRequired("AUTH_WALL", hint.get("message", "profile is signed out"))

    # ---- profiles -------------------------------------------------------
    def create_profile(self, name: str) -> dict:
        return self._call("POST", "/v1/profiles", json={"name": name})

    def get_profile(self, profile_id: str) -> dict:
        return self._call("GET", f"/v1/profiles/{profile_id}")

    def start_setup_session(self, profile_id: str, url: str | None = None, timeout_seconds: int = 900) -> dict:
        body = {"timeout_seconds": timeout_seconds, **({"url": url} if url else {})}
        return self._call("POST", f"/v1/profiles/{profile_id}/setup-session", json=body)

    def save_setup_session(self, profile_id: str, session_id: str, signed_in_sites: list[str] | None = None) -> dict:
        body = {"session_id": session_id, **({"signed_in_sites": signed_in_sites} if signed_in_sites else {})}
        return self._call("POST", f"/v1/profiles/{profile_id}/save", json=body)

    def cancel_setup_session(self, profile_id: str, session_id: str) -> None:
        self._call("POST", f"/v1/profiles/{profile_id}/setup-session/cancel", json={"session_id": session_id})

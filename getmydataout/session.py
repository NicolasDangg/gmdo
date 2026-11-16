"""The signed-in portal browser: a TinyFish profile setup session driven over CDP.

The agent reads pages; this browser (same profile, same cookies, TinyFish
infrastructure) does what an agent result cannot: download file bytes and read
the counts the portal itself reports, so the export can be checked for
completeness. No password is ever typed here.
"""
from __future__ import annotations

import json
import re
import time
from contextlib import contextmanager
from typing import Iterator

import httpx
from playwright.sync_api import sync_playwright

from .client import ReauthRequired, TinyFishClient, TinyFishError

NEXT = re.compile(r'<([^>]+)>;\s*rel="next"')


class PortalBrowser:
    def __init__(self, page, origin: str):
        self.page, self.origin = page, origin
        self._http: httpx.Client | None = None

    def _get(self, path: str) -> tuple[int, str | None, str]:
        return self.page.evaluate(
            """async (p) => { const c = new AbortController(); const t = setTimeout(() => c.abort(), 30000);
                 try { const r = await fetch(p, {credentials: 'include', headers: {Accept: 'application/json'}, signal: c.signal});
                       return [r.status, r.headers.get('link'), (await r.text()).replace(/^while\\(1\\);/, '')]; }
                 catch (e) { return [599, null, String(e)]; } finally { clearTimeout(t); } }""", path)

    def get_json(self, path: str):
        status, _, body = self._get(path)
        if status == 401:
            raise ReauthRequired("AUTH_WALL", "portal session is signed out; run `gmdo setup`")
        if status != 200:
            return None
        return json.loads(body)

    def get_all(self, path: str, max_pages: int = 50) -> list | None:
        """Follow Link rel=next pagination. None means the portal refused (e.g. tab hidden)."""
        out, url = [], path
        for _ in range(max_pages):
            status, link, body = self._get(url)
            if status == 401:
                raise ReauthRequired("AUTH_WALL", "portal session is signed out; run `gmdo setup`")
            if status == 599:
                raise TimeoutError(f"portal request timed out: {path}")
            if status != 200:
                return None if not out else out
            out.extend(json.loads(body))
            m = NEXT.search(link or "")
            if not m:
                return out
            url = m.group(1)
        raise RuntimeError(f"pagination did not end after {max_pages} pages: {path}")

    def _direct(self) -> httpx.Client:
        """An HTTP client carrying this signed-in browser's cookies and user agent, so file
        bytes come straight to this machine instead of through the remote browser."""
        if self._http is None:
            jar = httpx.Cookies()
            for c in self.page.context.cookies():
                jar.set(c["name"], c["value"], domain=c["domain"], path=c.get("path", "/"))
            ua = self.page.evaluate("navigator.userAgent")
            self._http = httpx.Client(cookies=jar, headers={"User-Agent": ua}, follow_redirects=True,
                                      timeout=httpx.Timeout(30, read=120))
        return self._http

    def download(self, url: str, timeout_ms: int = 120_000) -> tuple[int, str, bytes]:
        try:
            r = self._direct().get(url, timeout=httpx.Timeout(30, read=timeout_ms / 1000))
            if r.status_code == 200 and "text/html" not in r.headers.get("content-type", ""):
                return 200, r.headers.get("content-type", ""), r.content
        except httpx.HTTPError:
            pass
        # fall back to fetching inside the remote browser (slower, but always signed in)
        r = self.page.request.get(url, timeout=timeout_ms)
        return r.status, r.headers.get("content-type", ""), r.body()

    def signed_in(self) -> bool:
        status, _, _ = self._get("/api/v1/users/self")
        return status == 200


@contextmanager
def portal_browser(client: TinyFishClient, profile_id: str, origin: str,
                   refresh_cookies: bool = True) -> Iterator[PortalBrowser]:
    # An agent run that is still using this profile locks it; wait for it rather than fail.
    for attempt in range(60):
        try:
            sess = client.start_setup_session(profile_id, url=origin + "/", timeout_seconds=900)
            break
        except TinyFishError as e:
            if "locked by an active run" not in e.message or attempt == 59:
                raise
            if attempt == 0:
                print("Your browser profile is busy with an agent run; waiting for it to finish …", flush=True)
            time.sleep(15)
    sid = sess["session_id"]
    saved = False
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(sess["cdp_url"], timeout=60_000)
            ctx = browser.contexts[0]
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            if not page.url.startswith(origin):
                page.goto(origin + "/", wait_until="domcontentloaded", timeout=60_000)
            page.set_default_timeout(60_000)
            pb = PortalBrowser(page, origin)
            if not pb.signed_in():
                raise ReauthRequired("AUTH_WALL", "saved profile is no longer signed in; run `gmdo setup`")
            yield pb
            # Keep the saved login fresh, but only while it is still valid. Best effort: the
            # remote browser may already have closed, and that must never fail an export.
            if refresh_cookies:
                try:
                    if pb.signed_in():
                        client.save_setup_session(profile_id, sid)
                        saved = True
                except Exception:
                    pass
    finally:
        if not saved:
            try:
                client.cancel_setup_session(profile_id, sid)
            except Exception:
                pass

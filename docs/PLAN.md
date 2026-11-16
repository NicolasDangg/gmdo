# Get My Data Out — plan to one-shot it

Bounty: Student Bounty Drop 002, "Get My Data Out" (assumed to close with the rest of Drop 002, Tue 17 Nov 2026 — confirm on the bounty page).
API facts live in `docs/SPEC.md` (verified against the OpenAPI). This file is the order of work.

## Constraints that shape everything

| Constraint | Consequence |
|---|---|
| Wallet $7.85, Agent $0.016/step (~490 steps total) | No exploratory agent runs. Map the portal for free first, then write tight goals. Hard step budget in code. |
| No signed-in profile yet | Step 1 is a human sign-in into a TinyFish Browser Context Profile. |
| Agent results are JSON only, no file output | Agent returns document links; bytes are fetched with the profile's cookies over the TinyFish setup-session CDP browser. |
| Cancelled/failed runs return nothing | Small date windows, one run each, state saved per window. |

## Why this can be one-shot

Most failed agent builds guess at the site. We remove the guessing before writing any agent code:

1. **Recon in the signed-in profile browser, not the agent.** While the user's setup session is open (Browser is $0.002/min), I drive it over CDP with Playwright and record: the billing-history URL, how pagination or date filters work, how many rows/pages exist, what a document link looks like (direct PDF, signed URL or cookie-gated), and any internal JSON the page calls. Output: `docs/RECON.md` (redacted).
2. **One golden run.** With the recon in hand, one agent run on the newest window with the real `output_schema`. Check row count and fields against what recon saw. Fix the goal once, then freeze it.
3. **Record that run as the test fixture** (redacted SSE stream + result), so the client, parser, state and export are tested offline against real data shape, not invented data.
4. **Backfill, then prove incremental.** Full history once; then a second run that returns 0 new rows (and a third after a new bill if timing allows).

Expected spend: golden run ~$0.30, backfill ~$1–2, incremental reruns ~$0.20 each, buffer for one retry. Fits the wallet with ~$4 spare.

## Decisions (16 Nov)

- **Portal: the user's school portal** (exact system and login URL still needed). A school portal has several sections behind menus, which scores well on difficulty: grades/marks, assignments and feedback, reports (PDFs), attendance, timetable. One adapter, one record type per section, each with its own stable key.
- Incremental: new or changed grades/assignments since the last export (key = portal id, else hash of course|title|date; changed marks are upserted and logged), new report PDFs by hash.
- **No password manager → no Vault.** Sign-in is profile-only; if the session expires, `gmdo setup` is rerun by hand. Endpoint #4 is `run-batch` (one run per section/term in parallel on the backfill).
- If the school signs in through Google or Microsoft, the user does that sign-in themselves in the setup session; the profile keeps the cookies.

- **16 Nov, after recon** (`docs/RECON.md`): it is Canvas LMS with Google SSO. The browser profile is saved and signed in; fresh sessions stay signed in and download files byte-exact. Records = one agent run per course Grades page via `run-batch` (43 courses); documents through the profile browser; per-course counts from the portal check completeness and pick which courses a rerun sends to the agent.

## Portal choice (the one decision only the user can make)

Must be: own account, 12+ months of history, downloadable bills/receipts, list with pagination or date filter, email+password login (an authenticator-app code is fine with Vault; SMS-only MFA means a manual refresh), no heavy bot wall.
Good: phone carrier, electricity/gas/water utility, ISP, school portal with reports.
Avoid: banks/brokerages (bot walls, judges' safety lens), Amazon (aggressive bot checks), Uber (hard login).

## TinyFish endpoints, each doing real work (4+ = 200 pts)

1. **Agent** `POST /v1/automation/run-sse` — the signed-in navigation and extraction, per date window, with `output_schema`, `use_profile`, `use_vault`; streams `streaming_url` for the demo.
2. **Browser Context Profiles** `POST /v1/profiles`, `/setup-session`, `/save` — password-free sign-in; the same session's CDP browser downloads the documents with the profile's cookies.
3. **Runs** `GET /v1/runs/{id}`, `GET /v1/runs` — resume after dropped streams/timeouts, error categories, run links for judges, `gmdo runs`.
4. **Vault** `GET /v1/vault/items`, `POST /v1/vault/items/sync` — unattended reruns re-log in when cookies expire (needs 1Password or Bitwarden). If no password manager: **`POST /v1/automation/run-batch`** for parallel date windows on the backfill takes this slot.

## Build order (timeboxed for one day)

| # | Step | Who | Done when |
|---|---|---|---|
| 0 | Pick portal; top-up decision | User | Portal named |
| 1 | `gmdo setup`: create profile, open setup session, user signs in, save | User + me | `signed_in_sites` lists the portal |
| 2 | Recon over CDP in that session | Me | `docs/RECON.md`, sample doc downloaded |
| 3 | Golden agent run on newest window | Me | Rows match recon, schema clean |
| 4 | Python package per SPEC §4 (client, auth, adapter, extract, documents, state, export, redact, cli) + tests on the recorded fixture | Me | `pytest` green |
| 5 | Backfill full history + documents | Me | `export/records.csv/json`, `documents/`, `manifest.json`, counts match portal |
| 6 | Rerun → 0 new rows; state proves it | Me | `manifest.json` shows `new: 0` |
| 7 | Landing page with product mockup (below) | Me | Light mode, deployed |
| 8 | Demo recording (blurred), run link made public, README explanation | User records, I script it | Submission checklist ticked |

## Landing page

Flow from the earlier bounties: reference sites → one extracted design file per site → build with `/design-taste-frontend` (light mode) → slop sweep → `/impeccable polish`.

- References: linear.app, hex.tech (plus 1–2 found by search) saved in `websites.md`, design files in `designs/`.
- Product mockup is the hero, built in HTML/CSS from the real redacted export, showing the TinyFish flow in order:
  1. Profile sign-in card ("Signed in once, in your own browser. No password stored.")
  2. Run timeline: window by window, live-view thumbnail, step count, run link
  3. Export table: consistent columns, document column with PDF chips
  4. Rerun panel: "Since 3 Nov: 1 new bill" and the state file's high-water mark
- Sections after the hero: how sign-in works (profile + vault), what you get (files), reruns, safety (what never leaves your machine), the CLI in three commands.
- Copy pass bans: "gaps", "Found X, never Y" constructions, "seamless", "effortless", "unlock", "supercharge", em-dash triplets, rhetorical "not X, but Y". Plain, specific sentences instead.
- Lives in `site/` (Next.js, static), separate from the Python tool.

## Submission checklist (maps to the brief)

- [ ] Real portal, own account, signed in through a TinyFish profile (and vault if available)
- [ ] `records.csv` + `records.json`, consistent fields, no duplicates, plus every document the portal holds
- [ ] Rerun picks up only what is new (shown, not claimed)
- [ ] Pagination/date windows handled; timeouts resume via `GET /v1/runs/{id}`
- [ ] No passwords in code or goals; `.env` holds only the API key and profile id; exports git-ignored; logs redacted
- [ ] Demo video with personal details blurred + public TinyFish run link
- [ ] Short write-up: which portal, how sign-in works, which endpoints and why

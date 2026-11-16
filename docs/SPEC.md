# Get My Data Out (`gmdo`) — Build Spec

Verified against https://agent.tinyfish.ai/v1/openapi/main (OpenAPI) and docs.tinyfish.ai/llms-full.txt.
Base URL `https://agent.tinyfish.ai`, auth header `X-API-Key: $TINYFISH_API_KEY` on every call. Python 3.11; deps: `httpx`, `pydantic`, `typer`, `playwright` (CDP only: setup + doc download), `pytest`, `respx`.

## 1. TinyFish API facts (verified)

### Run endpoints (all POST, same body except batch envelope)
`/v1/automation/run-sse` (stream), `/run` (sync; 200 `{run_id,status:COMPLETED|FAILED,started_at,finished_at,num_of_steps,result,error,profile_hint?}`), `/run-async` (200 `{run_id|null,error|null}`), `/run-batch` (`{runs:[{url,goal,...per-run fields}] (1..100), profile_id?, output_schema?}` → `{run_ids:[...]|null,error}`).
Body: `url`* (https), `goal`* (non-empty), `browser_profile` `lite|stealth`, `agent_config{mode:default|strict, max_steps 1-500 (default 150; BETA: non-enrolled key gets 403 FORBIDDEN), max_duration_seconds, cursor_style}` (additionalProperties false), `capture_config{elements,snapshots,screenshots,recording,html}`, `webhook_url` (https), `use_vault` bool, `credential_item_ids[]` (requires use_vault), `use_profile` bool, `profile_id` (requires use_profile; use_profile with no default profile → 400), `proxy_config{enabled*,country_code}`, `output_schema`, `api_integration`.
`output_schema` rules: top level must be an object (no top-level anyOf), ≤64KB, depth ≤10, `nullable:true` (not `type:[x,"null"]`), a list must be an array field (`{"records":{"type":"array",...}}`) or only one item returns; schema beats prompt; keep data fields optional (required fields get hallucinated placeholders); `propertyOrdering` supported.

### SSE events (`data: {json}` lines)
- `STARTED {type,run_id,timestamp}`: persist run_id immediately.
- `STREAMING_URL {run_id,streaming_url}`: live view (use for demo).
- `PROGRESS {run_id,purpose,tinyfish_api?}`, `TF_API_RESULT`, `HEARTBEAT {timestamp}`.
- `COMPLETE {run_id,status:COMPLETED|FAILED|CANCELLED,result:object|null,error:string?,help_url?,help_message?,profile_hint?{message,setup_url,reason:auth_wall|bot_challenge},timestamp}`. CLI docs also show `run_url` in COMPLETE and `result` as `{"result":"<json string>"}`: parser must accept both and `json.loads` string values. Stream drop before COMPLETE → poll `GET /v1/runs/{id}` (run continues server-side).

### Runs
`GET /v1/runs/{id}?screenshots=url|base64|none&html=url|none` → `{run_id,status:PENDING|RUNNING|COMPLETED|FAILED|CANCELLED,goal,created_at,started_at,finished_at,num_of_steps,result,output_schema,profile_attached,profile_id,error{code,message,category:SYSTEM_FAILURE|AGENT_FAILURE|BILLING_FAILURE|UNKNOWN,retry_after,help_url,help_message,profile_hint},profile_hint,streaming_url,browser_config,video_url (presigned, 15 min),steps[{id,timestamp,status,action,screenshot,html}]}`.
`GET /v1/runs?status&goal&created_after&created_before&sort_direction&cursor&limit(1-100,def 20)&owner=me|team` → `{data:[run...], ...}`; pagination cursor key not confirmed in trimmed schema: read `next_cursor`/`cursor`/`pagination.next_cursor` defensively and verify on a live call.
`POST /v1/runs/{id}/cancel`, `POST /v1/runs/batch` (get many by ids), `POST /v1/runs/batch/cancel`, `GET /v1/runs/{id}/steps/{stepId}/screenshot|html`.
**Public run link for judges:** `https://agent.tinyfish.ai/runs/{run_id}` (`run_url` in CLI docs). Sharing is owner-controlled in the dashboard: enable it, then verify in a logged-out window.
Error codes: MISSING_API_KEY, INVALID_API_KEY, INVALID_INPUT, RATE_LIMIT_EXCEEDED (honor `Retry-After`), DAILY_LIMIT_EXCEEDED, INTERNAL_ERROR, RETRY_REQUIRED, VAULT_RECONNECT_REQUIRED, FORBIDDEN, NOT_FOUND, SERVICE_BUSY, TIMEOUT, INSUFFICIENT_CREDITS, SITE_BLOCKED, TASK_FAILED, MAX_STEPS_EXCEEDED, CANCELLED. Retry: 429, 5xx, SYSTEM_FAILURE, UNKNOWN, SERVICE_BUSY, TIMEOUT. Never retry AGENT_FAILURE, BILLING_FAILURE, INVALID_INPUT. A cancelled run has `result:null` (no partial data), so use small windows.

### Browser Context Profiles (not the same as `browser_profile`)
- `POST /v1/profiles {name*(≤100),set_as_default?,proxy_country_code?}` → `{id,name,is_default,fingerprint_seed,domain_count,signed_in_sites[{site,claimed_at}],domains[...],created_at,updated_at}`; `GET /v1/profiles` → `{profiles:[...]}`; GET/PATCH/DELETE `/v1/profiles/{id}`; `DELETE /v1/profiles/{id}/domains/{domain}`.
- `POST /v1/profiles/{id}/setup-session {url?,timeout_seconds 5..86400}` → **201** `{session_id,cdp_url (wss; Playwright connect_over_cdp),base_url (HTTPS; only /pages),timeout_seconds,expires_at}`.
- `POST /v1/profiles/{id}/save {session_id*,signed_in_sites?[≤20]}` → `{domains_updated,domains_failed,cookie_count,domains_skipped{...},sign_in{site,status:recorded|already_recorded|not_detected|unverifiable}}`. `POST .../setup-session/cancel {session_id}` → `{cancelled}`. Unsaved state is discarded at expiry.
- `POST /v1/profiles/{id}/upload {cookies[≤3000],localStorage[≤100],sessionStorage}` imports state.
- Run with `use_profile:true, profile_id:"..."`. Sites may still expire cookies or force MFA.

### Vault
`POST /v1/vault/connections {provider:1password|bitwarden, token | clientId/clientSecret/masterPassword, serverUrl?}` → `{connectionId,connected,provider,items[]}`; `GET /v1/vault/connections` → `{connections:[{id,provider,connectionStatus,lastValidatedAt}]}`; `DELETE /v1/vault/connections/{id}`; `GET /v1/vault/items` → `{items:[{itemId,connectionId,label,vaultName,domains[],fieldMetadata[{fieldId,label,type:STRING|CONCEALED|OTP}],hasTotp}]}`; `POST /v1/vault/items/sync` → `{items,sync_summary{added,updated,removed}}`. Run with `use_vault:true, credential_item_ids:[itemId]`; TOTP supported (`hasTotp`). Expired connection → `VAULT_RECONNECT_REQUIRED`. Docs: pair profile + vault so TinyFish re-logs-in when cookies expire.

### Other hosts (same key)
Fetch `POST https://api.fetch.tinyfish.ai/ {urls[≤10],format,...}` → `{results[{url,final_url,title,text,...}],errors[]}`: public URLs only; PDF → extracted text; binary files error. Browser API `POST https://api.browser.tinyfish.ai/ {url,timeout_seconds,proxy_config}` → 201 `{session_id,cdp_url,base_url}`; no profile field.
**Files: no documented agent download/attachment output.** Agent results are JSON only; documents are handled outside the result (see documents.py).

## 2. Endpoints used meaningfully (4+ = 200 pts)
| # | Endpoint | Why needed (not padding) |
|---|---|---|
| 1 | `POST /v1/automation/run-sse` | Core: signed-in navigation of menus/pagination per date window; `output_schema` records + document links; SSE gives run_id, streaming_url, heartbeats. |
| 2 | `POST /v1/profiles`, `/setup-session`, `/save` | Password-free sign-in: user logs in once by hand (incl. MFA) in the CDP browser; every run uses `use_profile`. |
| 3 | `GET /v1/runs/{id}` and `GET /v1/runs` | Resume after dropped SSE/timeouts, classify `error.category`/`profile_hint`, store `steps`/`video_url`; `gmdo runs` reconciles orphaned runs via `created_after`. |
| 4 | `GET /v1/vault/items` + `POST /v1/vault/items/sync` (+`use_vault`, `credential_item_ids`) | Unattended re-run survives cookie expiry (auto re-login with TOTP); `gmdo setup` verifies a vault item matches the portal domain. |
| 5 optional | `POST /v1/automation/run-batch` | Parallel independent date windows (≤100) for long histories. Do not add Fetch/Browser/research just to inflate count. |

## 3. Bounty checklist → features
| Requirement | Feature |
|---|---|
| Real portal, own account, signed in | One real adapter (utility/phone bill portal the author uses, `portals/utility_bills.py`); sign-in by profile, Vault fallback; `.env` holds only `TINYFISH_API_KEY`, `GMDO_PROFILE_ID`, optional `GMDO_VAULT_ITEM_ID`; no passwords in code or goals (docs: passwords in goals leak into logs). |
| Complete structured export | `export/records.csv`, `records.json`, `records.ndjson`: fixed column order from adapter schema, ISO-8601 dates, amount as decimal string + `currency`, `null` not "", UTF-8, `schema_version`, `source_run_id`, `exported_at`. Pydantic-validate each record; bad ones to `export/rejected.jsonl`. `manifest.json` has counts and run links. |
| Documents | `documents/<YYYY>/<record_key>.<ext>` + `documents.csv` (record_key, doc_url, path, sha256, bytes, content_type, status); `records.document_path` column. |
| Incremental re-run | `state.json`: per-portal `high_water_mark` (max date), `seen_keys`, `doc_hashes`, per-window status. Key = portal's stable id, else sha1(date|amount|description). Re-run starts at `hwm − 7d` overlap, dedupes by key, upserts changed rows (logged). Atomic write (tmp + rename) + file lock. |
| Pagination / date ranges / long histories | `windows(since, until)` yields month/quarter windows; goal: "page through ALL pages until no Next; return page_count, reached_end, total_rows_reported". Per-window `max_duration_seconds`; if `reached_end:false`, MAX_STEPS_EXCEEDED or row_count mismatch, bisect the window and retry. |
| Timeouts / retries / resume | Backoff+jitter on retryable codes; SSE idle >90 s → poll `GET /runs/{id}`; window states `pending/running(run_id)/done/failed` in state.json so `gmdo export --resume` re-attaches instead of re-paying. |
| Personal-data safety | `redact.py` masks account no./address/email/phone in logs, run dumps and demo artifacts; `--redact` hashes PII columns; `.gitignore`: `.env`, `state.json`, `export/`, `documents/`, `*.log`, `.gmdo/`; no cookies/credentials logged; own account only, ToS note in README, sequential runs with delays. |
| Demo + run link | `gmdo export --demo` prints `streaming_url` and `https://agent.tinyfish.ai/runs/{id}` per run and writes `runs.md`. Screen-record with blur over personal details; ship a blurred sample in `examples/`. |
| Short explanation | README: portal, profile + vault sign-in, endpoint table, incremental logic. |

## 4. Architecture (package `getmydataout/`)
- `client.py`: `TinyFishClient(httpx.Client)` with `run_sse(req)->Iterator[Event]` (parses `data:` lines, ignores HEARTBEAT), `run_to_completion(req)` (SSE; on drop poll `get_run`), `get_run`, `list_runs` (cursor loop), `cancel_run`, `run_batch`; `profiles.create/list/setup_session/save/cancel`; `vault.connections/items/sync`. `TinyFishError(code,status,category,retry_after)`; retry decorator honoring `Retry-After`.
- `auth.py`: `setup_profile(name, login_url)`: create profile → setup-session → Playwright `connect_over_cdp(cdp_url)` → user logs in → Enter → `/save` → write profile id to `.env`. `check_vault(domain)`. `auth_kwargs()` → `{use_profile, profile_id, use_vault, credential_item_ids}`. `profile_hint.reason=="auth_wall"` → raise `ReauthRequired(setup_url)`.
- `portals/base.py`: `PortalAdapter(ABC)`: `name,start_url,domain`; `windows(since,until)`; `build_goal(window)`; `output_schema()` (object: `records[]`, `page_count`, `reached_end`, `total_rows_reported`; all data fields optional/nullable); `record_key(rec)`; `normalize(rec)`; `document_urls(rec)`. `portals/utility_bills.py`: Account → Billing history → date filter → paginated table → per-row "View bill".
- `extract.py`: per window runs the goal with `agent_config{max_duration_seconds}` (`max_steps` only if enrolled; drop on 403), `browser_profile:"stealth"` if configured; persists run_id/run_url before and after; schema-validates; bisects on incomplete.
- `documents.py`: tier 1: direct/pre-signed HTTPS URL from agent → httpx stream, check `%PDF`/content-type, sha256, skip known hashes. Tier 2 (auth-gated links): Playwright over a profile setup-session CDP browser using `page.request.get(url)`; must verify the setup browser actually carries saved state, else tier 3. Tier 3: agent opens the bill and returns its full text → saved as sidecar JSON/TXT with `status:"text_only"`. Never report a PDF that was not downloaded.
- `state.py`: dataclasses + JSON; `high_water_mark`, `seen_keys`, `doc_hashes`, `windows{id:{status,run_id,attempts}}`, `last_export_at`.
- `export.py`: merge into key-unique, sorted records; consistent flat columns; CSV/JSON/NDJSON + manifest.
- `redact.py`: mask helpers, `redact_record`, logging `RedactingFilter`.
- `cli.py` (typer, `gmdo`): `setup`; `export [--since --until --full --resume --redact --no-docs --demo]`; `status` (hwm, counts, pending windows, last runs); `runs [--limit]`.
- Tests (pytest + respx, no network): SSE parser (STARTED/COMPLETE, string-wrapped result, mid-stream drop → poll), retry on 429/5xx, error-category handling, window bisect, second run adds 0 rows, state atomicity, golden CSV/JSON, doc hash dedupe, redaction, CLI via `CliRunner`.
- Also: `pyproject.toml` (script `gmdo = getmydataout.cli:app`), `.env.example`, `.gitignore`, `README.md`.

## 5. Open risks
- **File downloads**: no documented agent file output; documents rely on tiers 1–3. Biggest completeness risk: probe the real portal first (direct URL? cookie-gated?).
- **CAPTCHA/bot checks**: `SITE_BLOCKED` / `profile_hint.reason=bot_challenge`; mitigate with `stealth` + `proxy_config` + profile with real history; user may solve interactively in setup session.
- **MFA / expiry**: Vault TOTP covers some portals; SMS MFA needs a manual `gmdo setup` refresh.
- `max_steps` is beta-gated (403); rely on `max_duration_seconds` and small windows.
- LLM extraction accuracy: schema, row-count cross-check, repeat-window spot check.
- Cancelled/failed runs return no partial data; `GET /v1/runs` cursor key unconfirmed; run-sharing toggle is manual; concurrency/credit limits (keep sequential by default).

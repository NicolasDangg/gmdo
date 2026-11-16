# gmdo: get my data out of Canvas

Page: https://gmdo-ten.vercel.app · Notes for reviewers: [REVIEWERS.md](REVIEWERS.md)

My school runs its coursework on Canvas LMS (`lms.vinschool.edu.vn`). Students get no export: grades,
assignment history and the files you handed in live behind a Google sign-in and a dozen course menus.
`gmdo` signs in as me through a TinyFish browser profile, has the TinyFish Agent read every course's
Grades page, checks each run against what Canvas itself reports, and writes clean CSV and JSON plus the
documents. Run it again later and it only touches courses that changed.

```bash
gmdo setup                                        # sign in once, by hand, in a TinyFish browser
gmdo export --terms "2025-2026,2026-2027"         # first run: everything in those school years
gmdo export --terms "2025-2026,2026-2027"         # later runs: only what changed
gmdo showcase                                     # shareable copy with every name removed
```

## How TinyFish is used

| Step | TinyFish endpoint | What it does here |
|---|---|---|
| Sign-in | `POST /v1/profiles`, `POST /v1/profiles/{id}/setup-session`, `POST /v1/profiles/{id}/save` | `gmdo setup` opens a TinyFish browser on the portal. I sign in myself (Google SSO); the profile keeps the cookies. No password is typed into, stored by, or sent through this tool. |
| Reading the portal | `POST /v1/automation/run-batch` | One agent run per course, started on that course's Grades page with `use_profile`. It clicks "Show All Details", scrolls the whole table and returns every row against a fixed `output_schema`. All changed courses go in one batch. |
| Waiting, resuming, retrying | `GET /v1/runs/{id}`, `GET /v1/runs` | Polls each batch run to the end, records steps and the run link, and resumes runs already in flight after a crash instead of paying again. A course that comes back short is retried once with `POST /v1/automation/run-sse`. |
| Files and checks | profile setup-session over CDP | The same signed-in profile browser lists courses, reads the counts and timestamps Canvas reports, and downloads documents byte for byte. |

The agent reads what a student sees. The profile browser reads the same data feed the page itself loads,
which is how every run gets checked: the export says, per course, how many rows the agent returned against
how many assignments Canvas lists, and whether each score matches.

## What you get

```
export/
  records.csv / .json     one row per assignment: course, term, name, group, due and submitted
                          (as displayed and ISO-8601), status, score, out of, late/missing/excused,
                          teacher comments, whether the score matched Canvas, the run that read it
  courses.csv / .json     every course, term, course total, rows read vs portal count, run link
  documents.csv / .json   every file: kind, course, size, sha256, local path, status
  changes.ndjson          what each rerun added, changed (field by field) or saw removed
  manifest.json           counts, run links, agent steps and cost, score checks
documents/
  own/ submission/ course/   the files themselves
```

- Stable keys: `canvas:<course_id>:<assignment_id>` for records, `canvas:file:<file_id>` for documents.
  A rerun never duplicates a row; a changed grade updates the row and is logged in `changes.ndjson`.
- Fixed column order, `null` for anything the portal does not show, UTF-8, `schema_version` in every JSON file.
- When Canvas shows no number (e.g. a quiz still in `pending_review`), the export keeps it blank and records
  the portal state instead of inventing a score.

## Results on my account (16 Nov 2026)

| | |
|---|---|
| Scope | school years 2025-2026 and 2026-2027: 26 courses with assignments (2024-2025 is listed in `courses.csv` as not selected) |
| Records | 743 assignment rows, every course matching the count Canvas reports |
| Scores | 666 checked against Canvas and matching; 16 rows in 2 courses flagged `score_verified: false` (the page read showed no score where Canvas holds one), left flagged rather than hidden |
| Documents | 58 files, 140 MB: my uploads and submission attachments, sizes checked byte for byte |
| Agent | first export about $4.50 (2 runs at a time, batches of up to 18), fixes about $0.70, a quiet rerun $0.00 |

## Reruns pick up only what's new

Before any agent run, `gmdo` fingerprints each course from the portal feed (assignment and submission
timestamps, grades, states). Only courses whose fingerprint changed, or whose last run was incomplete, go to
the agent. Documents are skipped when their id, size and timestamp are unchanged. State lives in
`state.json` (written atomically).

## Long histories, timeouts, failures

- One run per course keeps each run short (`max_duration_seconds: 300`); a failed or cancelled run loses one
  course, not the export.
- Runs are saved to `state.json` the moment they are submitted, so `gmdo export` after a crash re-attaches
  to them.
- 429/5xx responses back off and honour `Retry-After`; agent and billing failures are not retried blindly.
- A cost estimate prints before any agent run, and `--budget` stops the run if it would cost more.
- If the saved sign-in expires, `gmdo` stops with "run `gmdo setup`" rather than exporting a sign-in page.
- Batches stay under the account's queue limit (20 pending runs on a 2-run plan): `gmdo` keeps 18 queued
  and tops up as runs finish.
- A run that comes back short is read once more. A long table that comes back nearly empty is re-read in
  windows of 50 rows and the windows are merged.
- Before paying for a new run, `gmdo` re-checks the course's earlier runs (alone and combined) against
  today's Canvas data; matching improvements alone fixed five courses without a new run.
- An unchanged course that is still short after two exports is not retried on every rerun; it stays marked
  incomplete in `courses.csv` with the missing assignments in `manifest.json`, and `--full` tries again.
- If an agent run is still using the browser profile, `gmdo` waits for it instead of failing.
- Portal requests inside the browser time out after 30 seconds instead of hanging.

## How rows are matched to Canvas

The agent copies each row's assignment id from its link when it can. When it cannot, `gmdo` matches the
row to Canvas's own list: exact name; repeated names paired by points and due date; names the Grades page
shortens with "…" or cuts off; then a near-identical spelling. Every row records how it was matched.
Items Canvas does not show on the Grades page (ungraded, no points) are not expected there. Scores are
compared at the precision the page shows (4.67 against 4.6666…), and a score Canvas holds but has not
released to the student (pending review, not posted) is never counted as a mismatch.

## Personal data

- Only my own account, read-only: the agent goal forbids submitting or changing anything.
- `.env` holds the profile id and portal URL only; the API key comes from the shell. `export/`,
  `documents/`, `state.json` and `.env` are git-ignored.
- Logs and errors pass through a filter that masks emails, phone numbers, API keys and signed download tokens.
- `gmdo showcase` writes a copy for demos: course names become plain subjects ("Mathematics · Grade 12"),
  teacher handles, class and campus codes are dropped, names are replaced with `[student]`/`[teacher]`
  (accented and unaccented, either order, inside file names), comments become a count, local paths are
  removed. It then searches every file it wrote for those names and deletes the copy if one survived.
  The list of names is read live from the portal and never written to disk.
- TinyFish run pages contain real screenshots of the portal, so run links are shared with the judges only.

## Tests

`pytest` runs offline against recordings of real runs (names and scores replaced): SSE parsing, dropped
streams, retries, batch envelopes, completeness checks, score parsing, fingerprints, export columns,
atomic state, redaction and the showcase leak check.

## Setup

```bash
uv venv && uv pip install -e '.[dev]'
export TINYFISH_API_KEY=...        # from the TinyFish dashboard
.venv/bin/gmdo setup
```

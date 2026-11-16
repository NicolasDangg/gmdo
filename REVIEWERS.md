# Notes for reviewers

**What it is.** `gmdo` exports a student's Canvas LMS data (grades, assignments, submitted files), which Canvas does not let students download. Tested on my own school account (Google SSO).

**Where TinyFish is used** (`getmydataout/client.py`, `extract.py`, `session.py`)
- Profiles: `gmdo setup` creates a profile and a setup session; I sign in by hand and save. No password anywhere.
- Agent: one run per course on its Grades page, `use_profile`, fixed `output_schema`, read-only goal. Sent via `run-batch`, kept under the 20-run queue limit; empty long tables re-read in 50-row windows via `run-sse`.
- Runs API: follows each run, re-attaches after a crash, re-checks earlier runs before paying again.
- The profile's browser (CDP) reads Canvas's own counts and downloads documents.

**How to check it in 5 minutes**
1. `pytest` runs 33 offline tests on scrubbed recordings of real runs.
2. `README.md` → "Results": 26 courses, 743 rows, every course matching Canvas, 58 files, rerun $0.00.
3. `getmydataout/portals/canvas.py` → `resolve_ids` and `verify`: how rows are matched and scores checked.
4. `extract.py` → `run()`: inventory, change fingerprints, batched runs, checks, merge.
5. The TinyFish run link is in the submission form (real screenshots, so not in the repo).

**Export shape.** `records.csv/json` one row per assignment, key `canvas:<course>:<assignment>`; `courses.csv` rows read vs Canvas count; `documents.csv` with sha256; `changes.ndjson`; `manifest.json` with run links and cost.

**Honest limits**
- Scope is two school years; the third is listed as not selected.
- 16 rows in 2 courses are flagged `score_verified: false` (blank on the page, released in Canvas). Left visible on purpose.
- Built for Canvas; the adapter is one file.

**Privacy.** Exports, documents and state are git-ignored. `gmdo showcase` strips names, classes and comments; the landing page uses only that copy.

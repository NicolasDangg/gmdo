# Recon: Vinschool LMS (16 Nov 2026)

Mapped over CDP inside the signed-in TinyFish profile setup session (profile `gmdo-vinschool-lms`). No agent steps spent. Counts only; no names, emails or grades of record kept here.

## Platform

- `lms.vinschool.edu.vn` is **Canvas LMS** (Instructure hosted, `x-canvas-meta` header). Login redirects to `online.vinschool.edu.vn` (Cloudflare) and the student signs in with **Google SSO**.
- Profile save: 55 cookies across vinschool.edu.vn, google.com, canvaslms.com. A **fresh** session on the profile lands on the dashboard signed in, and `page.request.get(file.url)` returns the exact bytes (PDF, 1,752,349 B, `%PDF-` header). So documents can be downloaded through TinyFish's own browser with the saved profile, no password involved.
- Global nav: Dashboard, Courses, Calendar, Inbox, plus school tools (CLISE, Timetable, SWB) as LTI launches (out of scope: separate apps).

## What the portal holds for this student

| Source | Count | Notes |
|---|---|---|
| Courses | 43 (41 readable, 2 restricted by date) | 3 school years: 2024-2025 (grade 10), 2025-2026 (grade 11), 2026-2027 (grade 12, active) |
| Assignments | 1,168 | many ungraded/practice; 2024-2025 shows no scores (hidden after the year closed) |
| Graded submissions | 187 | score + course total visible on each course's Grades page |
| Submissions with attachments | 33 | the student's own uploaded work |
| Own files (`/users/self/files`) | 58 | |
| Course files (teacher material) | 1,780 | 8 courses return 403 (Files tab hidden) |
| Announcements | 34 | |
| Modules | 419 | structure only |
| Inbox conversations | 3 | |
| Calendar events | 0 | |

Pagination: Canvas lists page with `Link: <…>; rel="next"`, 100 per page max. Grades page per course is one long table (no paging), which suits one agent run per course.

## What this means for the build

- **Unit of work = one course.** One agent run per course on `/courses/{id}/grades` (direct start URL, so no menu-walking steps wasted) returns assignments, due dates, status, score, out-of, and teacher comments. 43 runs through `run-batch`.
- **Course list** comes from one agent run on `/courses` (all terms, past enrolments).
- **Completeness check:** the profile browser reads the counts Canvas itself reports per course; the manifest prints agent rows vs portal count per course and re-runs any course that does not match.
- **Documents** (own files, submission attachments, announcement attachments, course files) download through the profile browser, sha256 deduped.
- **Reruns:** compare per-course counts and `updated_at` first (free), then send only changed courses to the agent. Active term = 13 courses.
- Budget: ~3–4 steps per course run → ~130–170 steps (~$2–2.75) for the backfill; a rerun with 2–3 changed courses ~$0.20.

# Landing page notes (design-taste-frontend run)

References (user's choice): linear.app (tight left-aligned grotesk headline, real product UI as the
framed hero object, plain nav, statement in ink + grey continuation), hex.tech (warm off-white paper
ground, heavy display face, overlapping product windows as the mockup). Light mode.

Reading: a page for a free, open CLI. Audience: students and developers who know their LMS has no
export button, and the TinyFish bounty judges. One job: show it working, send people to the repo.

## Inventory (belongs to gmdo and nothing else)
1. The name is the command: `gmdo` = get my data out. You type it.
2. The portal: Canvas LMS at a Vietnamese school, Google SSO sign-in, no student export.
3. Real numbers: 43 courses over three school years, 1,168 assignments, 187 graded, 58 of your own files,
   1,780 teacher files; golden run 22 of 22 rows in 6 steps; agent step $0.016; unchanged course $0.
4. The output files: records.csv, courses.csv, documents.csv, manifest.json, changes.ndjson, documents/.
5. The record key: `canvas:37598:2060378` (course : assignment). Never written twice.
6. The check: "22 rows read, Canvas lists 22". score_verified. pending_review left blank, not guessed.
7. The ritual: sign in once by hand, batch of runs, check, files, rerun with fingerprints.
8. The world's printed thing: the school report / transcript the portal never hands you.
9. Bilingual subjects: Toán, Ngữ Văn, Lịch Sử next to A-Level Computer Science.
10. The TinyFish run link and live view.
11. Redaction tokens: [student], [teacher], "[2 comments hidden]".

## Argument (one claim per section)
1. gmdo gets every grade, assignment and file out of Canvas      → hero: terminal + export windows
2. You sign in once, yourself; no password reaches the tool        → profile sign-in window
3. One agent run per course, checked against Canvas's own count   → run list: rows read vs listed
4. The files open anywhere: CSV, JSON, the documents              → records.csv table + folder tree
5. Run it again and it reads only what changed                     → rerun diff, cost of unchanged = $0
6. Personal data stays yours; the showcase strips every name      → before/after redaction row
7. Three commands to start                                         → code block, repo button

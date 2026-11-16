# Copy deck

Idea: On this page, **the tool's own name, "get my data out", which is the command you type**, becomes
**the headline across two fields: "data out" rising out of the portal's field below.**
Competitor test: another exporter is not named for the act; the sentence fails for it.

Live thing: the command line in the showcase. Type or pick a `gmdo` command; under it, what that
command would do to the real (redacted) export: which courses go to the agent, steps, cost, files.

## Nav
gmdo · How it works · Files · Questions · [Get the code]

## Hero
Get my / data out
Sub: A command-line tool that signs in to your school's Canvas and saves every grade, assignment and
file you have there, with a TinyFish agent doing the clicking.

## Showcase (headline is an input)
[gmdo export --dry-run]
Answer rows (real, from the export manifest)
Examples: gmdo export · gmdo export --full · gmdo showcase

## How it works — "Three commands"
First, sign in yourself.          call: gmdo setup         → TinyFish browser window, signed in, no password stored
Then export.                      call: gmdo export --terms 2025-2026,2026-2027 → batch run list, rows read vs listed
Then open what it wrote.          call: open export/records.csv → records table, wide

## Pictures
None, by the user's decision (16 Nov): the page is type and real interface fragments only.

## Features — sentences with switches (the real flags)
Download the files you handed in.     on  → n files, x MB, every one checked byte for byte
Include your teachers' course files.  off → 1,780 more files, about 3.3 GB
Read only the courses that changed.   on  → unchanged courses never reach the agent and cost $0
Start again from scratch.             off → every course re-read: 26 runs, about $4.40
Hide the scores in the showcase.      off → names are always removed; this blanks the marks as well

## Proof — "Every course / checked"
table: school year | subject | rows read / Canvas lists | result

## Questions
(items in the page; see index.html)

## CTA band
Clone → "The code, tests and setup guide are on GitHub."

## Footer
notes: Built for the TinyFish "Get My Data Out" bounty · Python 3.11+ · Back to top
display line: gmdo export
meta: README · Tests | photo credits | 2026

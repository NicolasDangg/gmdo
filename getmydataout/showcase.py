"""Make a shareable copy of an export with every personal detail removed.

The real export (export/, documents/) never changes. The showcase copy:
- replaces course names with a plain subject label ("Mathematics · Grade 12"),
  dropping teacher handles, class and campus codes;
- redacts the student's and teachers' names, handles, logins and emails wherever
  they appear (assignment titles, file names), in accented and unaccented forms;
- hides teacher comments (keeps only how many there were);
- strips local paths and signed links;
- optionally hides scores;
- then scans every file it wrote for any of those terms and refuses to finish
  if one is found.

The list of names is built live from the signed-in portal and only kept in memory.
"""
from __future__ import annotations

import json
import re
import shutil
import unicodedata
from pathlib import Path

from . import export as ex
from .portals import canvas
from .redact import EMAIL, VERIFIER, mask_phones

# Syllables too common in Vietnamese words to redact on their own (e.g. "Văn" in "Ngữ Văn",
# "Anh" in "Tiếng Anh"). Full names that contain them are still redacted.
COMMON = {
    "nguyen", "tran", "le", "pham", "hoang", "huynh", "phan", "vu", "vo", "dang", "bui", "do", "ho",
    "ngo", "duong", "ly", "thi", "van", "duc", "ngoc", "minh", "anh", "thanh", "hong", "lan", "mai",
    "hoa", "hai", "nam", "son", "an", "binh", "hung", "long", "quang", "trung", "tuan", "viet",
    "kim", "my", "ha", "thu", "linh", "huong", "phuong", "tam", "the", "and", "mr", "ms", "mrs",
}
KEYWORDS = {"THPT", "ESL", "MATHS", "MATHEMATICS", "PHYSICS", "CHEMISTRY", "A", "LEVEL", "AS",
            "COMPUTER", "SCIENCE", "LMS", "HARMONY", "THE", "GL", "IT", "PE"}
HANDLE = re.compile(r"^[A-Z]{3,}\d*$")

SUBJECTS = {
    "IT": "Information Technology", "MIL": "Defence and Security", "CAM.ESL": "English (ESL)",
    "CLISE": "Life Skills", "PE": "Physical Education", "CAREER": "Careers and Experiences",
    "HIS": "History", "NV": "Vietnamese Literature", "LOCE": "Local Studies", "VNS": "Vietnam Studies",
    "PHY": "Physics", "MATHS": "Mathematics", "GEO": "Geography", "AS.PHY": "AS Physics",
    "AS.CHEM": "AS Chemistry", "AS.CS": "AS Computer Science", "AS.NV": "AS Vietnamese Literature",
    "CAM.MATHS": "Cambridge Mathematics", "AS.MATHS": "AS Mathematics",
}


def fold(s: str) -> str:
    """Lowercase, strip accents (đ -> d) so 'Nguyễn' and 'nguyen' match."""
    s = unicodedata.normalize("NFD", s.replace("đ", "d").replace("Đ", "D"))
    return "".join(ch for ch in s if unicodedata.category(ch) != "Mn").casefold()


# ---------------------------------------------------------------- labels
def subject_label(course: dict) -> str:
    code, name = course.get("course_code") or "", course.get("course_name") or ""
    m = re.match(r"^THPT\.\w+-([A-Z.]+)-(\d{2})$", code)
    if m:
        return f"{SUBJECTS.get(m.group(1), m.group(1).title())} · Grade {m.group(2)}"
    m = re.match(r"^[A-Z]+\d*-(.+?)-(\d{2})-THPT", code)
    if m:
        return f"{english_subject(m.group(1))} · Grade {m.group(2)}"
    if name and not handles_from_courses([course]) and not re.search(r"\d{2}[A-Z]\d|THPT", name):
        return name                                  # a plain title with no handle, class or campus in it
    return f"Course {course.get('course_id')}"


# Vietnamese subject names as Canvas shows them -> English, so a showcase reads anywhere.
VI_SUBJECTS = {
    "toan": "Mathematics", "ngu van": "Vietnamese Literature", "lich su": "History",
    "dia ly": "Geography", "dia li": "Geography", "hoa hoc": "Chemistry", "vat ly": "Physics",
    "vat li": "Physics", "sinh hoc": "Biology", "tieng anh": "English",
    "cong nghe thong tin": "Information Technology", "tin hoc": "Information Technology",
    "giao duc the chat": "Physical Education", "giao duc quoc phong - an ninh": "Defence and Security",
    "an ninh quoc phong": "Defence and Security",
    "hoat dong trai nghiem, huong nghiep": "Careers and Experiences",
    "noi dung giao duc cua dia phuong": "Local Studies", "noi dung giao duc dia phuong": "Local Studies",
    "mathematics": "Mathematics", "computer science": "Computer Science",
}


SUBJECT_WORDS = {fold(w) for text in list(SUBJECTS.values()) + list(VI_SUBJECTS.values()) + list(VI_SUBJECTS)
                 for w in re.split(r"[\s,()-]+", text) if w} | {
    "department", "team", "teachers", "teacher", "admin", "subject", "group", "level", "a-level", "as", "and"}


def english_subject(raw: str) -> str:
    raw = raw.strip()
    level = ""
    if fold(raw).startswith("a-level "):
        level, raw = "A-Level ", raw[8:].strip()
    return level + VI_SUBJECTS.get(fold(raw), raw.title())


def handles_from_courses(courses: list[dict]) -> set[str]:
    out = set()
    for c in courses:
        for field in ("course_code", "course_name"):
            for seg in re.split(r"[-\s]+", c.get(field) or ""):
                if HANDLE.match(seg) and seg not in KEYWORDS and not seg.startswith("THPT") \
                        and fold(seg) not in SUBJECT_WORDS:
                    out.add(seg)
    return out


# ---------------------------------------------------------------- name list
def collect_terms(pb, courses: list[dict]) -> dict[str, str]:
    """term -> replacement label. Built live from the portal, never written to disk."""
    terms: dict[str, str] = {}

    def add_name(full: str | None, label: str):
        if not full:
            return
        full = re.sub(r"\s+", " ", full.replace(",", " ")).strip()
        parts = full.split(" ")
        if all(fold(p) in SUBJECT_WORDS for p in parts):
            return                                   # a shared account named after its subject, not a person
        variants = {full, " ".join(reversed(parts))}
        if len(parts) > 1:
            variants |= {f"{parts[-1]} {parts[0]}", f"{parts[0]} {parts[-1]}"}
        for v in list(variants):
            variants |= {v.replace(" ", "_"), v.replace(" ", ""), v.replace(" ", ".")}
        for v in variants:
            if len(v) >= 4:
                terms[v] = label
        for p in parts:
            if len(p) >= 3 and fold(p) not in COMMON:
                terms["=" + p] = label      # single words match with exact accents: Nhung ≠ những

    me = pb.get_json("/api/v1/users/self") or {}
    prof = pb.get_json("/api/v1/users/self/profile") or {}
    for k in ("name", "short_name", "sortable_name"):
        add_name(me.get(k), "[student]")
    for k in ("login_id", "primary_email", "sis_user_id", "integration_id"):
        v = prof.get(k) or me.get(k)
        if v and len(str(v)) >= 4:
            terms[str(v)] = "[student]"
            if "@" in str(v):
                terms[str(v).split("@")[0]] = "[student]"
    raw = pb.get_all("/api/v1/courses?per_page=100&enrollment_state=all&state[]=available"
                     "&state[]=completed&include[]=teachers") or []
    for c in raw:
        for t in c.get("teachers") or []:
            add_name(t.get("display_name"), "[teacher]")
    for h in handles_from_courses(courses):
        terms[h] = "[teacher]"
    return terms


class Redactor:
    """Terms starting with '=' match with exact accents (single name words); all others
    (full names, handles, logins) match accent-insensitively."""
    B = r"(?<![0-9a-zà-ỹđ])"
    E = r"(?![0-9a-zà-ỹđ])"

    def __init__(self, terms: dict[str, str]):
        items = []
        for t, lab in terms.items():
            exact = t.startswith("=")
            t = t[1:] if exact else t
            if t:
                items.append(((t.lower() if exact else fold(t)), lab, exact))
        items.sort(key=lambda x: -len(x[0]))     # longest first so full names win
        self.rx = [(re.compile(self.B + re.escape(t) + self.E), lab, exact) for t, lab, exact in items]

    def _views(self, text: str) -> tuple[str, str]:
        return fold(text), text.lower()

    def __call__(self, text):
        if not isinstance(text, str) or not text:
            return text
        text = EMAIL.sub("[email]", text)
        text = mask_phones(text)
        text = VERIFIER.sub(r"\1[token]", text)
        folded, lower = self._views(text)
        if not (len(folded) == len(lower) == len(text)):   # rare: decomposed input; work on folded text
            text = lower = folded
        spans = []
        for rx, lab, exact in self.rx:
            for m in rx.finditer(lower if exact else folded):
                if not any(s < m.end() and m.start() < e for s, e, _ in spans):
                    spans.append((m.start(), m.end(), lab))
        for s, e, lab in sorted(spans, reverse=True):
            text = text[:s] + lab + text[e:]
        return text

    def leaks(self, text: str) -> list[str]:
        folded, lower = self._views(text)
        found = [lab for rx, lab, exact in self.rx if rx.search(lower if exact else folded)]
        if EMAIL.search(text):
            found.append("[email]")
        return found




# ---------------------------------------------------------------- build
def build(src: Path, dest: Path, red: Redactor, hide_scores: bool = False) -> dict:
    terms_checked = len(red.rx)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    meta = {"note": "Showcase copy: names, handles, classes, comments and local paths removed."}

    courses = ex.load_table(src, "courses")
    labels = {c["course_id"]: subject_label(c) for c in courses}
    # two classes of the same subject in one grade would collide: number them
    seen: dict[str, int] = {}
    for cid in sorted(labels):
        seen[labels[cid]] = seen.get(labels[cid], 0) + 1
        if seen[labels[cid]] > 1:
            labels[cid] = f"{labels[cid]} ({seen[labels[cid]]})"

    def scrub_course(c):
        c = dict(c)
        c["course_code"] = c["course_name"] = labels.get(c["course_id"])
        if hide_scores:
            c["course_total"] = None
        return c

    recs = []
    for r in ex.load_table(src, "records"):
        r = dict(r)
        r["course_code"] = r["course_name"] = labels.get(r["course_id"])
        r["assignment_name"] = red(r.get("assignment_name"))
        r["group"] = red(r.get("group"))
        if r.get("comments"):
            n = len(str(r["comments"]).split(" | "))
            r["comments"] = f"[{n} comment{'s' if n > 1 else ''} hidden]"
        if hide_scores:
            r["score_display"] = r["score"] = None
        recs.append(r)

    docs = []
    for d in ex.load_table(src, "documents"):
        d = dict(d)
        d["course_code"] = labels.get(d.get("course_id")) if d.get("course_id") else None
        d["filename"] = red(d.get("filename"))
        d["path"] = None
        docs.append(d)

    ex.write_table(dest, "records", canvas.RECORD_FIELDS, recs, meta)
    ex.write_table(dest, "courses", canvas.COURSE_FIELDS, [scrub_course(c) for c in courses], meta)
    ex.write_table(dest, "documents", ex.DOC_FIELDS, docs, meta)
    man_p = src / "manifest.json"
    if man_p.exists():
        man = json.loads(man_p.read_text())
        man["showcase"] = meta["note"]
        man["terms_checked"] = terms_checked
        (dest / "manifest.json").write_text(json.dumps(man, indent=1, ensure_ascii=False))
    ch_p = src / "changes.ndjson"
    if ch_p.exists():
        out = []
        for line in ch_p.read_text().splitlines():
            c = json.loads(line)
            for f, (a, b) in (c.get("fields") or {}).items():
                if f == "comments":
                    c["fields"][f] = ["[hidden]", "[hidden]"]
                elif f in {"score", "score_display"} and hide_scores:
                    c["fields"][f] = ["[hidden]", "[hidden]"]
                else:
                    c["fields"][f] = [red(a) if isinstance(a, str) else a, red(b) if isinstance(b, str) else b]
            out.append(json.dumps(c, ensure_ascii=False))
        (dest / "changes.ndjson").write_text("\n".join(out) + ("\n" if out else ""))

    # leak check over everything written
    problems = {}
    for p in dest.iterdir():
        found = red.leaks(p.read_text(encoding="utf-8"))
        if found:
            problems[p.name] = sorted(set(found))
    if problems:
        shutil.rmtree(dest)
        raise SystemExit(f"Showcase NOT written: personal terms still present {problems}")
    return {"records": len(recs), "courses": len(courses), "documents": len(docs), "dest": str(dest)}

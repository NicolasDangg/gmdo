import json

import pytest

from getmydataout import export as ex
from getmydataout.portals import canvas
from getmydataout.showcase import Redactor, build, handles_from_courses, subject_label

# Made-up names, not real people.
TERMS = {"Trần Thị Bích Ngọc": "[teacher]", "=Bích": "[teacher]", "=Nhung": "[teacher]", "PHAMXY9": "[teacher]",
         "Lucas Vale": "[student]", "=Lucas": "[student]", "=Vale": "[student]", "lvale42": "[student]"}


def test_redacts_names_in_any_form():
    red = Redactor(TERMS)
    assert red("Essay feedback from Trần Thị Bích Ngọc") == "Essay feedback from [teacher]"
    assert red("tran thi bich ngoc marked it") == "[teacher] marked it"
    assert red("Vale_Lucas_homework.pdf").startswith("[student]")
    assert "lvale42" not in red("lvale42-final.docx")
    assert red("Prepared by PHAMXY9") == "Prepared by [teacher]"
    assert red("write to x.y@school.edu.vn") == "write to [email]"


def test_keeps_ordinary_words():
    red = Redactor(TERMS)
    assert red("Ngữ Văn - Bài tập 3") == "Ngữ Văn - Bài tập 3"
    assert red("Valence electrons") == "Valence electrons"     # 'Vale' only as a whole word
    assert red("ASEAN - những chặng đường") == "ASEAN - những chặng đường"   # word, not the name Nhung
    assert red("cô Nhung") == "cô [teacher]"
    assert red("9618-specimen-paper-2023-2025.pdf") == "9618-specimen-paper-2023-2025.pdf"
    assert red("call 0912 345 678") == "call [phone]"
    assert red("+84 912 345 678") == "[phone]"
    assert red("415312-2020-specimen-paper-1.pdf") == "415312-2020-specimen-paper-1.pdf"


def test_subject_labels_drop_handles_classes_and_campus():
    assert subject_label({"course_code": "THPT.HAR-AS.CS-11", "course_name": "1102-COMPUTER SCIENCE-ROBERT7-THPT.HAR"}) \
        == "AS Computer Science · Grade 11"
    assert subject_label({"course_code": "PHAMXY9-HÓA HỌC-12-THPT-THE HARMONY-2026 - 2027"}) == "Chemistry · Grade 12"
    assert subject_label({"course_id": 5, "course_code": "Odd"}) == "Course 5"
    assert subject_label({"course_code": "PHAMXY9-VẬT LÝ-12-THPT-THE HARMONY-2026 - 2027"}) == "Physics · Grade 12"
    assert subject_label({"course_code": "PHAMXY9-A-LEVEL NGỮ VĂN-12-THPT-THE HARMONY-2026 - 2027"}) == "A-Level Vietnamese Literature · Grade 12"


def test_handles_found_in_course_names():
    hs = handles_from_courses([{"course_code": "THPT.T37-IT-10", "course_name": "10-CÔNG NGHỆ-NHUNGXY2-THPT.T37"},
                               {"course_code": "PHAMXY9-TOÁN-12-THPT-THE HARMONY-2026 - 2027"}])
    assert hs == {"NHUNGXY2", "PHAMXY9"}


def _export(tmp_path, comment="Great work Lucas"):
    src = tmp_path / "export"
    course = {"course_id": 1, "course_code": "PHAMXY9-TOÁN-12-THPT-THE HARMONY-2026 - 2027",
              "course_name": "PHAMXY9-TOÁN-12-THPT-THE HARMONY-2026 - 2027", "term": "2026 - 2027"}
    rec = {"record_key": "canvas:1:9", "course_id": 1, "course_code": course["course_code"],
           "course_name": course["course_name"], "assignment_id": "9", "assignment_name": "Quiz for Lucas Vale",
           "score": "8", "score_display": "8", "comments": comment}
    doc = {"doc_key": "canvas:file:3", "kind": "own", "file_id": 3, "course_id": None,
           "filename": "lvale42_report.pdf", "path": "/Users/someone/documents/own/x.pdf", "status": "new"}
    ex.write_table(src, "records", canvas.RECORD_FIELDS, [rec], {})
    ex.write_table(src, "courses", canvas.COURSE_FIELDS, [course], {})
    ex.write_table(src, "documents", ex.DOC_FIELDS, [doc], {})
    return src


def test_build_writes_clean_copy(tmp_path):
    src = _export(tmp_path)
    out = build(src, tmp_path / "showcase", Redactor(TERMS))
    text = "".join(p.read_text() for p in (tmp_path / "showcase").iterdir())
    for bad in ("PHAMXY9", "Lucas", "lvale42", "HARMONY", "/Users/", "Great work"):
        assert bad not in text
    recs = json.loads((tmp_path / "showcase" / "records.json").read_text())["records"]
    assert recs[0]["course_name"] == "Mathematics · Grade 12" and recs[0]["comments"] == "[1 comment hidden]"
    assert recs[0]["score"] == "8" and out["records"] == 1


def test_hide_scores(tmp_path):
    build(_export(tmp_path), tmp_path / "s", Redactor(TERMS), hide_scores=True)
    recs = json.loads((tmp_path / "s" / "records.json").read_text())["records"]
    assert recs[0]["score"] is None


def test_refuses_when_a_name_survives(tmp_path):
    src = _export(tmp_path)
    red = Redactor(TERMS)
    red.__class__ = type("Leaky", (Redactor,), {"__call__": lambda self, t: t})   # a redactor that does nothing
    with pytest.raises(SystemExit):
        build(src, tmp_path / "showcase", red)
    assert not (tmp_path / "showcase").exists()


def test_accounts_named_after_a_subject_are_not_people():
    from getmydataout.showcase import SUBJECT_WORDS, fold
    assert all(fold(w) in SUBJECT_WORDS for w in "Vietnamese Literature".split())
    assert not all(fold(w) in SUBJECT_WORDS for w in "Lucas Vale".split())


def test_subject_words_in_course_names_are_not_handles():
    hs = handles_from_courses([{"course_code": "THPT.HAR-AS.NV-11", "course_name": "1104-VIETNAMESE LITERATURE-PHAMXY9-THPT.HAR"}])
    assert hs == {"PHAMXY9"}

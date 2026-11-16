"""Keep personal data out of logs and demo files."""
from __future__ import annotations

import hashlib
import logging
import re

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONEISH = re.compile(r"(?<![\w.-])(?:\+\d|0)[\d .-]{7,14}\d(?![\w.-])")  # local 0… or international +…
_YEARS = re.compile(r"^(19|20)\d\d\s*-\s*(19|20)\d\d$")
PHONE = _PHONEISH  # kept for callers that only need the pattern


def mask_phones(text: str) -> str:
    """9-12 digit numbers that look like phone numbers, not ids, years or year ranges."""
    def sub(m):
        s = m.group(0)
        digits = sum(ch.isdigit() for ch in s)
        if _YEARS.match(s) or not 9 <= digits <= 12:
            return s
        return "[phone]"
    return _PHONEISH.sub(sub, text)
SECRET = re.compile(r"(X-API-Key[\"']?\s*[:=]\s*[\"']?)[\w-]+", re.I)
# Signed download links carry a verifier token.
VERIFIER = re.compile(r"(verifier=)[\w-]+")


def scrub(text: str) -> str:
    text = EMAIL.sub("[email]", text)
    text = mask_phones(text)
    text = SECRET.sub(r"\1[key]", text)
    return VERIFIER.sub(r"\1[token]", text)


def pseudonym(value: str | None, prefix: str) -> str | None:
    if not value:
        return value
    return f"{prefix}-{hashlib.sha256(value.encode()).hexdigest()[:6]}"


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = scrub(record.getMessage())   # format first, then mask
        record.args = None
        return True

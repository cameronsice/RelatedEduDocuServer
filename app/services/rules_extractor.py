"""Deterministic (non-AI) field extraction from OCR text.

This is the first tier of the extraction cascade: cheap, free, and reliable
where the document is printed and templated. It handles:

  * SA ID numbers  — 13-digit regex + date-of-birth sanity + Luhn checksum
  * dates          — label-preferred, normalized to YYYY-MM-DD
  * named fields   — label-anchored ("Certificate Number: X", or a label on one
                     line with its value on the next)

Whatever it can't fill (e.g. handwritten POE learner details) is left for the
vision-AI fallback. Values here are conservative on purpose.
"""

import logging
import re
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


# --- SA ID number --------------------------------------------------------

_ID_TOKEN = re.compile(r"\b(\d{13})\b")


def luhn_valid(number: str) -> bool:
    """Standard Luhn checksum (South African ID numbers use it)."""
    total = 0
    for i, ch in enumerate(reversed(number)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _valid_id_dob(number: str) -> bool:
    """First 6 digits are a plausible YYMMDD date of birth."""
    mm = int(number[2:4])
    dd = int(number[4:6])
    return 1 <= mm <= 12 and 1 <= dd <= 31


def validate_sa_id(number: Optional[str]) -> bool:
    """True if number is a 13-digit SA ID with a valid DOB and Luhn checksum."""
    if not number:
        return False
    number = str(number).strip()
    if not re.fullmatch(r"\d{13}", number):
        return False
    return _valid_id_dob(number) and luhn_valid(number)


def extract_sa_id(text: str) -> Optional[str]:
    """Return the first 13-digit sequence that passes SA ID validation."""
    if not text:
        return None
    for match in _ID_TOKEN.finditer(text):
        candidate = match.group(1)
        if validate_sa_id(candidate):
            return candidate
    return None


# --- Dates ---------------------------------------------------------------

_DATE_FORMATS = [
    "%Y-%m-%d", "%Y/%m/%d",
    "%m-%d-%Y", "%m/%d/%Y",
    "%d-%m-%Y", "%d/%m/%Y",
    "%d %B %Y", "%d %b %Y",
    "%B %d, %Y", "%b %d, %Y",
    "%B %d %Y", "%b %d %Y",
]

# Ordered by preference — issue date wins over achieved date, etc.
_DATE_LABELS = [
    "date issued", "date of issue", "issued",
    "date achieved", "date completed", "completed",
    "date", "dated",
]

_DATE_TOKEN = re.compile(
    r"(\d{1,4}[/\-.]\d{1,2}[/\-.]\d{1,4})"
    r"|(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})"
    r"|([A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})"
)


def _parse_date(token: str) -> Optional[str]:
    token = token.strip().strip(".,")
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(token, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _find_date_in(text: str) -> Optional[str]:
    for match in _DATE_TOKEN.finditer(text):
        parsed = _parse_date(match.group(0))
        if parsed:
            return parsed
    return None


def extract_date(text: str) -> Optional[str]:
    """Extract a date (YYYY-MM-DD), preferring one next to a date label."""
    if not text:
        return None
    lines = text.splitlines()
    lowered = [(line, line.lower()) for line in lines]
    for label in _DATE_LABELS:
        for original, low in lowered:
            if label in low:
                found = _find_date_in(original)
                if found:
                    return found
    return _find_date_in(text)


# --- Label-anchored named fields ----------------------------------------

# Aliases per core field (kept precise to avoid capturing the wrong text).
_FIELD_ALIASES: dict[str, list[str]] = {
    "student_name": ["certifies that", "student name", "learner name", "name of learner", "full name"],
    "course_name": ["qualification", "course name", "programme", "program", "course"],
    "assignment_name": ["assignment", "module", "workbook", "assessment"],
    "grade": ["final result", "grade", "result", "mark", "score"],
}

_VALUE_STRIP = " \t:-–—"


def _looks_like_value(text: str) -> bool:
    return bool(text) and len(text) >= 2


def _next_line_value(lines: list[str], idx: int, max_len: int) -> Optional[str]:
    for j in range(idx + 1, min(idx + 3, len(lines))):
        nxt = lines[j].strip()
        if _looks_like_value(nxt):
            return nxt[:max_len]
    return None


def _extract_by_label(lines: list[str], aliases: list[str], max_len: int = 160) -> Optional[str]:
    """
    Find a value by label, avoiding false positives from headings.

    Pass 1 (preferred): a real labeled form, "alias:" anywhere on the line — the
    value follows the colon, or is the next line if the label stands alone.
    Pass 2 (loose): only when the alias *starts* the line, so a heading such as
    "NQF4 ... WORKBOOK" is never mistaken for a "workbook" label.
    """
    for idx, line in enumerate(lines):
        low = line.lower()
        for alias in aliases:
            m = re.search(re.escape(alias) + r"\s*:", low)
            if not m:
                continue
            rest = line[m.end():].strip(_VALUE_STRIP).strip()
            if rest:  # any non-empty same-line value (grades can be one char)
                return rest[:max_len]
            value = _next_line_value(lines, idx, max_len)
            if value:
                return value

    for idx, line in enumerate(lines):
        stripped = line.strip()
        low = stripped.lower()
        for alias in aliases:
            if not low.startswith(alias):
                continue
            rest = stripped[len(alias):].strip(_VALUE_STRIP).strip()
            if rest:  # any non-empty same-line value (grades can be one char)
                return rest[:max_len]
            value = _next_line_value(lines, idx, max_len)
            if value:
                return value
    return None


class RulesExtractor:
    """Deterministic extractor driven by a document type's field config."""

    def extract(self, ocr_text: Optional[str], type_config: Optional[dict]) -> dict:
        """
        Return {field_key: value} for fields this tier could confidently fill.
        `type_config` is the enriched type (from document_type_service.get_type).
        """
        values: dict = {}
        if not ocr_text:
            return values
        lines = ocr_text.splitlines()
        fields = (type_config or {}).get("fields", [])

        for field in fields:
            key = field.get("key")
            data_type = field.get("data_type", "text")
            if not key:
                continue

            if key == "student_id" or data_type == "id":
                found = extract_sa_id(ocr_text)
                if found:
                    values[key] = found
            elif key == "document_date" or data_type == "date":
                found = extract_date(ocr_text)
                if found:
                    values[key] = found
            else:
                aliases = list(_FIELD_ALIASES.get(key, []))
                label = (field.get("label") or "").lower()
                if label and label not in aliases:
                    aliases.append(label)
                found = _extract_by_label(lines, aliases)
                if found:
                    values[key] = found

        return values


# Global instance
rules_extractor = RulesExtractor()

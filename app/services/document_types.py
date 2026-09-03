"""Document type configuration service.

Document types (POE, Certificate, and future ones) and the fields each type
uses are stored in the `document_types` table so they can be managed as data.
This service reads that config, seeds sensible defaults, and answers questions
the rest of the app needs (which fields are required for a type, is a type
allowed, what are the labels, etc.).

Phase 1 scope: every field maps to an existing column on the `documents`
table (see CORE_FIELDS). Custom fields stored in a JSON column arrive with the
Phase 2 admin page.
"""

import logging
import re
from typing import Optional

from sqlalchemy.orm import Session

from app.models import DocumentType, Document

logger = logging.getLogger(__name__)


# Supported field data types. Drives validation, search behavior, and the
# schema the MCP exposes to agents.
#   text   -> free text (LIKE search)
#   number -> numeric (range/exact search)
#   date   -> ISO date (range/exact search)
#   id     -> identifier, stored/matched as text but exact-match oriented
FIELD_DATA_TYPES = ("text", "number", "date", "id")

# Registry of "core" fields — these map 1:1 to columns on the Document model
# (key == column name). Custom fields (defined per type) are stored in the
# document_field_values table instead.
CORE_FIELDS: dict[str, dict] = {
    "student_name": {"label": "Student Name", "input_type": "text", "data_type": "text"},
    "course_name": {"label": "Course Name", "input_type": "text", "data_type": "text"},
    "assignment_name": {"label": "Assignment Name", "input_type": "text", "data_type": "text"},
    "grade": {"label": "Grade", "input_type": "text", "data_type": "text"},
    "document_date": {"label": "Date", "input_type": "date", "data_type": "date"},
    "student_id": {"label": "Student ID", "input_type": "text", "data_type": "id"},
}

# Default seed. POE keeps today's behavior except Grade is optional (it lives
# deeper in the portfolio, not on the cover). Certificate drops Assignment and
# Grade entirely.
DEFAULT_DOCUMENT_TYPES: list[dict] = [
    {
        "key": "poe",
        "label": "POE (Grade Books)",
        "sort_order": 1,
        "max_pages": 5,
        "fields": [
            {"key": "student_name", "required": True, "visible": True},
            {"key": "course_name", "required": True, "visible": True},
            {"key": "assignment_name", "required": True, "visible": True},
            {"key": "document_date", "required": True, "visible": True},
            {"key": "student_id", "required": True, "visible": True},
            {"key": "grade", "required": False, "visible": True},
        ],
    },
    {
        "key": "certificate",
        "label": "Certificate",
        "sort_order": 2,
        "max_pages": 1,
        "detect_keywords": ["certificate issued"],
        "fields": [
            {"key": "student_name", "required": True, "visible": True},
            {"key": "course_name", "required": True, "visible": True},
            {"key": "student_id", "required": True, "visible": True},
            {"key": "document_date", "required": True, "visible": True},
        ],
    },
]

# Fallback type key when a value is missing or not recognized.
DEFAULT_TYPE_KEY = "poe"

# What the AI tier may look at for a type (see DocumentType.ai_input).
AI_INPUT_MODES = ("text_then_images", "text", "images")
DEFAULT_AI_INPUT = "text_then_images"


def _clean_list(value) -> list[str]:
    """Normalize a list (or comma/newline separated string) of short strings."""
    if value is None:
        return []
    if isinstance(value, str):
        parts = re.split(r"[,\n]", value)
    else:
        parts = list(value)
    out, seen = [], set()
    for p in parts:
        item = str(p or "").strip()
        if item and item.lower() not in seen:
            seen.add(item.lower())
            out.append(item)
    return out


class DocumentTypeService:
    """Read and seed document type configuration."""

    def seed_defaults(self, db: Session) -> None:
        """
        Insert the default types if they don't already exist. Idempotent and
        purely additive — never updates or deletes existing rows, so it is safe
        to run on every startup against a database that already has data.
        """
        for spec in DEFAULT_DOCUMENT_TYPES:
            exists = (
                db.query(DocumentType)
                .filter(DocumentType.key == spec["key"])
                .first()
            )
            if exists:
                continue
            db.add(
                DocumentType(
                    key=spec["key"],
                    label=spec["label"],
                    sort_order=spec.get("sort_order", 0),
                    is_active=True,
                    fields=spec["fields"],
                    max_pages=spec.get("max_pages", 1),
                    detect_keywords=spec.get("detect_keywords", []),
                    filename_patterns=spec.get("filename_patterns", []),
                    ai_input=spec.get("ai_input", DEFAULT_AI_INPUT),
                )
            )
            logger.info("Seeded default document type: %s", spec["key"])
        db.commit()

    def _enrich_field(self, field: dict) -> Optional[dict]:
        """
        Merge a stored field config with registry metadata.

        Core fields draw label/type from CORE_FIELDS and map to a Document
        column. Custom fields carry their own label/data_type and are stored in
        the document_field_values table.
        """
        key = field.get("key")
        if not key:
            return None
        core = CORE_FIELDS.get(key)
        if core:
            source = "core"
            label = field.get("label") or core["label"]
            input_type = core["input_type"]
            data_type = core["data_type"]
        else:
            source = "custom"
            label = field.get("label") or key.replace("_", " ").title()
            data_type = field.get("data_type") or "text"
            if data_type not in FIELD_DATA_TYPES:
                data_type = "text"
            input_type = "date" if data_type == "date" else "text"
        return {
            "key": key,
            "label": label,
            "input_type": input_type,
            "data_type": data_type,
            "source": source,
            "required": bool(field.get("required", False)),
            "visible": bool(field.get("visible", True)),
            # Hint for the AI prompt (e.g. "the employer registered company name").
            "description": str(field.get("description") or "").strip(),
            # Extra labels the rules extractor should look for in OCR text.
            "aliases": _clean_list(field.get("aliases")),
            # Usually handwritten: skip text rules, let the AI read the image.
            "handwritten": bool(field.get("handwritten", False)),
        }

    def _rows(self, db: Session) -> list[DocumentType]:
        """Active types from the DB, or in-memory defaults if unseeded."""
        rows = (
            db.query(DocumentType)
            .filter(DocumentType.is_active.is_(True))
            .order_by(DocumentType.sort_order, DocumentType.label)
            .all()
        )
        if rows:
            return rows
        # Resilience: behave sensibly even if seeding hasn't run yet.
        return [
            DocumentType(
                key=s["key"],
                label=s["label"],
                sort_order=s.get("sort_order", 0),
                is_active=True,
                fields=s["fields"],
                max_pages=s.get("max_pages", 1),
                detect_keywords=s.get("detect_keywords", []),
                filename_patterns=s.get("filename_patterns", []),
                ai_input=s.get("ai_input", DEFAULT_AI_INPUT),
            )
            for s in DEFAULT_DOCUMENT_TYPES
        ]

    def list_types(self, db: Session) -> list[dict]:
        """Return all active types with enriched (labelled) field configs."""
        result = []
        for row in self._rows(db):
            fields = [self._enrich_field(f) for f in (row.fields or [])]
            result.append(
                {
                    "key": row.key,
                    "label": row.label,
                    "max_pages": row.max_pages,
                    "detect_keywords": _clean_list(row.detect_keywords),
                    "filename_patterns": _clean_list(row.filename_patterns),
                    "ai_input": self._normalize_ai_input(row.ai_input),
                    "fields": [f for f in fields if f],
                }
            )
        return result

    @staticmethod
    def _normalize_ai_input(value) -> str:
        v = (value or "").strip().lower()
        return v if v in AI_INPUT_MODES else DEFAULT_AI_INPUT

    def list_all(self, db: Session) -> list[dict]:
        """All types (active + inactive) with is_active/sort_order — for admin."""
        rows = (
            db.query(DocumentType)
            .order_by(DocumentType.sort_order, DocumentType.label)
            .all()
        )
        if not rows:
            rows = self._rows(db)  # in-memory defaults if unseeded
        result = []
        for row in rows:
            fields = [self._enrich_field(f) for f in (row.fields or [])]
            result.append(
                {
                    "key": row.key,
                    "label": row.label,
                    "is_active": bool(row.is_active),
                    "sort_order": row.sort_order,
                    "max_pages": row.max_pages,
                    "detect_keywords": _clean_list(row.detect_keywords),
                    "filename_patterns": _clean_list(row.filename_patterns),
                    "ai_input": self._normalize_ai_input(row.ai_input),
                    "fields": [f for f in fields if f],
                }
            )
        return result

    def get_type(self, db: Session, key: Optional[str]) -> Optional[dict]:
        """Return one enriched type config by key, or None."""
        if not key:
            return None
        for t in self.list_types(db):
            if t["key"] == key:
                return t
        return None

    def allowed_keys(self, db: Session) -> list[str]:
        """List of valid type keys."""
        return [t["key"] for t in self.list_types(db)]

    def normalize_type(self, db: Session, value: Optional[str]) -> str:
        """Return a valid type key; fall back to the default if invalid."""
        if value:
            v = value.strip().lower()
            if v in self.allowed_keys(db):
                return v
        allowed = self.allowed_keys(db)
        return DEFAULT_TYPE_KEY if DEFAULT_TYPE_KEY in allowed else (allowed[0] if allowed else DEFAULT_TYPE_KEY)

    def detect_type(
        self, db: Session, ocr_text: Optional[str], filename: Optional[str]
    ) -> Optional[str]:
        """
        Deterministic type identification (case-insensitive substring matches).

        Pass 1: detection keywords against the first-page OCR text, types in
        sort order - what the page *says* is the strongest evidence.
        Pass 2: filename patterns against the original filename - a fallback
        for unreadable scans (scanner naming is coarser: e.g. both a Workplace
        Agreement and a Learner Contract may be named "..._Agreement_...").
        Returns the first matching key, or None.
        """
        name = (filename or "").lower()
        text = (ocr_text or "").lower()
        types = self.list_types(db)
        if text:
            for t in types:
                if any(k.lower() in text for k in t["detect_keywords"]):
                    return t["key"]
        if name:
            for t in types:
                if any(p.lower() in name for p in t["filename_patterns"]):
                    return t["key"]
        return None

    def required_field_keys(self, db: Session, key: Optional[str]) -> list[str]:
        """The field keys that must be present for a document of this type."""
        return [f["key"] for f in self.required_fields(db, key)]

    def required_fields(self, db: Session, key: Optional[str]) -> list[dict]:
        """The enriched field configs that are required for this type."""
        t = self.get_type(db, key) or self.get_type(db, DEFAULT_TYPE_KEY)
        if not t:
            return []
        return [f for f in t["fields"] if f["required"]]

    def is_core_field(self, key: str) -> bool:
        """Whether a field maps to a Document column (vs the values table)."""
        return key in CORE_FIELDS

    def custom_field_map(self, db: Session, type_key: Optional[str]) -> dict[str, dict]:
        """Map of custom field_key -> enriched field config for a type."""
        t = self.get_type(db, type_key)
        if not t:
            return {}
        return {f["key"]: f for f in t["fields"] if f["source"] == "custom"}

    def field_data_type(self, db: Session, type_key: Optional[str], field_key: str) -> str:
        """Resolve a field's data type (core registry or custom config)."""
        if field_key in CORE_FIELDS:
            return CORE_FIELDS[field_key]["data_type"]
        cf = self.custom_field_map(db, type_key).get(field_key)
        return cf["data_type"] if cf else "text"

    def field_label(self, key: str) -> str:
        """Human label for a core field key."""
        meta = CORE_FIELDS.get(key)
        if meta:
            return meta["label"]
        return key.replace("_", " ").title()

    # --- Write operations (admin) --------------------------------------

    @staticmethod
    def _slugify(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", (value or "").strip().lower()).strip("_")

    def _normalize_field(self, raw: dict) -> Optional[dict]:
        """Validate/normalize one incoming field config into stored form."""
        key = (raw.get("key") or "").strip()
        if key in CORE_FIELDS:
            entry = {
                "key": key,
                "required": bool(raw.get("required", False)),
                "visible": bool(raw.get("visible", True)),
            }
            if raw.get("label"):
                entry["label"] = str(raw["label"]).strip()
            self._apply_field_hints(entry, raw)
            return entry

        # Custom field: derive a safe key, validate type.
        slug = self._slugify(key or raw.get("label") or "")
        if not slug or slug in CORE_FIELDS:
            return None
        data_type = (raw.get("data_type") or "text").lower()
        if data_type not in FIELD_DATA_TYPES:
            data_type = "text"
        label = (raw.get("label") or slug.replace("_", " ").title()).strip()
        entry = {
            "key": slug,
            "label": label,
            "data_type": data_type,
            "required": bool(raw.get("required", False)),
            "visible": bool(raw.get("visible", True)),
        }
        self._apply_field_hints(entry, raw)
        return entry

    @staticmethod
    def _apply_field_hints(entry: dict, raw: dict) -> None:
        description = str(raw.get("description") or "").strip()
        aliases = _clean_list(raw.get("aliases"))
        if description:
            entry["description"] = description[:300]
        if aliases:
            entry["aliases"] = aliases[:20]
        if raw.get("handwritten"):
            entry["handwritten"] = True

    def _normalize_fields(self, fields) -> list:
        out, seen = [], set()
        for raw in (fields or []):
            entry = self._normalize_field(raw)
            if not entry or entry["key"] in seen:
                continue
            seen.add(entry["key"])
            out.append(entry)
        return out

    def create_type(self, db: Session, data: dict) -> DocumentType:
        key = self._slugify(data.get("key") or data.get("label") or "")
        if not key:
            raise ValueError("A type key or label is required")
        if db.query(DocumentType).filter(DocumentType.key == key).first():
            raise ValueError(f"Document type '{key}' already exists")
        dt = DocumentType(
            key=key,
            label=(data.get("label") or key).strip(),
            sort_order=int(data.get("sort_order") or 0),
            is_active=bool(data.get("is_active", True)),
            fields=self._normalize_fields(data.get("fields")),
            max_pages=max(1, int(data.get("max_pages") or 1)),
            detect_keywords=_clean_list(data.get("detect_keywords")),
            filename_patterns=_clean_list(data.get("filename_patterns")),
            ai_input=self._normalize_ai_input(data.get("ai_input")),
        )
        db.add(dt)
        db.commit()
        db.refresh(dt)
        logger.info("Created document type: %s", key)
        return dt

    def update_type(self, db: Session, key: str, data: dict) -> DocumentType:
        dt = db.query(DocumentType).filter(DocumentType.key == key).first()
        if not dt:
            raise LookupError(f"Document type '{key}' not found")
        if data.get("label"):
            dt.label = str(data["label"]).strip()
        if data.get("sort_order") is not None:
            dt.sort_order = int(data["sort_order"])
        if data.get("is_active") is not None:
            dt.is_active = bool(data["is_active"])
        if data.get("max_pages") is not None:
            dt.max_pages = max(1, int(data["max_pages"]))
        if data.get("fields") is not None:
            dt.fields = self._normalize_fields(data.get("fields"))
        if data.get("detect_keywords") is not None:
            dt.detect_keywords = _clean_list(data.get("detect_keywords"))
        if data.get("filename_patterns") is not None:
            dt.filename_patterns = _clean_list(data.get("filename_patterns"))
        if data.get("ai_input") is not None:
            dt.ai_input = self._normalize_ai_input(data.get("ai_input"))
        db.commit()
        db.refresh(dt)
        logger.info("Updated document type: %s", key)
        return dt

    def usage_count(self, db: Session, key: str) -> int:
        """How many documents currently use this type."""
        return db.query(Document).filter(Document.document_type == key).count()

    def delete_type(self, db: Session, key: str) -> None:
        dt = db.query(DocumentType).filter(DocumentType.key == key).first()
        if not dt:
            raise LookupError(f"Document type '{key}' not found")
        db.delete(dt)
        db.commit()
        logger.info("Deleted document type: %s", key)


# Global service instance
document_type_service = DocumentTypeService()

"""One-off data fix for document type configuration (run once, idempotent).

* Gives the custom fields on the newer types human-readable labels, the
  labels they actually appear under on the forms (aliases, used by the free
  rules extractor) and a hint for the AI prompt.
* Adds filename patterns / detection keywords so scanned files are
  auto-identified (the scanner names files like ``<id>_ID_<n>.pdf`` and
  ``<id>_Agreement_<n>.pdf``).
* Sets the AI input mode: ID cards and handwritten POEs go straight to page
  images; typed agreements try OCR text first.
* Repairs values stored under the misspelled key ``leaernerfullnameandsurname``.

Usage (from the project root, with the .env in place):

    python scripts/fix_field_config.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal, init_db  # noqa: E402
from app.models import DocumentType, DocumentFieldValue  # noqa: E402

FIELD_FIXES = {
    "workplace_based_learning_programme_agreement": {
        "learnerfullnameandsurname": {
            "label": "Learner Full Name and Surname",
            "aliases": ["learner full name and surname", "learner name", "full name and surname", "name of learner"],
            "description": "the learner's full name and surname as written in the learner details section",
            "handwritten": True,
        },
        "learningprogrammetitle": {
            "label": "Learning Programme Title",
            "aliases": ["learning programme title", "programme title", "qualification title", "learning programme"],
            "description": "the title of the learning programme or qualification the agreement covers",
        },
        "projectname": {
            "label": "Project Name",
            "aliases": ["project name", "project"],
            "description": "the project or funding window name printed near the top of page 1",
        },
    },
    "company_learner_contract": {
        "companyname": {
            "label": "Company Name",
            "aliases": ["company name", "employer registered name", "employer name", "registered name", "employer"],
            "description": "the employer's registered company name",
        },
        "contractdate": {
            "label": "Contract Date",
            "aliases": ["contract date", "date of contract", "commencement date", "start date", "signed on"],
            "description": "the date the contract was entered into or signed",
        },
    },
}

TYPE_FIXES = {
    "student_id": {"filename_patterns": ["_ID_"], "detect_keywords": ["national identity card", "identity number"], "ai_input": "images"},
    "workplace_based_learning_programme_agreement": {
        "filename_patterns": ["_Agreement_"],
        "detect_keywords": ["workplace based learning programme agreement", "workplace based learning programme"],
        "ai_input": "text_then_images",
    },
    "company_learner_contract": {
        "filename_patterns": ["_Contract_"],
        "detect_keywords": ["company learner contract", "learner contract"],
        "ai_input": "text_then_images",
    },
    "certificate": {"detect_keywords": ["certificate issued"], "ai_input": "text_then_images"},
    "poe": {"detect_keywords": ["portfolio of evidence"], "ai_input": "images"},
}

KEY_RENAMES = {"leaernerfullnameandsurname": "learnerfullnameandsurname"}


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        for type_key, fields in FIELD_FIXES.items():
            dt = db.query(DocumentType).filter(DocumentType.key == type_key).first()
            if not dt:
                print(f"skip {type_key}: not found")
                continue
            new_fields = []
            for f in dt.fields or []:
                fix = fields.get(f.get("key"))
                if fix:
                    f = dict(f)
                    f.update(fix)
                new_fields.append(f)
            dt.fields = new_fields
            print(f"fields updated: {type_key}")

        for type_key, values in TYPE_FIXES.items():
            dt = db.query(DocumentType).filter(DocumentType.key == type_key).first()
            if not dt:
                print(f"skip {type_key}: not found")
                continue
            for attr, value in values.items():
                current = getattr(dt, attr)
                if attr in ("filename_patterns", "detect_keywords"):
                    merged = list(current or [])
                    for v in value:
                        if v.lower() not in {m.lower() for m in merged}:
                            merged.append(v)
                    setattr(dt, attr, merged)
                else:
                    setattr(dt, attr, value)
            print(f"type updated: {type_key} -> {values}")

        for old, new in KEY_RENAMES.items():
            rows = db.query(DocumentFieldValue).filter(DocumentFieldValue.field_key == old).all()
            moved = 0
            for row in rows:
                clash = (
                    db.query(DocumentFieldValue)
                    .filter(DocumentFieldValue.document_id == row.document_id, DocumentFieldValue.field_key == new)
                    .first()
                )
                if clash:
                    if not clash.value_text and row.value_text:
                        clash.value_text = row.value_text
                    db.delete(row)
                else:
                    row.field_key = new
                moved += 1
            print(f"renamed {moved} value(s): {old} -> {new}")

        db.commit()
        print("done")
    finally:
        db.close()


if __name__ == "__main__":
    main()

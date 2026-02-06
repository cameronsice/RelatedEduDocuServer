# Changelog

## 2025-02-06

- Added document type: POE (Grade Books) and Certificate; dropdown on upload, OCR auto-detect from "Certificate issued".
- Added Student ID field (13-digit); AI extraction + regex fallback; searchable (filter + general query).
- Stored files renamed to descriptive names: `StudentName_CourseName_Type_Last4.ext`; collision suffix _1, _2.
- DB: `document_type`, `student_id` columns; index on `student_id`. `init_db()` migrations for both.
- API: POST upload optional `document_type`; DocumentUpdate/Response include `document_type`, `student_id`; GET /api/search `student_id` param and in full-text.
- UI: Upload type dropdown; document view type + Student ID; search Student ID filter; dashboard and review Type column.

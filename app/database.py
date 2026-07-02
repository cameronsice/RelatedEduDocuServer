"""Database connection and session management."""

from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from app.config import DATABASE_URL

# Create database engine. SQLite needs check_same_thread disabled so the
# background worker thread (bulk upload / file watcher) can use sessions.
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args)

# Create session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()


def get_db():
    """Dependency to get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _ensure_sqlite_columns():
    """Add newer columns to an existing SQLite `documents` table (dev self-heal).

    create_all() only creates missing tables, not missing columns, so an
    existing local DB needs these added without dropping data.
    """
    additions = {
        "ai_used": "BOOLEAN DEFAULT 0",
        "extraction_error": "VARCHAR(500)",
    }
    with engine.connect() as conn:
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(documents)"))}
        for name, ddl in additions.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE documents ADD COLUMN {name} {ddl}"))
        conn.commit()


def init_db():
    """Initialize database tables."""
    Base.metadata.create_all(bind=engine)

    # The Postgres statements below are lightweight, idempotent migrations for
    # pre-existing deployments (Postgres-specific "ADD COLUMN IF NOT EXISTS").
    # On SQLite we self-heal newer columns onto an existing table instead.
    if engine.dialect.name != "postgresql":
        if engine.dialect.name == "sqlite":
            _ensure_sqlite_columns()
        return

    with engine.connect() as conn:
        conn.execute(
            text(
                "ALTER TABLE documents "
                "ADD COLUMN IF NOT EXISTS extraction_confidence DOUBLE PRECISION"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE documents "
                "ADD COLUMN IF NOT EXISTS requires_review BOOLEAN DEFAULT FALSE"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE documents "
                "ADD COLUMN IF NOT EXISTS review_reason VARCHAR(500)"
            )
        )
        conn.execute(
            text(
                "UPDATE documents "
                "SET requires_review = FALSE "
                "WHERE requires_review IS NULL"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE documents "
                "ADD COLUMN IF NOT EXISTS document_type VARCHAR(50)"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE documents "
                "ADD COLUMN IF NOT EXISTS student_id VARCHAR(20)"
            )
        )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_documents_student_id "
                "ON documents (student_id)"
            )
        )
        conn.execute(
            text(
                "UPDATE documents "
                "SET document_type = 'poe' "
                "WHERE document_type IS NULL"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE documents "
                "ADD COLUMN IF NOT EXISTS ai_used BOOLEAN DEFAULT FALSE"
            )
        )
        conn.execute(
            text(
                "ALTER TABLE documents "
                "ADD COLUMN IF NOT EXISTS extraction_error VARCHAR(500)"
            )
        )
        conn.commit()


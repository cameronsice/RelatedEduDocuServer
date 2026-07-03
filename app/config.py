"""Configuration settings for the application."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Base directory
BASE_DIR = Path(__file__).resolve().parent.parent


def _resolve_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (BASE_DIR / path).resolve()


def _env_path(name: str, default: Path) -> Path:
    value = os.getenv(name)
    if value:
        return _resolve_path(value)
    return _resolve_path(default)


# Database
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://user:password@localhost:5432/education_docs")

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# Folder paths (stored as absolute paths to avoid watcher/move confusion)
SCAN_FOLDER_PATH = _env_path("SCAN_FOLDER_PATH", BASE_DIR / "scans")
SCAN_PROCESSED_PATH = _env_path("SCAN_PROCESSED_PATH", SCAN_FOLDER_PATH / "_processed")
SCAN_REVIEW_HOLD_PATH = _env_path("SCAN_REVIEW_HOLD_PATH", SCAN_FOLDER_PATH / "_review_queue")
STORAGE_PATH = _env_path("STORAGE_PATH", BASE_DIR / "storage")
STORAGE_REVIEW_PATH = _env_path("STORAGE_REVIEW_PATH", STORAGE_PATH / "review_queue")

# Ensure directories exist
for folder in (
    SCAN_FOLDER_PATH,
    SCAN_PROCESSED_PATH,
    SCAN_REVIEW_HOLD_PATH,
    STORAGE_PATH,
    STORAGE_REVIEW_PATH,
):
    folder.mkdir(parents=True, exist_ok=True)

# Server configuration
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", 8000))
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# External tool paths (optional). When set, the app points pytesseract /
# pdf2image directly at these binaries instead of relying on PATH — useful on
# Windows where PATH changes don't reach an already-running server process.
TESSERACT_CMD = os.getenv("TESSERACT_CMD", "").strip()
POPPLER_PATH = os.getenv("POPPLER_PATH", "").strip() or None

# MCP server (hosted, optional). When MCP_ENABLED is true AND MCP_AUTH_TOKEN is
# set, the app mounts the MCP server at /mcp (streamable HTTP). Clients must send
# `Authorization: Bearer <MCP_AUTH_TOKEN>`. If the token is blank the mount is
# skipped (fail-safe: never expose write tools unauthenticated).
MCP_ENABLED = os.getenv("MCP_ENABLED", "false").lower() == "true"
MCP_AUTH_TOKEN = os.getenv("MCP_AUTH_TOKEN", "").strip()

# Supported file extensions for scanning
SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp"}

# Image optimization settings
MAX_IMAGE_DIMENSION = 2000  # Max width or height in pixels
JPEG_QUALITY = 85  # Quality for JPEG compression


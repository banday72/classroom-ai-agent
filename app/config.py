"""Central configuration for the Classroom AI Assistant.

WHAT: Loads settings from the environment (.env file) and defines file paths
      and the exact OAuth permissions (scopes) this app will request.

WHY: We need ONE place where every module can look up paths and settings.
     Keeping secrets in .env (never in code) keeps the code safe to share.

HOW: python-dotenv reads the .env file at import time. Every other module
     does `from app.config import ...`.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (folder that contains the app/ package)
load_dotenv()


def _env_str(name, default=""):
    """Read a string env var, treating blank values as unset.

    Hosting dashboards often save a variable as an empty string, which would
    otherwise defeat the default below.
    """
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def _env_float(name, default):
    """Read a float env var, ignoring blank or unparsable values."""
    try:
        return float(_env_str(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int(name, default):
    """Read an int env var, ignoring blank or unparsable values."""
    try:
        return int(float(_env_str(name, str(default))))
    except (TypeError, ValueError):
        return default


def _env_bool(name, default=False):
    """Read a boolean env var from common truthy spellings."""
    value = _env_str(name, "").lower()
    if not value:
        return default
    return value in ("1", "true", "yes", "on")

# ---------------------------------------------------------------------
# File system layout
# ---------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent      # .../classroom_ai_agent

# Serverless hosts (e.g. Vercel) mount the app folder read-only, so we keep
# mutable data (SQLite DB, downloads, generated docs) on a writable path.
if os.getenv("DATA_DIR"):
    DATA_DIR = Path(os.environ["DATA_DIR"].strip() or "/tmp/classroom-data")
elif os.getenv("VERCEL"):
    DATA_DIR = Path("/tmp/classroom-data")
else:
    DATA_DIR = BASE_DIR / "data"
DOWNLOADS_DIR = DATA_DIR / "downloads"                 # raw attachments
GENERATED_DIR = DATA_DIR / "generated"                 # AI-generated .docx
DB_PATH = DATA_DIR / "app.db"                          # SQLite database

# Credentials live in the repo folder normally; on serverless hosts they are
# injected as env vars (git ignores them) so they must sit in writable space.
if os.getenv("VERCEL"):
    CREDENTIALS_DIR = DATA_DIR / "credentials"
else:
    CREDENTIALS_DIR = BASE_DIR / "credentials"

# Google OAuth client (from Google Cloud Console, Desktop app type)
CREDENTIALS_FILE = CREDENTIALS_DIR / "credentials.json"
# Saved user login session (created automatically on first login)
TOKEN_FILE = CREDENTIALS_DIR / "token.json"

# Create folders if they do not exist yet
for _folder in (DATA_DIR, DOWNLOADS_DIR, GENERATED_DIR, CREDENTIALS_DIR):
    _folder.mkdir(parents=True, exist_ok=True)

# Serverless deployments pass the Google files as environment variables
# (Vercel Dashboard -> Settings -> Environment Variables). Write them to the
# writable credentials folder once so the Google client library can read
# them from disk as usual.
for _env_name, _target in (
    ("GOOGLE_CLIENT_JSON", CREDENTIALS_FILE),
    ("GOOGLE_TOKEN_JSON", TOKEN_FILE),
):
    _blob = os.getenv(_env_name, "").strip()
    if _blob and not _target.exists():
        try:
            _target.write_text(_blob, encoding="utf-8")
        except OSError:
            pass

# ---------------------------------------------------------------------
# OAuth 2.0 scopes (minimum permissions we ask Google for)
# ---------------------------------------------------------------------
SCOPES = [
    # Read the list of courses you belong to (metadata only).
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    # Read your coursework AND turn in your own student submissions.
    # (This is the official scope for studentSubmissions.turnIn.)
    "https://www.googleapis.com/auth/classroom.coursework.me",
    # Download the files attached to assignments (read-only on Drive).
    "https://www.googleapis.com/auth/drive.readonly",
]

# ---------------------------------------------------------------------
# AI settings (from .env). No key is ever hard-coded.
# ---------------------------------------------------------------------
AI_API_KEY = _env_str("AI_API_KEY")
AI_BASE_URL = _env_str("AI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
AI_MODEL = _env_str("AI_MODEL", "gpt-4o-mini")
AI_TEMPERATURE = _env_float("AI_TEMPERATURE", 0.3)

# Safety limit: skip attachments larger than this
MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024  # 50 MB

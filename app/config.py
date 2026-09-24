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

# ---------------------------------------------------------------------
# File system layout
# ---------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent      # .../classroom_ai_agent
DATA_DIR = BASE_DIR / "data"
DOWNLOADS_DIR = DATA_DIR / "downloads"                 # raw attachments
GENERATED_DIR = DATA_DIR / "generated"                 # AI-generated .docx
DB_PATH = DATA_DIR / "app.db"                          # SQLite database
CREDENTIALS_DIR = BASE_DIR / "credentials"

# Google OAuth client (from Google Cloud Console, Desktop app type)
CREDENTIALS_FILE = CREDENTIALS_DIR / "credentials.json"
# Saved user login session (created automatically on first login)
TOKEN_FILE = CREDENTIALS_DIR / "token.json"

# Create folders if they do not exist yet
for _folder in (DATA_DIR, DOWNLOADS_DIR, GENERATED_DIR, CREDENTIALS_DIR):
    _folder.mkdir(parents=True, exist_ok=True)

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
AI_API_KEY = os.getenv("AI_API_KEY", "").strip()
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
AI_MODEL = os.getenv("AI_MODEL", "gpt-4o-mini").strip()
AI_TEMPERATURE = float(os.getenv("AI_TEMPERATURE", "0.3"))

# Safety limit: skip attachments larger than this
MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024  # 50 MB

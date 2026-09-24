"""SQLite database: local tracking of every assignment's life cycle.

WHAT: A thin layer over Python's built-in sqlite3 module. Stores one row per
      assignment and remembers which phase it is in.
WHY:  Some assignments should be worked on only once (no duplicate answers),
      and we must never lose track of which answer is ready and approved.
      A simple local DB is perfect for this and needs no server.
HOW:  Each assignment has a `status`:
        pending   -> fetched from Classroom but not processed yet
        ready     -> AI solution generated + saved to data/generated/
        approved  -> you approved it; waiting to be turned in
        submitted -> successfully turned in via the API
        cancelled -> you chose not to submit it
      Rows are unique per (coursework_id, course_id) so syncing twice never
      creates duplicates.
"""

import json
import sqlite3
from datetime import datetime, timezone

from app.config import DB_PATH

STATUS_PENDING = "pending"
STATUS_READY = "ready"
STATUS_APPROVED = "approved"
STATUS_SUBMITTED = "submitted"
STATUS_CANCELLED = "cancelled"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # rows behave like dicts: row["title"]
    return conn


def init_db() -> None:
    """Create the tables the first time the app runs."""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS assignments (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                coursework_id TEXT NOT NULL,
                course_id     TEXT NOT NULL,
                course_name   TEXT NOT NULL,
                title         TEXT NOT NULL,
                description   TEXT NOT NULL DEFAULT '',
                due_date      TEXT,
                max_points    REAL,
                materials     TEXT NOT NULL DEFAULT '[]',   -- JSON list
                status        TEXT NOT NULL DEFAULT 'pending',
                answer_path   TEXT,
                created_at    TEXT NOT NULL,
                processed_at  TEXT,
                UNIQUE (coursework_id, course_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS submissions (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                assignment_id  INTEGER NOT NULL,
                course_id      TEXT NOT NULL,
                coursework_id  TEXT NOT NULL,
                submission_id  TEXT,
                submitted_at   TEXT NOT NULL,
                FOREIGN KEY (assignment_id) REFERENCES assignments (id)
            )
            """
        )


def upsert_assignment(assignment: dict) -> bool:
    """Insert a new assignment OR update an existing one.

    Returns True if a NEW row was inserted (a brand-new assignment),
    False if it was just refreshed (probably already processed).
    The status is never reset on refresh.
    """
    materials_json = json.dumps(assignment["materials"], ensure_ascii=False)
    with _connect() as conn:
        existing = conn.execute(
            "SELECT id FROM assignments WHERE coursework_id = ? AND course_id = ?",
            (assignment["id"], assignment["course_id"]),
        ).fetchone()

        if existing is None:
            conn.execute(
                """
                INSERT INTO assignments
                    (coursework_id, course_id, course_name, title, description,
                     due_date, max_points, materials, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    assignment["id"], assignment["course_id"], assignment["course_name"],
                    assignment["title"], assignment["description"],
                    assignment["due_date"], assignment["max_points"],
                    materials_json, STATUS_PENDING, _now(),
                ),
            )
            return True

        conn.execute(
            """
            UPDATE assignments SET
                course_name = ?, title = ?, description = ?,
                due_date = ?, max_points = ?, materials = ?
            WHERE id = ?
            """,
            (
                assignment["course_name"], assignment["title"], assignment["description"],
                assignment["due_date"], assignment["max_points"],
                materials_json, existing["id"],
            ),
        )
        return False


def list_assignments(status: str = None) -> list:
    """All assignments, newest first. Optionally filtered by status."""
    if status:
        rows = _connect().execute(
            "SELECT * FROM assignments WHERE status = ? ORDER BY created_at DESC", (status,)
        ).fetchall()
    else:
        rows = _connect().execute(
            "SELECT * FROM assignments ORDER BY created_at DESC"
        ).fetchall()
    return rows


def get_assignment(db_id: int):
    """Fetch a single assignment row by its LOCAL database id."""
    row = _connect().execute(
        "SELECT * FROM assignments WHERE id = ?", (db_id,)
    ).fetchone()
    return row


def set_status(db_id: int, status: str, answer_path: str = None) -> None:
    """Advance an assignment to a new phase of the workflow."""
    with _connect() as conn:
        if answer_path is not None:
            conn.execute(
                "UPDATE assignments SET status = ?, answer_path = ?, processed_at = ? WHERE id = ?",
                (status, answer_path, _now(), db_id),
            )
        else:
            conn.execute(
                "UPDATE assignments SET status = ?, processed_at = ? WHERE id = ?",
                (status, _now(), db_id),
            )


def record_submission(db_id: int, course_id: str, coursework_id: str, submission_id: str) -> None:
    """Remember that we turned this assignment in, then mark it submitted."""
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO submissions (assignment_id, course_id, coursework_id, submission_id, submitted_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (db_id, course_id, coursework_id, submission_id, _now()),
        )
        conn.execute(
            "UPDATE assignments SET status = ?, processed_at = ? WHERE id = ?",
            (STATUS_SUBMITTED, _now(), db_id),
        )
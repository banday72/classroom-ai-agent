"""Main command-line interface for the Classroom AI Assistant.

WHAT: The terminal application that drives the whole workflow:
      authenticate -> list courses -> sync assignments -> process one
      assignment (download -> read -> AI solve -> DOCX) -> REVIEW ->
      APPROVE -> turn in via Classroom.

WHY:  All the modules do one job each. main.py is the only place that wires
      them together and the ONLY place that decides when the human sees
      choices. This is the safety guard: submission code lives in
      classroom/submit.py and is reached exclusively through an explicit
      approval step in the review menu.
HOW:  A simple while-loop menu calling one function per command. Each
      command is wrapped in try/except so a failure prints a friendly
      message instead of killing the app.
"""

import json
import re
import sys
from datetime import date

from googleapiclient.errors import HttpError

from app import config
from app.ai import solver
from app.classroom import assignments as classroom_assignments
from app.classroom import auth, client as classroom_client, submit as classroom_submit
from app.database import db
from app.files import downloader, reader
from app.output import document_generator

db.init_db()  # create tables on first run

STATUS_LABELS = {
    db.STATUS_PENDING: "pending (not processed)",
    db.STATUS_READY: "ready (awaiting your approval)",
    db.STATUS_APPROVED: "approved (ready to turn in)",
    db.STATUS_SUBMITTED: "submitted",
    db.STATUS_CANCELLED: "cancelled",
}


# ---------------------------------------------------------------------
# Small display helpers
# ---------------------------------------------------------------------
def _slug(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    return text[:60] or "assignment"


def print_assignment(row, index: int = None) -> None:
    prefix = f"[{index}] " if index is not None else ""
    print(f"\n{prefix}{row['title']}")
    print(f"    Course: {row['course_name']}   Due: {row['due_date'] or 'no due date'}")
    print(f"    Status: {STATUS_LABELS.get(row['status'], row['status'])}")
    if row["description"]:
        preview = row["description"].replace("\n", " ")[:90]
        print(f"    Description: {preview}...")
    try:
        materials = json.loads(row["materials"] or "[]")
    except json.JSONDecodeError:
        materials = []
    files = [m["name"] for m in materials if m.get("kind") == "drive_file"]
    if files:
        print(f"    Attachments: {', '.join(files)}")
    if row["answer_path"]:
        print(f"    Answer file: {row['answer_path']}")


def choose_assignment(rows, prompt: str):
    """Show a numbered list and let the user pick one. Returns a row."""
    if not rows:
        print("\nNo assignments match that status.")
        return None
    for index, row in enumerate(rows, start=1):
        print_assignment(row, index)
    while True:
        choice = input(f"\n{prompt} (number, or 0 to cancel): ").strip()
        if choice == "0":
            return None
        try:
            return rows[int(choice) - 1]
        except (ValueError, IndexError):
            print("Invalid choice, try again.")


# ---------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------
def cmd_auth() -> None:
    print("\n--- Google authentication ---")
    print("We will request these permissions:\n")
    print(auth.show_scopes())
    print("\nA browser window will open; sign in and accept.")
    creds = auth.get_credentials()
    print("\nAuthenticated successfully.")
    print(f"Access token expires at: {creds.expiry}")


def cmd_courses() -> None:
    print("\n--- My courses ---")
    service = classroom_client.classroom_service()
    courses = classroom_client.list_courses(service)
    if not courses:
        print("No courses found. Are you enrolled in any?")
        return
    for course in courses:
        summary = classroom_client.course_summary(course)
        label = summary["name"]
        if summary["section"]:
            label += f" — {summary['section']}"
        print(f"  * {label}   (id: {summary['id']})")


def cmd_sync() -> None:
    print("\n--- Syncing assignments ---\n")
    service = classroom_client.classroom_service()
    courses = classroom_client.list_courses(service)
    if not courses:
        print("No courses found.")
        return

    new_count = 0
    updated_count = 0
    total_count = 0
    for course in courses:
        for piece in classroom_assignments.fetch_coursework(service, course["id"]):
            assignment = classroom_assignments.normalize_assignment(course, piece)
            inserted = db.upsert_assignment(assignment)
            if inserted:
                new_count += 1
            else:
                updated_count += 1
            total_count += 1
        print(f"  {course['name']}: scanned")

    pending = len(db.list_assignments(status=db.STATUS_PENDING))
    print(
        f"\nDone. {total_count} assignments seen "
        f"({new_count} new, {updated_count} refreshed)."
    )
    print(f"{pending} are still pending (never processed).")


def cmd_show(status: str = None) -> None:
    print(f"\n--- Assignments ({status or 'all'}) ---")
    rows = db.list_assignments(status=status)
    if not rows:
        print("None.")
        return
    for index, row in enumerate(rows, start=1):
        print_assignment(row, index)


def build_info(row, material_text: str) -> dict:
    """The structured dict Phase 4 of the spec requires."""
    return {
        "course": row["course_name"],
        "assignment_title": row["title"],
        "description": row["description"] or "(no description provided)",
        "due_date": row["due_date"] or "(no due date)",
        "materials": material_text.strip() or "(no material text available)",
        "assignment_id": row["coursework_id"],
        "course_id": row["course_id"],
    }


def cmd_process() -> None:
    print("\n--- Process a pending assignment ---")
    rows = db.list_assignments(status=db.STATUS_PENDING)
    if not rows:
        print("No pending assignments. Run 'sync assignments' first.")
        return
    row = choose_assignment(rows, "Which assignment do you want to solve")
    if row is None:
        return

    drive = classroom_client.drive_service()
    try:
        materials = json.loads(row["materials"] or "[]")
    except json.JSONDecodeError:
        materials = []

    # 1) Download attachments
    dest = config.DOWNLOADS_DIR / _slug(row["course_name"])
    print("\n[1/4] Downloading attachments...")
    downloaded = downloader.download_attachments(drive, materials, dest)
    material_texts = []
    for item in downloaded:
        if item["path"]:
            print(f"      saved: {item['path'].name}")
            try:
                material_texts.append(
                    f"--- File: {item['name']} ---\n{reader.extract_text(item['path'])}"
                )
            except reader.UnsupportedFileTypeError as exc:
                print(f"      skipped: {exc}")
                material_texts.append(
                    f"--- File: {item['name']} ---\n[{exc}]"
                )
        else:
            print(f"      note: {item['name']} ({item['note']})")
            if item.get("note"):
                material_texts.append(
                    f"--- Material: {item['name']} ---\n({item['note']})"
                )

    info = build_info(row, "\n\n".join(material_texts))

    # 2) Solve with the AI (retry once on failure)
    print("[2/4] Asking the AI to solve...")
    solution = _solve_with_retry(info)
    if solution is None:
        print("Solving cancelled.")
        return

    # 3) Generate the document
    print("[3/4] Generating the answer document...")
    out_path = (
        config.GENERATED_DIR
        / f"{_slug(row['course_name'])}_{_slug(row['title'])}_{date.today().isoformat()}.docx"
    )
    saved = document_generator.generate_docx(info, solution, out_path)
    db.set_status(row["id"], db.STATUS_READY, answer_path=saved)
    print(f"      saved: {saved}")

    # 4) Review
    print("[4/4] Review time.")
    review_loop(db.get_assignment(row["id"]), info)


def _solve_with_retry(info: dict):
    """Call the AI, letting the user cancel or retry on failure."""
    while True:
        try:
            return solver.solve_assignment(info)
        except solver.AIError as exc:
            print(f"\nAI error: {exc}")
            choice = input("Retry [r] or cancel [c]: ").strip().lower()
            if choice == "c":
                return None


def review_loop(row, info: dict) -> None:
    """Phase 6: approve / regenerate / edit / cancel. NEVER auto-submits."""
    while True:
        print()
        print(f"Assignment: {row['title']}")
        print(f"Status:      {STATUS_LABELS.get(row['status'], row['status'])}")
        print(f"Answer file: {row['answer_path']}")
        print()
        print("[1] View solution")
        print("[2] Regenerate solution")
        print("[3] Edit output")
        print("[4] Approve and submit")
        print("[5] Cancel (keep draft, do not submit)")

        choice = input("\n> ").strip()
        if choice == "1":
            _print_solution_file(row["answer_path"])
        elif choice == "2":
            print("Regenerating...")
            try:
                row = _regenerate_and_save(row, info)
            except solver.AIError as exc:
                print(f"AI error: {exc}")
        elif choice == "3":
            row = _edit_solution(row, info)
        elif choice == "4":
            confirmed = _approve_and_submit(row)
            if confirmed:
                return
            print("\nNothing submitted. Back to review.\n")
        elif choice == "5":
            db.set_status(row["id"], db.STATUS_CANCELLED)
            print("Cancelled. The draft stays in the generated folder.")
            return
        else:
            print("Invalid choice.")


def _read_solution(path: str) -> list:
    """Read a generated .docx and return [(text, kind)] for terminal display."""
    from docx import Document

    doc = Document(path)
    rows = []
    for para in doc.paragraphs:
        style = para.style.name.lower()
        text = para.text.strip()
        if not text:
            continue
        if "heading 1" in style and text != "Solution":
            rows.append((text, "heading"))
        elif "heading" in style:
            rows.append((text, "subheading"))
        elif "bullet" in style:
            rows.append((text, "bullet"))
        else:
            rows.append((text, "plain"))
    return rows


def _print_solution_file(path) -> None:
    rows = _read_solution(path)
    print("\n" + "=" * 70)
    print(" " * 25 + "SOLUTION")
    print("=" * 70)
    for text, kind in rows:
        if kind == "heading":
            print(f"\n## {text}")
        elif kind == "subheading":
            print(f"\n### {text}")
        elif kind == "bullet":
            print(f"  - {text}")
        else:
            print(text)
    print("=" * 70)


def _regenerate_and_save(row, info):
    """Ask the AI again and replace the document + database path."""
    solution = solver.regenerate_solution(info)
    out_path = (
        config.GENERATED_DIR
        / f"{_slug(row['course_name'])}_{_slug(row['title'])}_{date.today().isoformat()}_v2.docx"
    )
    saved = document_generator.generate_docx(info, solution, out_path)
    db.set_status(row["id"], db.STATUS_READY, answer_path=saved)
    print(f"Saved new version: {saved}")
    return db.get_assignment(row["id"])


def _edit_solution(row, info: dict):
    """Let the user paste a corrected version (ends with a line 'DONE')."""
    print("\nPaste the full corrected solution text.")
    print("Finish with a line containing only: DONE")
    lines = []
    while True:
        line = input()
        if line.strip().upper() == "DONE":
            break
        lines.append(line)
    solution = "\n".join(lines)
    if not solution.strip():
        print("Nothing was pasted; keeping the current version.")
        return row
    out_path = (
        config.GENERATED_DIR
        / f"{_slug(row['course_name'])}_{_slug(row['title'])}_{date.today().isoformat()}_edited.docx"
    )
    saved = document_generator.generate_docx(info, solution, out_path)
    db.set_status(row["id"], db.STATUS_READY, answer_path=saved)
    print(f"Saved edited version: {saved}")
    return db.get_assignment(row["id"])


def _approve_and_submit(row) -> bool:
    """The ONLY path to submission — needs explicit typed approval.

    Returns True when the user approved (submission attempted), False if
    they declined.
    """
    print("\nApproval is required. Submitting will mark this assignment as")
    print("'turned in' on Google Classroom for you.")
    confirm = input("\nType APPROVE (all caps) to submit: ").strip()
    if confirm != "APPROVE":
        print("\nNot approved. Nothing was submitted.")
        return False

    print("\nTurning in your assignment...")
    try:
        result = classroom_submit.turn_in_assignment(
            row["course_id"], row["coursework_id"]
        )
        submission_id = result.get("id", "")
        db.record_submission(row["id"], row["course_id"], row["coursework_id"], submission_id)
        print("\nSUBMITTED successfully. State:",
              result.get("state", "unknown"))
    except classroom_submit.SubmitError as exc:
        print(f"\nSubmission failed: {exc}")
        print("Keeping the assignment as 'approved' so you can retry later")
        print("(option 8) or submit manually on the Classroom website.")
        db.set_status(row["id"], db.STATUS_APPROVED)
    return True


def cmd_submit_approved() -> None:
    print("\n--- Submit an approved assignment ---")
    rows = db.list_assignments(status=db.STATUS_APPROVED)
    if not rows:
        print("No approved assignments waiting to be submitted. Approve one")
        print("during processing (option 4 of the review menu) first.")
        return
    row = choose_assignment(rows, "Which one do you want to submit")
    if row is None:
        return
    _approve_and_submit(row)


# ---------------------------------------------------------------------
# Main menu
# ---------------------------------------------------------------------
def main_menu() -> None:
    print()
    print("=" * 60)
    print("  GOOGLE CLASSROOM AI ASSISTANT")
    print("=" * 60)
    print(" [1] Authenticate with Google")
    print(" [2] List my courses")
    print(" [3] Sync assignments (fetch from Classroom)")
    print(" [4] Show pending assignments")
    print(" [5] Show ready/awaiting-approval assignments")
    print(" [6] Process a pending assignment (solve + save DOCX)")
    print(" [7] Show all assignments in the local database")
    print(" [8] Submit an approved assignment")
    print(" [9] Show approved (waiting-turn-in) assignments")
    print(" [0] Exit")


def run() -> None:
    if not auth.has_saved_token():
        print("\nWelcome! First time? Set up credentials first:")
        print("  1. Follow README.md (Google Cloud console, enable APIs,")
        print("     create 'Desktop app' OAuth client).")
        print("  2. Save it as credentials/credentials.json")
    while True:
        main_menu()
        choice = input("\nChoose: ").strip()
        try:
            if choice == "1":
                cmd_auth()
            elif choice == "2":
                cmd_courses()
            elif choice == "3":
                cmd_sync()
            elif choice == "4":
                cmd_show(status=db.STATUS_PENDING)
            elif choice == "5":
                cmd_show(status=db.STATUS_READY)
            elif choice == "6":
                cmd_process()
            elif choice == "7":
                cmd_show()
            elif choice == "8":
                cmd_submit_approved()
            elif choice == "9":
                cmd_show(status=db.STATUS_APPROVED)
            elif choice == "0":
                print("Goodbye.")
                sys.exit(0)
            else:
                print("Invalid choice.")
        except (auth.AuthError,) as exc:
            print(f"\nAuthentication problem: {exc}")
        except HttpError as exc:
            print(f"\nGoogle API error (HTTP {exc.resp.status}).")
            if exc.resp.status == 403:
                print("Likely a missing permission or scope — check README.md scopes.")
            elif exc.resp.status == 429:
                print("Rate limit reached. Wait 30-60 seconds and try again.")
            elif exc.resp.status in (401, 440):
                print("Token expired/invalid — re-run option [1] to re-authenticate.")
            else:
                print(str(exc))
        except Exception as exc:  # keep the UI alive on unexpected failures
            print(f"\nUnexpected error: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    run()
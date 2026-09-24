"""Web UI for the Classroom AI Assistant (Flask).

WHAT: A browser interface over the exact same pipeline as app/main.py:
      courses -> sync -> process (download -> AI solve -> DOCX) -> review
      -> approve -> turn in. The approval step still requires typing APPROVE,
      exactly like the terminal version, so nothing is ever auto-submitted.

WHY:  The terminal app works, but a browser page is easier to look at. No
      business logic lives here -- this file only wires the existing modules
      to HTTP routes and renders templates.

HOW:  python -m app.web   then open http://127.0.0.1:5000
"""

import json
import re
import sys
import threading
import webbrowser
from datetime import date
from pathlib import Path

from docx import Document
from flask import Flask, redirect, render_template, request, url_for
from googleapiclient.errors import HttpError

from app import config
from app.ai import solver
from app.classroom import assignments as classroom_assignments
from app.classroom import auth, client as classroom_client, submit as classroom_submit
from app.database import db
from app.files import downloader, reader

db.init_db()

app = Flask(__name__, template_folder="web/templates")

STATUS_BADGE = {
    db.STATUS_PENDING: "secondary",
    db.STATUS_READY: "primary",
    db.STATUS_APPROVED: "warning",
    db.STATUS_SUBMITTED: "success",
    db.STATUS_CANCELLED: "light",
}


def _slug(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    return text[:60] or "assignment"


def _docs_to_plain(path) -> str:
    doc = Document(path)
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def _course_slug_name(row) -> str:
    return _slug(row["course_name"])


# ---------------------------------------------------------------------
# Index / dashboard
# ---------------------------------------------------------------------
@app.route("/")
def index():
    rows = db.list_assignments()
    counts = {s: len([r for r in rows if r["status"] == s]) for s in STATUS_BADGE}
    stats = [
        ("Pending", counts.get(db.STATUS_PENDING, 0), "secondary"),
        ("Ready", counts.get(db.STATUS_READY, 0), "primary"),
        ("Approved", counts.get(db.STATUS_APPROVED, 0), "warning"),
        ("Submitted", counts.get(db.STATUS_SUBMITTED, 0), "success"),
        ("Cancelled", counts.get(db.STATUS_CANCELLED, 0), "light"),
    ]
    return render_template(
        "index.html",
        rows=rows[:60],
        stats=stats,
        auth_ok=auth.has_saved_token(),
        msg=request.args.get("msg", ""),
    )


@app.route("/courses")
def courses():
    try:
        service = classroom_client.classroom_service()
        items = classroom_client.list_courses(service)
        course_rows = [
            {"name": classroom_client.course_summary(c)["name"], "id": c["id"]}
            for c in items
        ]
    except Exception as exc:
        course_rows, error = [], f"{type(exc).__name__}: {exc}"
    else:
        error = ""
    return render_template(
        "courses.html", courses=course_rows, error=error,
        msg=request.args.get("msg", ""),
    )


@app.route("/sync", methods=["POST"])
def sync():
    try:
        service = classroom_client.classroom_service()
        courses = classroom_client.list_courses(service)
        new = updated = total = 0
        for course in courses:
            for piece in classroom_assignments.fetch_coursework(service, course["id"]):
                assignment = classroom_assignments.normalize_assignment(course, piece)
                if db.upsert_assignment(assignment):
                    new += 1
                else:
                    updated += 1
                total += 1
        msg = f"Synced: {total} assignments ({new} new, {updated} refreshed)."
    except Exception as exc:
        msg = f"Sync failed: {type(exc).__name__}: {exc}"
    return redirect(url_for("index", msg=msg))


# ---------------------------------------------------------------------
# Process one assignment -> generate the answer document
# ---------------------------------------------------------------------
@app.route("/process/<int:assignment_id>")
def process_page(assignment_id):
    row = db.get_assignment(assignment_id)
    if row is None:
        return redirect(url_for("index", msg="Assignment not found."))
    return render_template(
        "process.html", row=row,
        current_status=row["status"],
    )


@app.route("/process/<int:assignment_id>/run", methods=["POST"])
def process_run(assignment_id):
    row = db.get_assignment(assignment_id)
    if row is None:
        return redirect(url_for("index", msg="Assignment not found."))
    if row["status"] != db.STATUS_PENDING:
        return redirect(url_for("review", assignment_id=assignment_id, msg="Already processed."))

    try:
        service = classroom_client.classroom_service()
        classroom_client.classroom_service()  # ensures credentials valid
        drive = classroom_client.drive_service()

        try:
            materials = json.loads(row["materials"] or "[]")
        except json.JSONDecodeError:
            materials = []

        dest = config.DOWNLOADS_DIR / _slug(row["course_name"])
        downloaded = downloader.download_attachments(drive, materials, dest)

        material_texts = []
        for item in downloaded:
            if item["path"]:
                try:
                    material_texts.append(
                        f"--- File: {item['name']} ---\n{reader.extract_text(item['path'])}"
                    )
                except reader.UnsupportedFileTypeError as exc:
                    material_texts.append(f"--- File: {item['name']} ---\n[{exc}]")
            elif item.get("note"):
                material_texts.append(f"--- Material: {item['name']} ---\n({item['note']})")

        info = {
            "course": row["course_name"],
            "assignment_title": row["title"],
            "description": row["description"] or "(no description provided)",
            "due_date": row["due_date"] or "(no due date)",
            "materials": "\n\n".join(material_texts).strip() or "(no material text available)",
            "assignment_id": row["coursework_id"],
            "course_id": row["course_id"],
        }

        solution = solver.solve_assignment(info)

        out_path = (
            config.GENERATED_DIR
            / f"{_slug(row['course_name'])}_{_slug(row['title'])}_{date.today().isoformat()}.docx"
        )
        saved = document_generate(info, solution, out_path)
        db.set_status(row["id"], db.STATUS_READY, answer_path=saved)
        return redirect(url_for("review", assignment_id=row["id"], msg="Solution generated."))
    except solver.AIError as exc:
        return redirect(url_for("review" if row["status"] == db.STATUS_READY else "process_page",
                                assignment_id=row["id"], msg=f"AI error: {exc}"))
    except Exception as exc:
        return redirect(url_for("process_page", assignment_id=row["id"],
                                msg=f"Failed: {type(exc).__name__}: {exc}"))


def document_generate(info, solution, out_path):
    from app.output import document_generator
    return document_generator.generate_docx(info, solution, out_path)


# ---------------------------------------------------------------------
# Review (approve / regenerate / edit / cancel)
# ---------------------------------------------------------------------
@app.route("/review/<int:assignment_id>")
def review(assignment_id):
    row = db.get_assignment(assignment_id)
    if row is None:
        return redirect(url_for("index", msg="Assignment not found."))

    solution_text, error = None, None
    if row["answer_path"] and Path(row["answer_path"]).exists():
        try:
            solution_text = _docs_to_plain(row["answer_path"])
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

    materials = []
    try:
        materials = json.loads(row["materials"] or "[]")
    except json.JSONDecodeError:
        pass

    return render_template(
        "review.html",
        row=row,
        solution_text=solution_text,
        materials=materials,
        error=error,
        msg=request.args.get("msg", ""),
    )


@app.route("/review/<int:assignment_id>/regenerate", methods=["POST"])
def review_regenerate(assignment_id):
    row = db.get_assignment(assignment_id)
    if row is None:
        return redirect(url_for("index"))
    try:
        info = _info_from_row(row)
        solution = solver.regenerate_solution(info)
        out_path = (
            config.GENERATED_DIR
            / f"{_slug(row['course_name'])}_{_slug(row['title'])}_{date.today().isoformat()}_v2.docx"
        )
        saved = document_generate(info, solution, out_path)
        db.set_status(row["id"], db.STATUS_READY, answer_path=saved)
        return redirect(url_for("review", assignment_id=row["id"], msg="Regenerated (v2)."))
    except Exception as exc:
        return redirect(url_for("review", assignment_id=row["id"],
                                msg=f"Regenerate failed: {type(exc).__name__}: {exc}"))


@app.route("/review/<int:assignment_id>/edit", methods=["POST"])
def review_edit(assignment_id):
    row = db.get_assignment(assignment_id)
    solution = request.form.get("solution_text", "").strip()
    if row is None or not solution:
        msg = "Nothing to save." if solution else "Assignment not found."
        return redirect(url_for("review", assignment_id=assignment_id, msg=msg))
    try:
        info = _info_from_row(row)
        out_path = (
            config.GENERATED_DIR
            / f"{_slug(row['course_name'])}_{_slug(row['title'])}_{date.today().isoformat()}_edited.docx"
        )
        saved = document_generate(info, solution, out_path)
        db.set_status(row["id"], db.STATUS_READY, answer_path=saved)
        return redirect(url_for("review", assignment_id=row["id"], msg="Saved edited version."))
    except Exception as exc:
        return redirect(url_for("review", assignment_id=row["id"],
                                msg=f"Edit failed: {type(exc).__name__}: {exc}"))


@app.route("/review/<int:assignment_id>/cancel", methods=["POST"])
def review_cancel(assignment_id):
    row = db.get_assignment(assignment_id)
    if row is not None:
        db.set_status(row["id"], db.STATUS_CANCELLED)
        return redirect(url_for("index", msg="Cancelled. Draft kept in the generated folder."))
    return redirect(url_for("index"))


@app.route("/review/<int:assignment_id>/approve", methods=["POST"])
def review_approve(assignment_id):
    row = db.get_assignment(assignment_id)
    if row is None:
        return redirect(url_for("index", msg="Assignment not found."))

    confirm = request.form.get("confirm", "").strip()
    if confirm != "APPROVE":
        return redirect(url_for("review", assignment_id=row["id"],
                                msg='You must type APPROVE (all caps) to submit.'))

    try:
        result = classroom_submit.turn_in_assignment(row["course_id"], row["coursework_id"])
        submission_id = result.get("id", "")
        db.record_submission(row["id"], row["course_id"], row["coursework_id"], submission_id)
        return redirect(url_for("index", msg="SUBMITTED successfully to Classroom."))
    except classroom_submit.SubmitError as exc:
        db.set_status(row["id"], db.STATUS_APPROVED)
        return redirect(url_for("review", assignment_id=row["id"],
                                msg=f"Submission failed ({exc}). Kept as approved."))


def _info_from_row(row) -> dict:
    try:
        materials = json.loads(row["materials"] or "[]")
    except json.JSONDecodeError:
        materials = []
    names = [m.get("name", "?") for m in materials if m.get("kind") == "drive_file"]
    return {
        "course": row["course_name"],
        "assignment_title": row["title"],
        "description": row["description"] or "(no description provided)",
        "due_date": row["due_date"] or "(no due date)",
        "materials": "Attachments: " + ", ".join(names) if names else "(no material text available)",
        "assignment_id": row["coursework_id"],
        "course_id": row["course_id"],
    }


if __name__ == "__main__":
    port = 5000
    threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    print(f"WEB_UI http://127.0.0.1:{port}", flush=True)
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
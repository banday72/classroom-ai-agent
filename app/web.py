"""Web UI for the Classroom AI Assistant (Flask).

WHAT: A browser interface over the exact same pipeline as app/main.py:
      login -> courses -> sync -> process (download -> AI solve -> DOCX)
      -> batch queue -> review -> approve -> turn in. Submission still
      requires typing APPROVE, exactly like the terminal version.

FEATURES
  - Password gate (WEB_PASSWORD in .env) so only you can open it
  - Dashboard with search / status / course filters and due-date alerts
  - Batch processing of many assignments with a live progress page
  - Ollama model switcher (list local models, change AI_MODEL live)
  - Light / dark theme toggle (saved in the browser)

HOW:  python -m app.web   then open http://127.0.0.1:5000
"""

import json
import os
import re
import secrets
import subprocess
import threading
import time
import urllib.request
import webbrowser
from datetime import date, datetime, timedelta
from pathlib import Path

from docx import Document
from flask import (
    Flask, redirect, render_template, request, session, url_for,
)
from googleapiclient.errors import HttpError

from app import config
from app.ai import solver
from app.classroom import assignments as classroom_assignments
from app.classroom import auth, client as classroom_client, submit as classroom_submit
from app.database import db
from app.files import downloader, reader
from app.output import document_generator

db.init_db()

app = Flask(__name__, template_folder="web/templates")
app.config["SECRET_KEY"] = os.getenv("WEB_SECRET") or secrets.token_hex(16)

WEB_PASSWORD = os.getenv("WEB_PASSWORD", "").strip() or "classroom"
OLLAMA_URL = "http://127.0.0.1:11434"

STATUS_BADGE = {
    db.STATUS_PENDING: "secondary",
    db.STATUS_READY: "primary",
    db.STATUS_APPROVED: "warning",
    db.STATUS_SUBMITTED: "success",
    db.STATUS_CANCELLED: "light",
}

JOB = {
    "running": False, "total": 0, "done": 0, "ok": 0, "fail": 0,
    "log": [], "started": "", "finished": False,
}
JOB_LOCK = threading.Lock()


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def _slug(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")
    return text[:60] or "assignment"


def _plain(path) -> str:
    doc = Document(path)
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def _due_state(due_date) -> str:
    """Return 'overdue' | 'soon' | 'ok' for due-date highlighting."""
    if not due_date:
        return "ok"
    try:
        due = datetime.strptime(str(due_date)[:10], "%Y-%m-%d").date()
    except ValueError:
        return "ok"
    today = date.today()
    if due < today:
        return "overdue"
    if due <= today + timedelta(days=2):
        return "soon"
    return "ok"


def _ensure_ollama() -> None:
    """Start Ollama if its local server is not answering."""
    try:
        urllib.request.urlopen(f"{OLLAMA_URL}/api/version", timeout=2)
        return
    except Exception:
        pass
    exe = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama app.exe"
    if exe.exists():
        try:
            subprocess.Popen([str(exe)], cwd=str(exe.parent))
        except OSError:
            return
    for _ in range(20):
        time.sleep(0.5)
        try:
            urllib.request.urlopen(f"{OLLAMA_URL}/api/version", timeout=2)
            return
        except Exception:
            continue


def _info_from_row(row) -> dict:
    try:
        materials = json.loads(row["materials"] or "[]")
    except json.JSONDecodeError:
        materials = []
    files = [m.get("name", "?") for m in materials if m.get("kind") == "drive_file"]
    return {
        "course": row["course_name"],
        "assignment_title": row["title"],
        "description": row["description"] or "(no description provided)",
        "due_date": row["due_date"] or "(no due date)",
        "materials": ("Attachments: " + ", ".join(files)) if files else "(no material text available)",
        "assignment_id": row["coursework_id"],
        "course_id": row["course_id"],
    }


def _process_assignment(row) -> tuple:
    """Download -> read -> AI solve -> DOCX -> status ready. Returns (ok, msg)."""
    if row["status"] != db.STATUS_PENDING:
        return False, f"Skipped (status is {row['status']})."

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

    info = _info_from_row(row)
    if material_texts:
        info["materials"] = "\n\n".join(material_texts)

    _ensure_ollama()
    solution = solver.solve_assignment(info)

    out_path = (
        config.GENERATED_DIR
        / f"{_slug(row['course_name'])}_{_slug(row['title'])}_{date.today().isoformat()}.docx"
    )
    saved = document_generator.generate_docx(info, solution, out_path)
    db.set_status(row["id"], db.STATUS_READY, answer_path=saved)
    return True, f"Solved: {row['title']}"


def _write_env(key: str, value: str) -> None:
    """Set or replace a KEY=VALUE line inside .env (keeps comments intact)."""
    path = config.BASE_DIR / ".env"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    for i, line in enumerate(lines):
        if line.split("=", 1)[0].strip() == key:
            lines[i] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------
# Auth gate
# ---------------------------------------------------------------------
@app.before_request
def require_login():
    if request.endpoint in ("login", "static"):
        return None
    if WEB_PASSWORD and session.get("authed"):
        return None
    return redirect(url_for("login", next=request.full_path))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        if secrets.compare_digest(request.form.get("password", "").strip(), WEB_PASSWORD):
            session["authed"] = True
            target = request.args.get("next", "")
            if target and target.startswith("/") and not target.startswith("//"):
                return redirect(target)
            return redirect(url_for("index"))
        error = "Wrong password. Try again."
    return render_template("login.html", error=error)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------
# Dashboard + filters
# ---------------------------------------------------------------------
@app.route("/")
def index():
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "")
    course = request.args.get("course", "").strip()

    rows = db.list_assignments()
    if status:
        rows = [r for r in rows if r["status"] == status]
    if course:
        rows = [r for r in rows if r["course_name"] == course]
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in r["title"].lower() or ql in r["course_name"].lower()
                or ql in (r["description"] or "").lower()]

    courses = sorted({r["course_name"] for r in db.list_assignments()})
    counts = {s: len([r for r in db.list_assignments() if r["status"] == s]) for s in STATUS_BADGE}
    stats = [
        ("Pending", counts.get(db.STATUS_PENDING, 0), "secondary"),
        ("Ready", counts.get(db.STATUS_READY, 0), "primary"),
        ("Approved", counts.get(db.STATUS_APPROVED, 0), "warning"),
        ("Submitted", counts.get(db.STATUS_SUBMITTED, 0), "success"),
        ("Cancelled", counts.get(db.STATUS_CANCELLED, 0), "light"),
    ]

    return render_template(
        "index.html",
        rows=[dict(r, due_state=_due_state(r["due_date"]),
                   badge=STATUS_BADGE.get(r["status"], "secondary")) for r in rows],
        stats=stats,
        courses=courses,
        auth_ok=auth.has_saved_token(),
        q=q, status=status, course=course,
        model=config.AI_MODEL,
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
        error = ""
    except Exception as exc:
        course_rows, error = [], f"{type(exc).__name__}: {exc}"
    return render_template("courses.html", courses=course_rows, error=error,
                           msg=request.args.get("msg", ""))


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
        msg = f"Synced {total} assignments ({new} new, {updated} refreshed)."
    except Exception as exc:
        msg = f"Sync failed: {type(exc).__name__}: {exc}"
    return redirect(url_for("index", msg=msg))


# ---------------------------------------------------------------------
# Single process + review
# ---------------------------------------------------------------------
@app.route("/process/<int:assignment_id>")
def process_page(assignment_id):
    row = db.get_assignment(assignment_id)
    if row is None:
        return redirect(url_for("index", msg="Assignment not found."))
    return render_template("process.html", row=row, current_status=row["status"],
                           msg=request.args.get("msg", ""))


@app.route("/process/<int:assignment_id>/run", methods=["POST"])
def process_run(assignment_id):
    row = db.get_assignment(assignment_id)
    if row is None:
        return redirect(url_for("index", msg="Assignment not found."))
    if row["status"] != db.STATUS_PENDING:
        return redirect(url_for("review", assignment_id=row["id"], msg="Already processed."))
    try:
        ok, msg = _process_assignment(row)
        return redirect(url_for("review", assignment_id=row["id"],
                                msg=msg if ok else msg))
    except solver.AIError as exc:
        return redirect(url_for("process_page", assignment_id=row["id"],
                                msg=f"AI error: {exc}"))
    except Exception as exc:
        return redirect(url_for("process_page", assignment_id=row["id"],
                                msg=f"Failed: {type(exc).__name__}: {exc}"))


@app.route("/review/<int:assignment_id>")
def review(assignment_id):
    row = db.get_assignment(assignment_id)
    if row is None:
        return redirect(url_for("index", msg="Assignment not found."))

    solution_text, error = None, None
    if row["answer_path"] and Path(row["answer_path"]).exists():
        try:
            solution_text = _plain(row["answer_path"])
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

    materials = []
    try:
        materials = json.loads(row["materials"] or "[]")
    except json.JSONDecodeError:
        pass

    return render_template(
        "review.html", row=row, solution_text=solution_text, materials=materials,
        error=error, badge=STATUS_BADGE.get(row["status"], "secondary"),
        msg=request.args.get("msg", ""),
    )


@app.route("/review/<int:assignment_id>/regenerate", methods=["POST"])
def review_regenerate(assignment_id):
    row = db.get_assignment(assignment_id)
    if row is None:
        return redirect(url_for("index"))
    try:
        info = _info_from_row(row)
        _ensure_ollama()
        solution = solver.regenerate_solution(info)
        out_path = (
            config.GENERATED_DIR
            / f"{_slug(row['course_name'])}_{_slug(row['title'])}_{date.today().isoformat()}_v2.docx"
        )
        saved = document_generator.generate_docx(info, solution, out_path)
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
        return redirect(url_for("review", assignment_id=assignment_id,
                                msg="Assignment not found." if row is None else "Nothing to save."))
    try:
        info = _info_from_row(row)
        out_path = (
            config.GENERATED_DIR
            / f"{_slug(row['course_name'])}_{_slug(row['title'])}_{date.today().isoformat()}_edited.docx"
        )
        saved = document_generator.generate_docx(info, solution, out_path)
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

    if not secrets.compare_digest(request.form.get("confirm", "").strip(), "APPROVE"):
        return redirect(url_for("review", assignment_id=row["id"],
                                msg='You must type APPROVE (all caps) to submit.'))

    try:
        result = classroom_submit.turn_in_assignment(row["course_id"], row["coursework_id"])
        db.record_submission(row["id"], row["course_id"], row["coursework_id"],
                             result.get("id", ""))
        return redirect(url_for("index", msg="SUBMITTED successfully to Classroom."))
    except classroom_submit.SubmitError as exc:
        db.set_status(row["id"], db.STATUS_APPROVED)
        return redirect(url_for("review", assignment_id=row["id"],
                                msg=f"Submission failed ({exc}). Kept as approved."))
    except Exception as exc:
        return redirect(url_for("review", assignment_id=row["id"],
                                msg=f"Cannot submit here: {type(exc).__name__}: {exc}"))


# ---------------------------------------------------------------------
# Batch processing (background thread + progress page)
# ---------------------------------------------------------------------
def _batch_worker(ids: list) -> None:
    with JOB_LOCK:
        JOB.update(running=True, finished=False, total=len(ids), done=0,
                   ok=0, fail=0, log=[], started=datetime.now().strftime("%H:%M:%S"))
    for aid in ids:
        row = db.get_assignment(aid)
        if row is None:
            with JOB_LOCK:
                JOB["log"].append(f"[{aid}] not found")
                JOB["done"] += 1
            continue
        try:
            ok, msg = _process_assignment(row)
        except Exception as exc:
            ok, msg = False, f"{row['title']}: {type(exc).__name__}: {exc}"
        with JOB_LOCK:
            JOB["log"].append(msg)
            JOB["done"] += 1
            if ok:
                JOB["ok"] += 1
            else:
                JOB["fail"] += 1
    with JOB_LOCK:
        JOB["running"] = False
        JOB["finished"] = True
        JOB["finished_at"] = datetime.now().strftime("%H:%M:%S")


@app.route("/batch")
def batch():
    rows = [r for r in db.list_assignments() if r["status"] == db.STATUS_PENDING]
    with JOB_LOCK:
        job = dict(JOB)
    return render_template("batch.html", rows=rows, job=job,
                           msg=request.args.get("msg", ""))


@app.route("/batch/run", methods=["POST"])
def batch_run():
    ids = [int(x) for x in request.form.getlist("ids") if x.isdigit()]
    if not ids:
        return redirect(url_for("batch", msg="Select at least one assignment."))
    with JOB_LOCK:
        if JOB["running"]:
            return redirect(url_for("batch", msg="A batch is already running."))
    threading.Thread(target=_batch_worker, args=(ids,), daemon=True).start()
    return redirect(url_for("batch_status"))


@app.route("/batch/status")
def batch_status():
    return render_template("batch_status.html")


@app.route("/batch/status.json")
def batch_status_json():
    with JOB_LOCK:
        return json.dumps(dict(JOB)), 200, {"Content-Type": "application/json"}


# ---------------------------------------------------------------------
# Ollama model switcher
# ---------------------------------------------------------------------
def _ollama_models() -> list:
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=5) as resp:
            data = json.loads(resp.read())
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


@app.route("/models")
def models():
    return render_template(
        "models.html",
        current=config.AI_MODEL,
        models=_ollama_models(),
        provider=config.AI_BASE_URL,
        msg=request.args.get("msg", ""),
    )


@app.route("/models/select", methods=["POST"])
def models_select():
    chosen = request.form.get("model", "").strip()
    if not chosen:
        return redirect(url_for("models", msg="No model chosen."))
    _write_env("AI_MODEL", chosen)
    config.AI_MODEL = chosen
    return redirect(url_for("models", msg=f"Model switched to {chosen}."))


if __name__ == "__main__":
    port = int(os.getenv("WEB_PORT", "5000"))
    threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    _ensure_ollama()
    print(f"WEB_UI on port {port} (open from any device on this WiFi)", flush=True)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
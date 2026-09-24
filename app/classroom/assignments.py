"""Fetching and normalizing classroom coursework (assignments).

WHAT: Talks to the Classroom API to get every assignment ("courseWork" is
      Google's official name for an assignment TO students) inside a course,
      then turns the raw response into simple Python dictionaries.
WHY:  The raw API response has a lot of nested fields. Normalizing it into
      a small flat dict means the rest of the app (database, AI, DOCX) works
      with easy data. This is where "assignment ID", "due date" and
      "attachments" get extracted.
HOW:
  - courses().courseWork().list() returns assignments + a pagination token.
  - dueDate/dueTime come as separate number dicts, so we join them into a
    readable "2026-10-01 23:59" string.
  - materials[] is a list; each material is one of driveFile / link /
    youtubeVideo. We convert them into a tiny dict for later downloading.
"""


def fetch_coursework(service, course_id: str) -> list:
    """Return ALL assignments for one course (handles pagination)."""
    request = service.courses().courseWork().list(courseId=course_id, pageSize=100)
    pieces = []
    while request is not None:
        response = request.execute()
        pieces.extend(response.get("courseWork", []))
        request = (
            service.courses().courseWork().list_next(request, response)
        )
    return pieces


def format_due_date(piece: dict):
    """Join Google's dueDate + dueTime dicts into a friendly string.

    Returns None when the assignment has no due date.
    """
    date = piece.get("dueDate") or {}
    time = piece.get("dueTime") or {}
    if not date:
        return None
    hours = time.get("hours", 0)
    minutes = time.get("minutes", 0)
    return (
        f"{date.get('year')}-{date.get('month'):02d}-{date.get('day'):02d} "
        f"{hours:02d}:{minutes:02d}"
    )


def summarize_materials(materials: list) -> list:
    """Turn raw materials[] into simple, readable attachment dicts.

    Each returned item is one of:
      {"kind": "drive_file", "name": "...", "id": "FILE_ID"}
      {"kind": "link", "name": "...", "url": "https://..."}
      {"kind": "youtube", "name": "...", "url": "https://..."}
    """
    result = []
    for material in materials or []:
        drive_file = material.get("driveFile")
        if drive_file and drive_file.get("driveFile"):
            df = drive_file["driveFile"]
            result.append(
                {"kind": "drive_file", "name": df.get("title", "file"), "id": df.get("id")}
            )
            continue
        link = material.get("link")
        if link:
            result.append(
                {"kind": "link", "name": link.get("title", "link"), "url": link.get("url")}
            )
            continue
        youtube = material.get("youtubeVideo")
        if youtube:
            result.append(
                {"kind": "youtube", "name": youtube.get("title", "video"), "url": youtube.get("link")}
            )
    return result


def normalize_assignment(course: dict, piece: dict) -> dict:
    """Wrap one raw courseWork object into our simple assignment dict."""
    return {
        "id": piece.get("id", ""),                 # assignment ID (courseWorkId)
        "course_id": course["id"],
        "course_name": course["name"],
        "title": piece.get("title", "Untitled"),
        "description": piece.get("description", "") or "",
        "due_date": format_due_date(piece),
        "max_points": piece.get("maxPoints"),
        "materials": summarize_materials(piece.get("materials", [])),
    }


def fetch_all_assignments(service, courses: list) -> list:
    """Fetch + normalize assignments across every course, in one call.

    Used by the 'sync' command. Returns a flat list of assignment dicts.
    """
    all_assignments = []
    for course in courses:
        for piece in fetch_coursework(service, course["id"]):
            all_assignments.append(normalize_assignment(course, piece))
    return all_assignments
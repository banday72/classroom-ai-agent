"""Turn in an approved assignment through the Google Classroom API.

WHAT: After you APPROVE a solution, this marks your student submission as
      turned in on Google Classroom.
WHY:  Every other submission step in the app exists to produce the answer.
      This is the ONLY module that writes to Classroom, and it is only ever
      called AFTER an explicit human confirmation — never automatically.
HOW:  Based on the official API (verified against Google's docs):
        studentSubmissions.turnIn(courseId, courseWorkId, id)
      requires the scope `classroom.coursework.me` and may only be called by
      the student who owns the submission. We first list your submissions
      for that coursework item to find its ID, then turn it in.
NOTE:  The API CANNOT upload files as attachments here — file attachments
       are added through the Classroom UI or Google Drive. turnIn simply
       flips your submission state to "submitted" (like clicking 'Turn in').
       Some organisations restrict this further; the API will then return
       PERMISSION_DENIED and we report it, never silently.
"""

from googleapiclient.errors import HttpError

from app.classroom.client import classroom_service


class SubmitError(Exception):
    """Raised when submission could not be completed (kept for the UI)."""


def find_my_submission(service, course_id: str, coursework_id: str) -> dict:
    """Locate the calling student's submission object for an assignment."""
    try:
        response = (
            service.courses()
            .courseWork()
            .studentSubmissions()
            .list(
                courseId=course_id,
                courseWorkId=coursework_id,
                states=["CREATED", "TURNED_IN", "RETURNED"],
                pageSize=50,
            )
            .execute()
        )
    except HttpError as exc:
        raise SubmitError(f"Could not read your submissions (HTTP {exc.resp.status}).") from exc

    submissions = response.get("studentSubmissions", [])
    # With the student scope this list holds only the caller's own submission.
    if not submissions:
        raise SubmitError(
            "No student submission found for this assignment. You may not be "
            "enrolled in this course as a student, or the assignment uses a "
            "format (e.g. a Google Form) that cannot be turned in via the API."
        )
    return submissions[0]


def turn_in_assignment(course_id: str, coursework_id: str) -> dict:
    """Turn in an approved assignment. Returns the submission object.

    Raises SubmitError with a readable message when it fails.
    """
    service = classroom_service()
    submission = find_my_submission(service, course_id, coursework_id)

    try:
        result = (
            service.courses()
            .courseWork()
            .studentSubmissions()
            .turnIn(
                courseId=course_id,
                courseWorkId=coursework_id,
                id=submission["id"],
            )
            .execute()
        )
    except HttpError as exc:
        reason = _explain_http_error(exc)
        raise SubmitError(reason) from exc

    return result


def _explain_http_error(exc: HttpError) -> str:
    status = exc.resp.status
    if status == 403:
        return (
            "PERMISSION_DENIED. Your account or organisation does not allow "
            "turning this in through the API. Turn it in manually from the "
            "Classroom website instead."
        )
    if status == 404:
        return "NOT_FOUND. The assignment or your submission no longer exists."
    if status == 429:
        return "Rate limited by Google. Wait a minute and try again."
    return f"Submission failed with HTTP {status}: {exc}"


__all__ = ["turn_in_assignment", "find_my_submission", "SubmitError"]
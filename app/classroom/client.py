"""API clients (services) for Google Classroom and Google Drive.

WHAT: Builds the "service" objects the official google-api-python-client
      library uses to talk to each Google API.
WHY:  A service object is a ready-made client: call service.courses().list()
      and the library builds the correct HTTP request for you.
HOW:  build(serviceName, version, credentials=...) returns the client.
      We wrap it in small functions so the rest of the app never deals
      with OAuth details. list_courses() also shows correct pagination:
      results come in pages of up to 100, so we keep fetching until there
      is no nextPageToken.
"""

from googleapiclient.discovery import build

from .auth import get_credentials


def classroom_service():
    """A client for the Google Classroom API (version v1)."""
    return build("classroom", "v1", credentials=get_credentials(), cache_discovery=False)


def drive_service():
    """A client for the Google Drive API (version v3), used for attachments."""
    return build("drive", "v3", credentials=get_credentials(), cache_discovery=False)


def list_courses(service, states=("ACTIVE",)):
    """Return every course the user belongs to, handling pagination.

    states: only ACTIVE courses by default. You could pass ("ACTIVE",
    "ARCHIVED") later if you want archived ones too.
    """
    request = service.courses().list(pageSize=100, courseStates=list(states))
    courses = []
    while request is not None:
        response = request.execute()
        courses.extend(response.get("courses", []))
        request = service.courses().list_next(request, response)
    return courses


def course_summary(course: dict) -> dict:
    """Keep only the fields we actually use from a raw course object."""
    return {
        "id": course.get("id", ""),
        "name": course.get("name", "Unnamed course"),
        "section": course.get("section", ""),
        "course_state": course.get("courseState", ""),
        "owner_id": course.get("ownerId", ""),
    }
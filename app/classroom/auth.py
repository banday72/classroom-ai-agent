"""Google OAuth 2.0 authentication for the Classroom Assistant.

WHAT: Handles the whole "log me into Google" process end to end.
WHY:  The Google Classroom/Drive APIs refuse to work until the user has
      granted permission. OAuth is Google's standard, safe way to ask for
      that permission WITHOUT ever giving your password to our script.
HOW:
  1. If we already have a saved token.json, load it.
  2. If the token is expired but has a refresh token, exchange it for a
     new one automatically (no window opens).
  3. Otherwise run the local-server OAuth flow: a browser opens, the user
     signs in and approves the scopes, Google redirects back to a local
     URL, and we trade the code for an access token.
  4. Save the token to token.json so the next run is instant.
"""

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from app.config import CREDENTIALS_FILE, SCOPES, TOKEN_FILE


class AuthError(Exception):
    """Raised when authentication cannot be completed (with a clear reason)."""


def _save_token(creds: Credentials) -> None:
    """Persist credentials so the user does not log in every time."""
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")


def get_credentials() -> Credentials:
    """Return valid credentials, refreshing or re-authenticating as needed."""
    creds = None

    # 1) Reuse a previously saved token, if present.
    if TOKEN_FILE.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        except ValueError as exc:  # corrupted / incompatible token file
            raise AuthError(
                f"token.json is corrupted or was created with different scopes "
                f"({exc}). Delete '{TOKEN_FILE}' and re-authenticate."
            ) from exc

    # 2) Refresh an expired token if we still have a refresh token.
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as exc:
            raise AuthError(
                "Could not refresh the expired token. Delete token.json and "
                "re-authenticate. (Refresh tokens are also invalidated if you "
                "revoked access or changed the OAuth client.)"
            ) from exc

    # 3) Already valid? Save a fresh copy and return.
    if creds and creds.valid:
        _save_token(creds)
        return creds

    # 4) No usable token: demand the OAuth client file, then run the flow.
    if not CREDENTIALS_FILE.exists():
        raise AuthError(
            f"Missing {CREDENTIALS_FILE}.\n"
            "1. Go to https://console.cloud.google.com/apis/credentials\n"
            "2. Create an OAuth Client ID of type 'Desktop app'\n"
            "3. Download the JSON and save it as credentials/credentials.json"
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
    # port=0 picks a random free port; the browser does the login.
    creds = flow.run_local_server(port=0)

    if not creds or not creds.valid:
        raise AuthError("Authentication failed: no valid credentials returned.")

    _save_token(creds)
    return creds


def has_saved_token() -> bool:
    """Quick check used by the CLI to show login status without side effects."""
    return TOKEN_FILE.exists()


def show_scopes() -> str:
    """Human-readable summary of exactly what we ask permission for."""
    names = {
        "classroom.courses.readonly": "read your Classroom course list",
        "classroom.coursework.me": "read your assignments and turn in your OWN work",
        "drive.readonly": "download files attached to assignments (read-only)",
    }
    lines = [f"  - {url.split('/')[-1]}: {names.get(url.split('/')[-1], url)}"
             for url in SCOPES]
    return "\n".join(lines)
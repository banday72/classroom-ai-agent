"""One-time: build the Google login URL and save the PKCE state to disk.

Run this whenever a fresh login link is needed. It does NOT wait for a
browser or start a server -- it only saves everything needed to finish the
login LATER, so nothing can time out:

    credentials/flow_state.json   {auth_url, redirect_uri, code_verifier}
    credentials/auth_url.txt      marker line (AUTH_URL <link>)
    Documents/login_link.txt      a clean, copy/paste-safe copy of the link

The saved code_verifier means scripts/exchange_code.py can trade in a code
even if the sign-in happened on another device long after this script ran.
"""

import json
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import webbrowser

from app import config
from google_auth_oauthlib.flow import InstalledAppFlow

FLOW_STATE_PATH = config.CREDENTIALS_DIR / "flow_state.json"
LOG_PATH = config.CREDENTIALS_DIR / "auth_url.txt"


def main() -> int:
    state = None
    if FLOW_STATE_PATH.exists():
        try:
            state = json.loads(FLOW_STATE_PATH.read_text(encoding="utf-8"))
            if not state.get("code_verifier"):
                state = None
        except (json.JSONDecodeError, OSError):
            state = None

    verifier = state.get("code_verifier") if state else None

    flow = InstalledAppFlow.from_client_secrets_file(str(config.CREDENTIALS_FILE), config.SCOPES)
    if verifier:
        flow.code_verifier = verifier

    with socket.socket() as _s:
        _s.bind(("127.0.0.1", 0))
        port = _s.getsockname()[1]
    flow.redirect_uri = f"http://localhost:{port}/"

    auth_url, state_token = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )
    # Encode scope separators as %20 (not '+') so the URL survives copy/paste.
    auth_url = auth_url.replace("+", "%20")

    state = {
        "auth_url": auth_url,
        "redirect_uri": flow.redirect_uri,
        "code_verifier": flow.code_verifier,
        "state_token": state_token,
    }
    config.CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    FLOW_STATE_PATH.write_text(json.dumps(state), encoding="utf-8")
    LOG_PATH.write_text("AUTH_URL " + auth_url, encoding="utf-8")

    try:
        (Path.home() / "Documents" / "login_link.txt").write_text(auth_url, encoding="utf-8")
        print("SAVED_DOC login_link.txt", flush=True)
    except OSError as exc:
        print("DOC_SAVE_FAILED " + str(exc), flush=True)

    print("AUTH_URL " + auth_url, flush=True)
    try:
        webbrowser.open(auth_url)
    except Exception as exc:
        print("BROWSER_FAILED " + str(exc), flush=True)
    print("NO_WAIT saved-state: finish later with scripts/exchange_code.py", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
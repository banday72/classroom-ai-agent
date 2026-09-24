"""Finish the login: trade a pasted OAuth code for credentials/token.json.

Usage:
    python scripts/exchange_code.py '<pasted code OR full callback URL>'

Reads the PKCE verifier and redirect_uri saved by make_login_link.py, so the
code can be exchanged even if the sign-in happened on another device -- at any
time before Google expires the code (a few minutes after "Allow").
"""

import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config
from google_auth_oauthlib.flow import InstalledAppFlow

FLOW_STATE_PATH = config.CREDENTIALS_DIR / "flow_state.json"


def extract_code(text: str):
    text = text.strip().strip("'\"")
    if "?" in text:
        query = parse_qs(urlparse(text).query)
        if "code" in query:
            return query["code"][0]
    match = re.search(r"code[=:]([0-9A-Za-z_\-~/+]+)", text)
    if match:
        return match.group(1).rstrip(".")
    return None


def main() -> int:
    if len(sys.argv) < 2:
        print("USAGE: exchange_code.py '<pasted code or callback URL>'", flush=True)
        return 1

    code = extract_code(sys.argv[1])
    if not code:
        print("COULD_NOT_PARSE_CODE", flush=True)
        return 1

    if not FLOW_STATE_PATH.exists():
        print("NO_FLOW_STATE -- run make_login_link.py first", flush=True)
        return 1
    state = json.loads(FLOW_STATE_PATH.read_text(encoding="utf-8"))

    flow = InstalledAppFlow.from_client_secrets_file(str(config.CREDENTIALS_FILE), config.SCOPES)
    flow.code_verifier = state["code_verifier"]
    flow.redirect_uri = state["redirect_uri"]

    try:
        flow.fetch_token(code=code)
    except Exception as exc:
        msg = str(exc).splitlines()[0][:400]
        print("TOKEN_EXCHANGE_FAILED " + msg, flush=True)
        return 1

    config.TOKEN_FILE.write_text(flow.credentials.to_json(), encoding="utf-8")
    print("AUTH_SUCCESS " + str(flow.credentials.expiry), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""One-step Google login -> saves credentials/token.json.

Two ways to complete the login:

  A) Same machine: a browser opens (or you paste the URL into this PC's
     browser) and Google redirects straight back to our local server.

  B) Any device (mobile): if this machine cannot open accounts.google.com
     (blocked network), open the printed URL on your PHONE, sign in and
     tap Allow. The phone will fail to load the localhost redirect -- copy
     that URL (it contains ?code=...) and save it to credentials/code.txt
     (or paste it in chat and I will save it). This script watches that
     file, extracts the code, and finishes the exchange.

The OAuth code expires in a few minutes, so keep it quick.
"""

import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import webbrowser

from app import config
from google_auth_oauthlib.flow import InstalledAppFlow

LOG_PATH = config.CREDENTIALS_DIR / "auth_url.txt"
CODE_PATH = config.CREDENTIALS_DIR / "code.txt"


class CallbackHandler(BaseHTTPRequestHandler):
    code = None
    error = None

    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        if "code" in query:
            CallbackHandler.code = query["code"][0]
        else:
            CallbackHandler.error = query.get("error", [None])[0]
        body = b"<html><body><h2>Login complete. You can close this window now.</h2></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def extract_code(text: str):
    """Pull the ?code=... value out of a URL or bare query string."""
    text = text.strip().strip("'\"")
    # accept full callback URL, a bare query string, or a raw code
    if "?" in text:
        query = parse_qs(urlparse(text.split("?")[-1]).query)
        if "code" in query:
            return query["code"][0]
    if text.startswith("4/") or "/" not in text:  # raw auth code shape
        return text
    return None


def read_code_file():
    if not CODE_PATH.exists():
        return None
    content = CODE_PATH.read_text(errors="ignore").strip()
    if not content:
        return None
    code = extract_code(content)
    if not code:
        return None
    try:
        CODE_PATH.unlink()
    except OSError:
        pass
    return code


def main() -> int:

    def clear_marker(text: str):
        LOG_PATH.write_text(text, encoding="utf-8")

    # Fresh start: remove a stale code file.
    if CODE_PATH.exists():
        CODE_PATH.unlink()

    server = HTTPServer(("127.0.0.1", 0), CallbackHandler)
    port = server.server_address[1]

    flow = InstalledAppFlow.from_client_secrets_file(str(config.CREDENTIALS_FILE), config.SCOPES)
    flow.redirect_uri = f"http://localhost:{port}/"

    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )

    # Encode scope separators as %20 (not '+') so the URL survives copy/paste.
    # Only scope matches use '+' in this query string, so a global replace is safe.
    auth_url = auth_url.replace("+", "%20")

    clear_marker("AUTH_URL " + auth_url)
    print("AUTH_URL " + auth_url, flush=True)

    # Also drop a clean copy on the Desktop area so copy/paste is never mangled.
    try:
        (Path.home() / "Documents" / "login_link.txt").write_text(auth_url, encoding="utf-8")
    except OSError:
        pass

    try:
        webbrowser.open(auth_url)
    except Exception as exc:
        print("BROWSER_FAILED " + str(exc), flush=True)

    # Server runs in a background thread (path A).
    def serve():
        while CallbackHandler.code is None and CallbackHandler.error is None:
            try:
                server.handle_request()
            except OSError:
                break

    threading.Thread(target=serve, daemon=True).start()

    # Main loop: wait for a code from the local server OR from code.txt (path B).
    deadline = time.time() + 900
    code = None
    while time.time() < deadline:
        err = CallbackHandler.error
        if err:
            clear_marker("AUTH_ERROR " + err)
            print("AUTH_ERROR " + err, flush=True)
            return 1
        if CallbackHandler.code:
            code = CallbackHandler.code
            break
        file_code = read_code_file()
        if file_code:
            code = file_code
            break
        time.sleep(0.5)

    if not code:
        clear_marker("TIMED_OUT after 15 minutes")
        print("TIMED_OUT", flush=True)
        return 1

    try:
        flow.fetch_token(code=code)
    except Exception as exc:
        clear_marker("TOKEN_EXCHANGE_FAILED " + str(exc)[:300])
        print("TOKEN_EXCHANGE_FAILED " + str(exc)[:300], flush=True)
        return 1

    config.TOKEN_FILE.write_text(flow.credentials.to_json(), encoding="utf-8")
    clear_marker("AUTH_SUCCESS " + str(flow.credentials.expiry))
    print("AUTH_SUCCESS " + str(flow.credentials.expiry), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
"""Helper: one-step Google login -> saves credentials/token.json.

Prints a login URL (also saves it to credentials/auth_url.txt). Open the URL
in a browser, complete the Google sign-in, and this script exchanges the
authorization code and saves token.json automatically.

HOW IT WORKS:
  - A tiny local HTTP server listens on a random localhost port.
  - We build the Google authorization URL with a redirect_uri pointing back
    to that local port (the loopback trick OAuth uses for desktop apps).
  - After you Allow in the browser, Google redirects to http://localhost:PORT/
    with a ?code=..., which this script receives and trades for a token.
  - token.json is saved; the console prints AUTH_SUCCESS.
"""

import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import webbrowser

from app import config
from google_auth_oauthlib.flow import InstalledAppFlow

LOG_PATH = config.CREDENTIALS_DIR / "auth_url.txt"


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


def main() -> int:
    server = HTTPServer(("127.0.0.1", 0), CallbackHandler)
    port = server.server_address[1]

    flow = InstalledAppFlow.from_client_secrets_file(str(config.CREDENTIALS_FILE), config.SCOPES)
    flow.redirect_uri = f"http://localhost:{port}/"

    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )

    LOG_PATH.write_text("AUTH_URL " + auth_url, encoding="utf-8")
    print("AUTH_URL " + auth_url, flush=True)

    try:
        webbrowser.open(auth_url)
    except Exception as exc:
        print("BROWSER_FAILED " + str(exc), flush=True)

    # Wait for Google's redirect back to our local server.
    while CallbackHandler.code is None and CallbackHandler.error is None:
        server.handle_request()

    if CallbackHandler.error is not None:
        LOG_PATH.write_text("AUTH_ERROR " + CallbackHandler.error, encoding="utf-8")
        print("AUTH_ERROR " + CallbackHandler.error, flush=True)
        return 1

    flow.fetch_token(code=CallbackHandler.code)   # exchanges code for token
    config.TOKEN_FILE.write_text(flow.credentials.to_json(), encoding="utf-8")

    LOG_PATH.write_text("AUTH_SUCCESS " + str(flow.credentials.expiry), encoding="utf-8")
    print("AUTH_SUCCESS " + str(flow.credentials.expiry), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
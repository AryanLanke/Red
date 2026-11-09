"""The optional Google sign-in for mail, calendar and contacts (plan.md task 7).

`python -m red google-login` runs Google's sign-in for installed apps once:
your browser opens Google's page, you approve, and Google sends the answer
back to a one-time local address (http://127.0.0.1:<port>/) with PKCE. The
refresh token goes in RED_HOME\\config\\google-token.json, which is outside
the repo and never committed. `python -m red google-logout` revokes it and
deletes the file.

Red needs your own OAuth client (Google Cloud Console > APIs & Services >
Credentials > Create OAuth client ID > Desktop app), downloaded as
RED_HOME\\config\\google-client.json. Red ships no shared client.

Only the standard library (urllib): no Google packages to install, so
nothing for Smart App Control to block. Every request goes to a fixed
https://*.googleapis.com address; what you say is only ever a parameter or
a JSON value, never part of the address.

Scopes, the smallest that do the job:
- gmail.readonly: count, list and read your mail
- gmail.send: send a new mail or a reply (Red reads it back first)
- calendar.events: read, add, move and delete events
- contacts.readonly: your contacts' names and addresses
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import logging
import secrets
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from typing import Callable

from .config import red_home

log = logging.getLogger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/contacts.readonly",
)
API_HOSTS = ("https://gmail.googleapis.com/", "https://www.googleapis.com/calendar/",
             "https://people.googleapis.com/")
TIMEOUT_SECONDS = 8.0
LOGIN_TIMEOUT_SECONDS = 300.0
MAX_BYTES = 2_000_000


class GoogleError(RuntimeError):
    """Something went wrong talking to Google; the message is fit to say."""


def client_path(home: Path | None = None) -> Path:
    return (home or red_home()) / "config" / "google-client.json"


def token_path(home: Path | None = None) -> Path:
    return (home or red_home()) / "config" / "google-token.json"


def signed_in(home: Path | None = None) -> bool:
    return token_path(home).is_file()


def load_client(home: Path | None = None) -> dict:
    """client_id and client_secret from the file Google Cloud Console gives you."""
    path = client_path(home)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise GoogleError(f"There's no Google client file at {path}. Make a Desktop app OAuth client "
                          "in Google Cloud Console and save its JSON there.") from None
    except (OSError, ValueError) as e:
        raise GoogleError(f"I couldn't read {path}: {e}") from e
    info = data.get("installed") or data.get("web") or data
    if not info.get("client_id") or not info.get("client_secret"):
        raise GoogleError(f"{path} has no client_id and client_secret.")
    return {"client_id": info["client_id"], "client_secret": info["client_secret"]}


def _post_form(url: str, fields: dict, opener: Callable = urllib.request.urlopen) -> dict:
    req = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode(),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with opener(req, timeout=TIMEOUT_SECONDS) as r:
            return json.loads(r.read(MAX_BYTES).decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        detail = e.read(2000).decode("utf-8", "replace")
        raise GoogleError(f"Google said no ({e.code}): {detail[:200]}") from e
    except (urllib.error.URLError, OSError, socket.timeout) as e:
        raise GoogleError("I can't reach Google right now.") from e


# --- signing in ----------------------------------------------------------------------

def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def auth_url(client_id: str, redirect_uri: str, state: str, challenge: str) -> str:
    return AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code",
        "scope": " ".join(SCOPES), "state": state, "code_challenge": challenge,
        "code_challenge_method": "S256", "access_type": "offline", "prompt": "consent"})


def _wait_for_code(server: http.server.HTTPServer, state: str, timeout: float) -> str:
    """Serve the one redirect from Google and return its code."""
    result: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - the http.server name
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            if query.get("state", [""])[0] != state:
                self.send_response(400)
                self.end_headers()
                return
            result["code"] = query.get("code", [""])[0]
            result["error"] = query.get("error", [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            done = "Red is signed in. You can close this tab." if result["code"] else \
                "Sign-in was cancelled. You can close this tab."
            self.wfile.write(f"<html><body style='font-family:sans-serif'><h2>{done}</h2></body></html>".encode())

        def log_message(self, *args):
            pass

    server.RequestHandlerClass = Handler
    server.timeout = 1.0
    end = time.monotonic() + timeout
    while "code" not in result and time.monotonic() < end:
        server.handle_request()
    if result.get("error"):
        raise GoogleError(f"Google sign-in was cancelled ({result['error']}).")
    if not result.get("code"):
        raise GoogleError("Google sign-in timed out.")
    return result["code"]


def login(home: Path | None = None, *, open_browser: Callable[[str], object] = webbrowser.open,
          opener: Callable = urllib.request.urlopen, timeout: float = LOGIN_TIMEOUT_SECONDS) -> Path:
    """Sign in once and save the refresh token. Returns the token file."""
    client = load_client(home)
    verifier, challenge = _pkce()
    state = secrets.token_urlsafe(24)
    server = http.server.HTTPServer(("127.0.0.1", 0), http.server.BaseHTTPRequestHandler)
    try:
        redirect = f"http://127.0.0.1:{server.server_address[1]}/"
        url = auth_url(client["client_id"], redirect, state, challenge)
        print(f"Opening Google's sign-in page. If it doesn't open, go to:\n  {url}")
        open_browser(url)
        code = _wait_for_code(server, state, timeout)
    finally:
        server.server_close()
    token = _post_form(TOKEN_URL, {"code": code, "client_id": client["client_id"],
                                   "client_secret": client["client_secret"], "redirect_uri": redirect,
                                   "grant_type": "authorization_code", "code_verifier": verifier}, opener)
    if not token.get("refresh_token"):
        raise GoogleError("Google didn't give Red a refresh token. Try google-login again.")
    return save_token(token, home)


def save_token(token: dict, home: Path | None = None) -> Path:
    path = token_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    keep = {"refresh_token": token["refresh_token"], "access_token": token.get("access_token", ""),
            "expires_at": time.time() + float(token.get("expires_in", 0)) - 60,
            "scope": token.get("scope", " ".join(SCOPES))}
    path.write_text(json.dumps(keep, indent=2), encoding="utf-8")
    return path


def logout(home: Path | None = None, opener: Callable = urllib.request.urlopen) -> bool:
    """Revoke the token at Google and delete the file. False if Red wasn't signed in."""
    path = token_path(home)
    if not path.is_file():
        return False
    try:
        token = json.loads(path.read_text(encoding="utf-8"))
        _post_form(REVOKE_URL, {"token": token.get("refresh_token", "")}, opener)
    except (GoogleError, OSError, ValueError) as e:
        log.warning("Couldn't revoke the Google token (deleting it anyway): %s", e)
    path.unlink(missing_ok=True)
    return True


# --- using the API -------------------------------------------------------------------

class GoogleApi:
    """Authorized JSON requests to Gmail, Calendar and People. Refreshes the access token."""

    def __init__(self, home: Path | None = None, opener: Callable = urllib.request.urlopen,
                 clock: Callable[[], float] = time.time):
        self._home = home
        self._open = opener
        self._clock = clock
        self._lock = threading.Lock()
        self._token: dict | None = None

    def _access_token(self) -> str:
        with self._lock:
            if self._token is None:
                try:
                    self._token = json.loads(token_path(self._home).read_text(encoding="utf-8"))
                except (OSError, ValueError) as e:
                    raise GoogleError("Red isn't signed in to Google. Run python -m red google-login.") from e
            if self._token.get("access_token") and self._token.get("expires_at", 0) > self._clock():
                return self._token["access_token"]
            client = load_client(self._home)
            fresh = _post_form(TOKEN_URL, {"client_id": client["client_id"],
                                           "client_secret": client["client_secret"],
                                           "refresh_token": self._token["refresh_token"],
                                           "grant_type": "refresh_token"}, self._open)
            self._token.update(access_token=fresh.get("access_token", ""),
                               expires_at=self._clock() + float(fresh.get("expires_in", 0)) - 60)
            try:
                token_path(self._home).write_text(json.dumps(self._token, indent=2), encoding="utf-8")
            except OSError:
                pass
            return self._token["access_token"]

    def request(self, method: str, url: str, params: dict | None = None, body: dict | None = None) -> dict:
        if not url.startswith(API_HOSTS):
            raise ValueError(f"not a Google API address: {url[:80]}")
        if params:
            url += "?" + urllib.parse.urlencode(params, doseq=True)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self._access_token()}", "Content-Type": "application/json"})
        try:
            with self._open(req, timeout=TIMEOUT_SECONDS) as r:
                raw = r.read(MAX_BYTES + 1)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise GoogleError("Google didn't allow that. Try python -m red google-login again.") from e
            if e.code == 404:
                raise GoogleError("Google couldn't find that.") from e
            raise GoogleError(f"Google returned an error ({e.code}).") from e
        except (urllib.error.URLError, OSError, socket.timeout) as e:
            raise GoogleError("I can't reach Google right now.") from e
        if len(raw) > MAX_BYTES:
            raise GoogleError("Google sent more than I can read.")
        return json.loads(raw.decode("utf-8")) if raw.strip() else {}

    def get(self, url: str, **params) -> dict:
        return self.request("GET", url, params=params)

    def post(self, url: str, body: dict, **params) -> dict:
        return self.request("POST", url, params=params, body=body)

    def patch(self, url: str, body: dict, **params) -> dict:
        return self.request("PATCH", url, params=params, body=body)

    def delete(self, url: str, **params) -> dict:
        return self.request("DELETE", url, params=params)


# --- contacts ------------------------------------------------------------------------

PEOPLE_URL = "https://people.googleapis.com/v1/people/me/connections"
CONTACTS_TTL = 3600.0
MAX_CONTACTS = 2000


class GoogleContacts:
    """Your Google Contacts as {spoken name: address}, fetched at most once an hour."""

    def __init__(self, api: GoogleApi, clock: Callable[[], float] = time.monotonic):
        self._api = api
        self._clock = clock
        self._cache: dict[str, str] | None = None
        self._at = 0.0

    def __call__(self) -> dict[str, str]:
        if self._cache is not None and self._clock() - self._at < CONTACTS_TTL:
            return self._cache
        found: dict[str, str] = {}
        token = None
        for _ in range(MAX_CONTACTS // 500):
            params = {"personFields": "names,emailAddresses", "pageSize": 500}
            if token:
                params["pageToken"] = token
            data = self._api.get(PEOPLE_URL, **params)
            for person in data.get("connections", []):
                emails = [e.get("value", "") for e in person.get("emailAddresses", []) if e.get("value")]
                if not emails:
                    continue
                for name in person.get("names", []):
                    for key in (name.get("displayName"), name.get("givenName")):
                        if key:
                            found.setdefault(" ".join(key.lower().split()), emails[0])
            token = data.get("nextPageToken")
            if not token:
                break
        self._cache, self._at = found, self._clock()
        return found

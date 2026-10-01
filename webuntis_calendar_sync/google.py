"""Google Calendar and Google Tasks over their REST APIs, with an OAuth refresh token.

Scopes are kept minimal:
  calendar.app.created  create calendars and manage only the calendars this app created
                        (it cannot see or change any other calendar of the account)
  tasks                 Google Tasks, for homework
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
from pathlib import Path

import requests

TIMEOUT = 30
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
CAL_API = "https://www.googleapis.com/calendar/v3"
TASKS_API = "https://tasks.googleapis.com/tasks/v1"
SCOPES = ("https://www.googleapis.com/auth/calendar.app.created "
          "https://www.googleapis.com/auth/tasks")
REDIRECT_URI = "http://127.0.0.1:8765/"  # loopback IP, as Google recommends for desktop apps


class GoogleError(Exception):
    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


def authorize_url(client_id: str) -> str:
    return AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",  # always hand out a refresh token
    })


def code_from(pasted: str) -> str:
    """Accept the whole redirect URL from the browser, or just the code."""
    pasted = pasted.strip()
    if pasted.startswith("http"):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(pasted).query)
        if "error" in query:
            raise GoogleError(f"Google refused: {query['error'][0]}")
        if "code" not in query:
            raise GoogleError("no code= in that URL")
        return query["code"][0]
    return pasted


def exchange_code(client_id: str, client_secret: str, code: str) -> dict:
    r = requests.post(TOKEN_URL, data={
        "code": code, "client_id": client_id, "client_secret": client_secret,
        "redirect_uri": REDIRECT_URI, "grant_type": "authorization_code"}, timeout=TIMEOUT)
    body = r.json()
    if not r.ok or "refresh_token" not in body:
        raise GoogleError(f"token exchange failed: {body.get('error')} {body.get('error_description', '')}")
    return {"refresh_token": body["refresh_token"], "scope": body.get("scope", "")}


def save_token(path: Path, token: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(token))
    os.chmod(tmp, 0o600)
    tmp.replace(path)


class GoogleAPI:
    def __init__(self, client_id: str, client_secret: str, token_file: Path) -> None:
        if not token_file.exists():
            raise GoogleError("not logged in to Google; run the google-login command first")
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = json.loads(token_file.read_text())["refresh_token"]
        self.session = requests.Session()
        self.access_token = ""
        self.expires = 0.0

    def _token(self) -> str:
        if time.time() > self.expires - 60:
            r = requests.post(TOKEN_URL, data={
                "client_id": self.client_id, "client_secret": self.client_secret,
                "refresh_token": self.refresh_token, "grant_type": "refresh_token"},
                timeout=TIMEOUT)
            body = r.json()
            if not r.ok:
                raise GoogleError(f"Google token refresh failed: {body.get('error')} "
                                  f"{body.get('error_description', '')} — run google-login again",
                                  r.status_code)
            self.access_token = body["access_token"]
            self.expires = time.time() + int(body.get("expires_in", 3600))
        return self.access_token

    def request(self, method: str, url: str, body: dict | None = None,
                ok: tuple[int, ...] = (200, 204)) -> dict:
        for attempt in range(4):
            r = self.session.request(method, url, json=body, timeout=TIMEOUT,
                                     headers={"Authorization": f"Bearer {self._token()}"})
            if r.status_code in (429, 500, 502, 503) and attempt < 3:
                time.sleep(2 ** attempt)  # rate limit / transient error: back off
                continue
            if r.status_code == 403 and "rateLimitExceeded" in r.text and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            break
        if r.status_code not in ok:
            try:
                message = r.json()["error"]["message"]
            except Exception:
                message = r.text[:200]
            raise GoogleError(f"{method} {urllib.parse.urlparse(url).path}: "
                              f"HTTP {r.status_code} {message}", r.status_code)
        return r.json() if r.content else {}

    # --- calendars --------------------------------------------------------

    def calendar_exists(self, calendar_id: str) -> bool:
        try:
            self.request("GET", f"{CAL_API}/calendars/{urllib.parse.quote(calendar_id)}")
            return True
        except GoogleError as e:
            if e.status in (403, 404):
                return False
            raise

    def create_calendar(self, name: str, tz: str) -> str:
        return self.request("POST", f"{CAL_API}/calendars",
                            {"summary": name, "timeZone": tz})["id"]

    def put_event(self, calendar_id: str, event: dict) -> None:
        """Create the event with our own id, or replace it if it already exists."""
        base = f"{CAL_API}/calendars/{urllib.parse.quote(calendar_id)}/events"
        try:
            self.request("POST", base, event)
        except GoogleError as e:
            if e.status != 409:  # 409 = an event with this id exists (maybe deleted)
                raise
            self.request("PUT", f"{base}/{event['id']}", event)

    def delete_event(self, calendar_id: str, event_id: str) -> None:
        try:
            self.request("DELETE", f"{CAL_API}/calendars/{urllib.parse.quote(calendar_id)}"
                                   f"/events/{event_id}")
        except GoogleError as e:
            if e.status not in (404, 410):
                raise

    # --- tasks ------------------------------------------------------------

    def tasklist_exists(self, list_id: str) -> bool:
        try:
            self.request("GET", f"{TASKS_API}/users/@me/lists/{list_id}")
            return True
        except GoogleError as e:
            if e.status in (403, 404):
                return False
            raise

    def create_tasklist(self, name: str) -> str:
        return self.request("POST", f"{TASKS_API}/users/@me/lists", {"title": name})["id"]

    def put_task(self, list_id: str, task: dict, task_id: str | None) -> str:
        """Update the task `task_id`, or create a new one; returns its id."""
        if task_id:
            try:
                return self.request("PATCH", f"{TASKS_API}/lists/{list_id}/tasks/{task_id}",
                                    task)["id"]
            except GoogleError as e:
                if e.status not in (400, 404):
                    raise
        return self.request("POST", f"{TASKS_API}/lists/{list_id}/tasks", task)["id"]

    def delete_task(self, list_id: str, task_id: str) -> None:
        try:
            self.request("DELETE", f"{TASKS_API}/lists/{list_id}/tasks/{task_id}")
        except GoogleError as e:
            if e.status not in (404, 410):
                raise

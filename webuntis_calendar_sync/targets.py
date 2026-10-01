"""Where the data goes: Nextcloud, any CalDAV server, Google Calendar + Tasks.

Each target turns lessons, exams and homework into its own format (`render`) and
knows how to write (`put`) and remove (`delete`) one entry. Deciding *what* to write
is done once, in __main__.apply, for all targets alike.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import ics
from .caldav import Calendar, CalDAVClient
from .google import GoogleAPI
from .untis import Exam, Homework, Lesson

KINDS = ("lessons", "exams", "homework")
USER_AGENT = "webuntis-calendar-sync/1.0"
# Slugs stay the same in every language; only the display names change.
SLUGS = {"lessons": "webuntis-stonneplang", "exams": "webuntis-pruefungen",
         "homework": "webuntis-hausaufgaben"}
COLORS = {"lessons": "#1E88E5", "exams": "#E53935", "homework": "#FB8C00"}


class Target:
    name = ""

    def prepare(self, meta: dict) -> set[str]:
        """Log in and make sure the calendars exist. `meta` is this target's saved state.
        Returns the kinds whose calendar was (re)created, so their entries are all rewritten."""
        return set()

    def key(self, kind: str, item) -> str:
        return f"webuntis-{kind[:-1] if kind != 'homework' else 'homework'}-{item.id}.ics"

    def render(self, kind: str, item) -> str:
        raise NotImplementedError

    def put(self, kind: str, key: str, payload: str, remote: str | None) -> str | None:
        raise NotImplementedError

    def delete(self, kind: str, key: str, remote: str | None) -> None:
        raise NotImplementedError

    def describe(self) -> list[str]:
        return []


# --- CalDAV / Nextcloud -----------------------------------------------------------


class CalDAVTarget(Target):
    def __init__(self, name: str, client: CalDAVClient, names: dict[str, str], lang: str,
                 tz: ZoneInfo, homework_as: str = "tasks",
                 calendar_urls: dict[str, str] | None = None) -> None:
        self.name = name
        self.client = client
        self.names = names
        self.lang = lang
        self.tz = tz
        self.homework_as = homework_as
        self.calendar_urls = {k: v for k, v in (calendar_urls or {}).items() if v}
        self.calendars: dict[str, Calendar] = {}

    def _component(self, kind: str) -> str:
        return "VTODO" if kind == "homework" and self.homework_as == "tasks" else "VEVENT"

    def prepare(self, meta: dict) -> set[str]:
        created = set()
        for kind in KINDS:
            if kind in self.calendar_urls:
                self.calendars[kind] = Calendar(self.client, self.calendar_urls[kind])
            else:
                self.calendars[kind], new = self.client.ensure(
                    SLUGS[kind], self.names[kind], self._component(kind), COLORS[kind])
                if new:
                    created.add(kind)
        return created

    def render(self, kind: str, item) -> str:
        if kind == "lessons":
            return ics.lesson(item, self.tz, self.lang)
        if kind == "exams":
            return ics.exam(item, self.tz, self.lang)
        if self.homework_as == "tasks":
            return ics.homework(item, self.lang)
        return ics.homework_event(item, self.lang)

    def put(self, kind: str, key: str, payload: str, remote: str | None) -> None:
        self.calendars[kind].put(key, payload)

    def delete(self, kind: str, key: str, remote: str | None) -> None:
        self.calendars[kind].delete(key)

    def describe(self) -> list[str]:
        existing = self.client.calendars()
        out = [f"{self.name}: login ok, {len(existing)} calendars"]
        for kind in KINDS:
            if kind in self.calendar_urls:
                out.append(f"  {self.names[kind]}: existing calendar {self.calendar_urls[kind]}")
            else:
                state = "exists" if SLUGS[kind] in existing else "will be created"
                out.append(f"  {self.names[kind]} ({self._component(kind)}): {state}")
        return out


# --- Google -------------------------------------------------------------------------


def google_event_id(key: str) -> str:
    """Google event ids may only use the letters a–v and 0–9 ("exam" and "homework" don't
    fit), so: 'webuntis-lesson-123.ics' → 'untisl123', exam → 'untise…', homework → 'untish…'."""
    kind, number = key.removeprefix("webuntis-").removesuffix(".ics").split("-", 1)
    return "untis" + {"lesson": "l", "exam": "e", "homework": "h"}[kind] + \
        "".join(ch for ch in number if ch.isdigit())


class GoogleTarget(Target):
    name = "google"

    def __init__(self, client_id: str, client_secret: str, token_file: Path,
                 names: dict[str, str], lang: str, tz: ZoneInfo,
                 homework_as: str = "tasks") -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_file = token_file
        self.names = names
        self.lang = lang
        self.tz = tz
        self.homework_as = homework_as
        self.api: GoogleAPI | None = None
        self.ids: dict[str, str] = {}

    def prepare(self, meta: dict) -> set[str]:
        self.api = GoogleAPI(self.client_id, self.client_secret, self.token_file)
        ids = meta.setdefault("ids", {})
        created = set()
        for kind in KINDS:
            if kind == "homework" and self.homework_as == "tasks":
                slot, exists, create = "tasks", self.api.tasklist_exists, \
                    lambda: self.api.create_tasklist(self.names[kind])
            else:
                slot, exists, create = kind, self.api.calendar_exists, \
                    lambda: self.api.create_calendar(self.names[kind], str(self.tz))
            if not (ids.get(slot) and exists(ids[slot])):
                ids[slot] = create()
                created.add(kind)
            self.ids[kind] = ids[slot]
        return created

    # rendering ---------------------------------------------------------------

    def _when(self, day, hm=None) -> dict:
        if hm is None:
            return {"date": day.isoformat()}
        local = datetime(day.year, day.month, day.day, hm[0], hm[1])
        return {"dateTime": local.isoformat(), "timeZone": str(self.tz)}

    def _event(self, text: ics.Text, start: dict, end: dict, busy: bool = True) -> dict:
        event = {
            "summary": text.summary,
            "description": text.description,
            "start": start,
            "end": end,
            # Google treats status "cancelled" as deleted, so a cancelled lesson stays
            # "confirmed" with the ❌ title, marked free and grey.
            "transparency": "opaque" if busy and not text.cancelled else "transparent",
            # No reminders of any kind: notifications are meant to come from elsewhere.
            "reminders": {"useDefault": False, "overrides": []},
        }
        if text.location:
            event["location"] = text.location
        if text.cancelled:
            event["colorId"] = "8"   # graphite
        elif text.changed:
            event["colorId"] = "6"   # tangerine
        return event

    def render(self, kind: str, item) -> str:
        if kind == "lessons":
            l: Lesson = item
            body = self._event(ics.lesson_text(l, self.lang), self._when(l.day, l.start),
                               self._when(l.day, l.end))
        elif kind == "exams":
            e: Exam = item
            text = ics.exam_text(e, self.lang)
            if e.start and e.end:
                body = self._event(text, self._when(e.day, e.start), self._when(e.day, e.end))
            else:
                body = self._event(text, self._when(e.day),
                                   self._when(ics._next_day(e.day)))
        else:
            h: Homework = item
            text = ics.homework_text(h, self.lang)
            if self.homework_as == "tasks":
                body = {"title": text.summary, "notes": text.description,
                        "due": f"{h.due.isoformat()}T00:00:00.000Z",
                        "status": "completed" if h.completed else "needsAction"}
            else:
                text.summary = ("✅ " if h.completed else "📚 ") + text.summary
                body = self._event(text, self._when(h.due), self._when(ics._next_day(h.due)),
                                   busy=False)
        return json.dumps(body, sort_keys=True, ensure_ascii=False)

    # writing -------------------------------------------------------------------

    def put(self, kind: str, key: str, payload: str, remote: str | None) -> str | None:
        body = json.loads(payload)
        if kind == "homework" and self.homework_as == "tasks":
            return self.api.put_task(self.ids[kind], body, remote)
        body["id"] = google_event_id(key)
        self.api.put_event(self.ids[kind], body)
        return None

    def delete(self, kind: str, key: str, remote: str | None) -> None:
        if kind == "homework" and self.homework_as == "tasks":
            if remote:
                self.api.delete_task(self.ids[kind], remote)
        else:
            self.api.delete_event(self.ids[kind], google_event_id(key))

    def describe(self) -> list[str]:
        api = GoogleAPI(self.client_id, self.client_secret, self.token_file)
        api._token()
        return ["google: login ok (token refreshed)",
                "  calendars and the task list are created on the first sync"]

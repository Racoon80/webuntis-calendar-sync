"""Google target against an in-memory fake of the Calendar and Tasks APIs."""

import json
import re
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest

from conftest import TODAY, exam, homework, lesson
from webuntis_calendar_sync import google, targets
from webuntis_calendar_sync.__main__ import DAY_OF, apply
from webuntis_calendar_sync.google import GoogleError

TZ = ZoneInfo("Europe/Luxembourg")
NAMES = {"lessons": "Timetable", "exams": "Exams", "homework": "Homework"}
WINDOW = (TODAY - timedelta(days=7), TODAY + timedelta(days=60))
EVENT_ID = re.compile(r"^[a-v0-9]{5,1024}$")


class FakeAPI:
    def __init__(self, *args):
        self.calendars, self.lists, self.n = {}, {}, 0

    def calendar_exists(self, cid):
        return cid in self.calendars

    def create_calendar(self, name, tz):
        self.n += 1
        self.calendars[f"cal{self.n}"] = {"name": name, "tz": tz, "events": {}}
        return f"cal{self.n}"

    def put_event(self, cid, event):
        assert EVENT_ID.match(event["id"]), event["id"]
        self.calendars[cid]["events"][event["id"]] = event

    def delete_event(self, cid, eid):
        self.calendars[cid]["events"].pop(eid, None)

    def tasklist_exists(self, lid):
        return lid in self.lists

    def create_tasklist(self, name):
        self.n += 1
        self.lists[f"list{self.n}"] = {"name": name, "tasks": {}}
        return f"list{self.n}"

    def put_task(self, lid, task, tid):
        if not tid or tid not in self.lists[lid]["tasks"]:
            self.n += 1
            tid = f"task{self.n}"
        self.lists[lid]["tasks"][tid] = task
        return tid

    def delete_task(self, lid, tid):
        self.lists[lid]["tasks"].pop(tid, None)


@pytest.fixture
def fake(monkeypatch, tmp_path):
    api = FakeAPI()
    monkeypatch.setattr(targets, "GoogleAPI", lambda *a: api)
    t = targets.GoogleTarget("id", "secret", tmp_path / "token.json", NAMES, "en", TZ)
    return t, api


def test_calendars_and_list_are_created_once(fake):
    t, api = fake
    meta = {}
    assert t.prepare(meta) == {"lessons", "exams", "homework"}
    assert t.prepare(meta) == set()
    assert sorted(c["name"] for c in api.calendars.values()) == ["Exams", "Timetable"]
    assert [l["name"] for l in api.lists.values()] == ["Homework"]


def test_events_have_valid_ids_and_no_reminders(fake):
    t, api = fake
    t.prepare({})
    seen = {}
    apply(t, "lessons", [lesson(1), lesson(2, code="cancelled"), lesson(3, code="irregular")],
          DAY_OF["lessons"], WINDOW, seen)
    events = api.calendars[t.ids["lessons"]]["events"]
    assert set(events) == {"untisl1", "untisl2", "untisl3"}
    for e in events.values():
        assert e["reminders"] == {"useDefault": False, "overrides": []}
        assert e["start"]["timeZone"] == "Europe/Luxembourg"
    cancelled = events["untisl2"]
    assert cancelled["summary"].startswith("❌ Cancelled")
    assert cancelled["transparency"] == "transparent" and cancelled["colorId"] == "8"
    assert "status" not in cancelled  # never "cancelled": that would delete it in Google

    apply(t, "lessons", [lesson(1)], DAY_OF["lessons"], WINDOW, seen)
    assert set(events) == {"untisl1"}


def test_all_day_exam(fake):
    t, api = fake
    t.prepare({})
    apply(t, "exams", [exam(4, timed=False)], DAY_OF["exams"], WINDOW, {})
    e = api.calendars[t.ids["exams"]]["events"]["untise4"]
    assert "date" in e["start"] and "date" in e["end"]


def test_homework_tasks_keep_their_google_id(fake):
    t, api = fake
    t.prepare({})
    seen = {}
    apply(t, "homework", [homework(7)], DAY_OF["homework"], WINDOW, seen)
    tasks = api.lists[t.ids["homework"]]["tasks"]
    assert len(tasks) == 1
    tid = seen["webuntis-homework-7.ics"]["remote"]
    assert tasks[tid]["status"] == "needsAction"
    assert re.match(r"^\d{4}-\d\d-\d\dT00:00:00\.000Z$", tasks[tid]["due"])

    # Done in WebUntis → same task updated, not a new one.
    apply(t, "homework", [homework(7, completed=True)], DAY_OF["homework"], WINDOW, seen)
    assert list(tasks) == [tid] and tasks[tid]["status"] == "completed"

    apply(t, "homework", [], DAY_OF["homework"], WINDOW, seen)
    assert tasks == {}


def test_rendering_is_stable(fake):
    t, _ = fake
    assert t.render("lessons", lesson(1)) == t.render("lessons", lesson(1))
    assert json.loads(t.render("homework", homework(1)))["title"].startswith("MATH:")


def test_oauth_helpers():
    url = google.authorize_url("my-client")
    assert "calendar.app.created" in url and "auth%2Ftasks" in url and "access_type=offline" in url
    assert google.code_from("http://127.0.0.1:8765/?code=abc123&scope=x") == "abc123"
    assert google.code_from("  abc123 ") == "abc123"
    with pytest.raises(GoogleError):
        google.code_from("http://127.0.0.1:8765/?error=access_denied")


def test_event_id_mapping():
    for key, expected in [("webuntis-lesson-123.ics", "untisl123"),
                          ("webuntis-exam-4.ics", "untise4"),
                          ("webuntis-homework-9.ics", "untish9")]:
        assert targets.google_event_id(key) == expected
        assert EVENT_ID.match(expected)


def test_homework_as_events_in_google(monkeypatch, tmp_path):
    api = FakeAPI()
    monkeypatch.setattr(targets, "GoogleAPI", lambda *a: api)
    t = targets.GoogleTarget("id", "secret", tmp_path / "t.json", NAMES, "en", TZ, "events")
    t.prepare({})
    assert api.lists == {} and len(api.calendars) == 3
    apply(t, "homework", [homework(5)], DAY_OF["homework"], WINDOW, {})
    event = api.calendars[t.ids["homework"]]["events"]["untish5"]
    assert event["summary"].startswith("📚") and event["transparency"] == "transparent"

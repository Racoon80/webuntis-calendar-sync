"""CalDAV target against a real (local) Radicale server."""

from datetime import timedelta
from zoneinfo import ZoneInfo

from conftest import TODAY, exam, homework, lesson
from webuntis_calendar_sync.__main__ import DAY_OF, apply
from webuntis_calendar_sync.caldav import CalDAVClient
from webuntis_calendar_sync.targets import CalDAVTarget

TZ = ZoneInfo("Europe/Luxembourg")
NAMES = {"lessons": "Stonneplang", "exams": "Prüfungen", "homework": "Hausaufgaben"}
WINDOW = (TODAY - timedelta(days=7), TODAY + timedelta(days=60))


def target(url, homework_as="tasks"):
    client = CalDAVClient.discover(url, "test", "test", "tests")
    return CalDAVTarget("caldav", client, NAMES, "lb", TZ, homework_as)


def test_discovery_finds_calendar_home(radicale):
    client = CalDAVClient.discover(radicale, "test", "test", "tests")
    assert client.home.endswith("/test/")


def test_full_cycle(radicale):
    t = target(radicale)
    created = t.prepare({})
    assert created == {"lessons", "exams", "homework"}
    assert t.prepare({}) == set()  # second time: nothing new

    seen = {}
    items = [lesson(1), lesson(2, code="cancelled"), lesson(3, day_offset=1)]
    assert apply(t, "lessons", items, DAY_OF["lessons"], WINDOW, seen) == \
        {"written": 3, "deleted": 0, "unchanged": 0}
    assert len(t.calendars["lessons"].objects()) == 3

    # Nothing changed in WebUntis → nothing written.
    assert apply(t, "lessons", items, DAY_OF["lessons"], WINDOW, seen)["unchanged"] == 3

    # One lesson changes, one disappears.
    items = [lesson(1, subject="PHYS"), lesson(2, code="cancelled")]
    counts = apply(t, "lessons", items, DAY_OF["lessons"], WINDOW, seen)
    assert counts == {"written": 1, "deleted": 1, "unchanged": 1}
    assert sorted(t.calendars["lessons"].objects()) == ["webuntis-lesson-1.ics",
                                                        "webuntis-lesson-2.ics"]


def test_no_alarms_and_status(radicale):
    t = target(radicale)
    t.prepare({})
    apply(t, "lessons", [lesson(5, code="cancelled")], DAY_OF["lessons"], WINDOW, {})
    apply(t, "homework", [homework(7)], DAY_OF["homework"], WINDOW, {})
    apply(t, "exams", [exam(9, timed=False)], DAY_OF["exams"], WINDOW, {})
    for kind in ("lessons", "homework", "exams"):
        cal = t.calendars[kind]
        for name in cal.objects():
            body = cal.client.request("GET", cal.url + name).text
            assert "VALARM" not in body
    body = t.client.request("GET", t.calendars["lessons"].url + "webuntis-lesson-5.ics").text
    assert "STATUS:CANCELLED" in body and "Fält aus" in body
    body = t.client.request("GET", t.calendars["homework"].url + "webuntis-homework-7.ics").text
    assert "BEGIN:VTODO" in body and "DUE;VALUE=DATE:" in body


def test_homework_as_events(radicale):
    t = target(radicale, homework_as="events")
    t.prepare({})
    apply(t, "homework", [homework(8, completed=True)], DAY_OF["homework"], WINDOW, {})
    body = t.client.request("GET", t.calendars["homework"].url + "webuntis-homework-8.ics").text
    assert "BEGIN:VEVENT" in body and "✅" in body and "DTSTART;VALUE=DATE" in body


def test_recreated_calendar_is_refilled(radicale):
    t = target(radicale)
    t.prepare({})
    seen = {}
    apply(t, "lessons", [lesson(1)], DAY_OF["lessons"], WINDOW, seen)
    t.client.request("DELETE", t.calendars["lessons"].url)  # user deletes the calendar
    assert "lessons" in t.prepare({})   # → recreated, caller resets its state
    seen = {}
    assert apply(t, "lessons", [lesson(1)], DAY_OF["lessons"], WINDOW, seen)["written"] == 1


def test_existing_calendar_url(radicale):
    first = target(radicale)
    first.prepare({})
    url = first.calendars["lessons"].url
    client = CalDAVClient.discover(radicale, "test", "test", "tests")
    t = CalDAVTarget("caldav", client, NAMES, "lb", TZ, "tasks",
                     {"lessons": url, "exams": "", "homework": ""})
    t.prepare({})
    assert t.calendars["lessons"].url == url

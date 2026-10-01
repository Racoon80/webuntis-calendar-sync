"""webuntis-nextcloud-sync: WebUntis timetable, exams and homework → Nextcloud.

  run      sync every SYNC_INTERVAL seconds (container default)
  sync     one sync, then exit
  check    log in to both sides and show counts, change nothing
  health   exit 0 if the last sync succeeded recently (Docker HEALTHCHECK)

Each kind of data gets its own calendar in the Nextcloud account: timetable
(events), exams (events) and homework (tasks). Titles and calendar names are in
LANGUAGE_TITLES: lb (default), de, fr or en.

An object is only written when its WebUntis content changed since the last
write, so edits in Nextcloud (a ticked-off homework, a deleted lesson) stay as
they are until WebUntis changes that entry.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import signal
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import ics
from .caldav import Calendar, CalDAVClient
from .untis import UntisClient

log = logging.getLogger("webuntis-nextcloud-sync")


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        raise SystemExit(f"missing environment variable {name}")
    return value.strip()


STATE_DIR = Path(env("STATE_DIR", "/data"))
STATE_FILE = STATE_DIR / "state.json"
STATUS_FILE = STATE_DIR / "status.json"
PREFIX = "webuntis-"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load(path: Path, default: dict) -> dict:
    return json.loads(path.read_text()) if path.exists() else default


def save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def untis() -> UntisClient:
    return UntisClient(env("WEBUNTIS_SERVER"), env("WEBUNTIS_SCHOOL"),
                       env("WEBUNTIS_USER"), env("WEBUNTIS_SECRET"))


def nextcloud() -> CalDAVClient:
    return CalDAVClient(env("NEXTCLOUD_URL"), env("NEXTCLOUD_USER"),
                        env("NEXTCLOUD_APP_PASSWORD"), "webuntis-nextcloud-sync/1.0")


LANG = os.environ.get("LANGUAGE_TITLES", "lb").strip().lower()
_names = ics.texts(LANG)["calendars"]

# The slugs stay the same in every language; only the display names change.
CALENDARS = {
    # key: (slug, display name, component, colour)
    "lessons": ("webuntis-stonneplang", os.environ.get("CALENDAR_LESSONS", _names["lessons"]),
                "VEVENT", "#1E88E5"),
    "exams": ("webuntis-pruefungen", os.environ.get("CALENDAR_EXAMS", _names["exams"]),
              "VEVENT", "#E53935"),
    "homework": ("webuntis-hausaufgaben", os.environ.get("CALENDAR_HOMEWORK", _names["homework"]),
                 "VTODO", "#FB8C00"),
}


def apply(cal: Calendar, desired: dict[str, tuple[str, str]], window: tuple[date, date],
          seen: dict[str, dict]) -> dict[str, int]:
    """Bring `cal` in line with `desired` ({file: (ics, day)}) inside `window`."""
    existing = cal.objects()
    counts = {"written": 0, "deleted": 0, "unchanged": 0}
    for name, (body, day) in desired.items():
        # DTSTAMP changes on every run; leave it out of the comparison.
        content = "\r\n".join(l for l in body.split("\r\n") if not l.startswith("DTSTAMP:"))
        digest = hashlib.sha256(content.encode()).hexdigest()
        known = seen.get(name)
        if known and known["hash"] == digest:
            counts["unchanged"] += 1
            continue
        cal.put(name, body)
        seen[name] = {"hash": digest, "day": day}
        counts["written"] += 1
    lo, hi = window
    for name in list(seen):
        if name in desired:
            continue
        day = date.fromisoformat(seen[name]["day"])
        if lo <= day <= hi:
            # Gone from WebUntis inside the window we asked for: remove it.
            if name in existing:
                cal.delete(name)
                counts["deleted"] += 1
            del seen[name]
    return counts


def sync_once() -> dict:
    tz = ZoneInfo(env("TZ", "Europe/Luxembourg"))
    today = datetime.now(tz).date()
    windows = {
        "lessons": (today - timedelta(days=7), today + timedelta(days=int(env("LESSON_DAYS", "28")))),
        "homework": (today - timedelta(days=14), today + timedelta(days=int(env("HOMEWORK_DAYS", "42")))),
        "exams": (today - timedelta(days=7), today + timedelta(days=int(env("EXAM_DAYS", "120")))),
    }
    with untis() as u:
        lessons = u.timetable(*windows["lessons"])
        homework = u.homework(*windows["homework"])
        exams = u.exams(*windows["exams"])
    log.info("WebUntis: %d lessons, %d homework, %d exams", len(lessons), len(homework), len(exams))

    desired = {
        "lessons": {f"{PREFIX}lesson-{l.id}.ics": (ics.lesson(l, tz, LANG), l.day.isoformat())
                    for l in lessons},
        "exams": {f"{PREFIX}exam-{e.id}.ics": (ics.exam(e, tz, LANG), e.day.isoformat())
                  for e in exams},
        "homework": {f"{PREFIX}homework-{h.id}.ics": (ics.homework(h, LANG), h.due.isoformat())
                     for h in homework},
    }

    nc = nextcloud()
    state = load(STATE_FILE, {"objects": {}})
    result = {}
    for key, (slug, name, component, color) in CALENDARS.items():
        cal = nc.ensure(slug, name, component, color)
        seen = state["objects"].setdefault(slug, {})
        result[key] = apply(cal, desired[key], windows[key], seen)
        save(STATE_FILE, state)
        log.info("%s: %s", name, result[key])
    return result


def cmd_sync() -> int:
    status = {"last_attempt": now()}
    try:
        status.update(ok=True, last_success=now(), result=sync_once())
        code = 0
    except Exception as e:  # keep the loop alive
        log.exception("sync failed: %s", e)
        status.update(ok=False, error=str(e))
        previous = load(STATUS_FILE, {})
        if previous.get("last_success"):
            status["last_success"] = previous["last_success"]
        code = 1
    save(STATUS_FILE, status)
    return code


def cmd_run() -> int:
    interval = int(env("SYNC_INTERVAL", "3600"))
    log.info("syncing every %ds", interval)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    while True:
        cmd_sync()
        time.sleep(interval)


def cmd_check() -> int:
    tz = ZoneInfo(env("TZ", "Europe/Luxembourg"))
    today = datetime.now(tz).date()
    with untis() as u:
        print("WebUntis login ok")
        print("  lessons next 7 days:", len(u.timetable(today, today + timedelta(days=7))))
        print("  homework next 14 days:", len(u.homework(today, today + timedelta(days=14))))
        print("  exams next 60 days:", len(u.exams(today, today + timedelta(days=60))))
    cals = nextcloud().calendars()
    print("Nextcloud login ok,", len(cals), "calendars")
    for key, (slug, name, *_rest) in CALENDARS.items():
        print(f"  {name}: {'exists' if slug in cals else 'will be created'}")
    return 0


def cmd_health() -> int:
    status = load(STATUS_FILE, {})
    if not status:
        return 0
    if not status.get("ok"):
        return 1
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(status["last_success"])).total_seconds()
    return 0 if age < 2 * int(env("SYNC_INTERVAL", "3600")) + 600 else 1


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(message)s")
    commands = {"run": cmd_run, "sync": cmd_sync, "check": cmd_check, "health": cmd_health}
    command = sys.argv[1] if len(sys.argv) > 1 else "run"
    if command not in commands:
        print(__doc__)
        sys.exit(64)
    sys.exit(commands[command]())


if __name__ == "__main__":
    main()

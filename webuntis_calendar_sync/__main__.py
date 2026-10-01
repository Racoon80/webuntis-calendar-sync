"""webuntis-calendar-sync: WebUntis timetable, exams and homework → your calendars.

  run           sync every SYNC_INTERVAL seconds (container default)
  sync          one sync, then exit
  check         log in everywhere and show what would happen; changes nothing
  google-login  one-time Google login (prints a link, asks for the result)
  health        exit 0 if the last sync succeeded recently (Docker HEALTHCHECK)

TARGETS is a comma-separated list of: nextcloud, caldav, google.
Each target gets three calendars: timetable, exams, homework (tasks or events).
Titles and calendar names are in LANGUAGE_TITLES: lb (default), de, fr or en.

An entry is only written when its WebUntis content changed since the last write,
so edits on the calendar side (a ticked-off homework, a deleted lesson) stay until
WebUntis changes that entry. Nothing ever carries a reminder or alarm.
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

from . import google, ics
from .caldav import CalDAVClient
from .targets import KINDS, SLUGS, USER_AGENT, CalDAVTarget, GoogleTarget, Target
from .untis import UntisClient

log = logging.getLogger("webuntis-calendar-sync")


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None or value.strip() == "" and default is None:
        raise SystemExit(f"missing environment variable {name}")
    return value.strip()


def opt(name: str) -> str:
    return os.environ.get(name, "").strip()


STATE_DIR = Path(env("STATE_DIR", "/data"))
STATE_FILE = STATE_DIR / "state.json"
STATUS_FILE = STATE_DIR / "status.json"
GOOGLE_TOKEN = STATE_DIR / "google-token.json"


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


def load_state() -> dict:
    state = load(STATE_FILE, {})
    if "objects" in state:
        # Version 0.1 kept only the Nextcloud state, keyed by calendar slug.
        by_slug = state.pop("objects")
        kinds = {kind: by_slug.get(slug, {}) for kind, slug in SLUGS.items()}
        state.setdefault("targets", {})["nextcloud"] = {"kinds": kinds, "meta": {}}
    state.setdefault("targets", {})
    return state


def timezone_() -> ZoneInfo:
    return ZoneInfo(env("TZ", "Europe/Luxembourg"))


def untis() -> UntisClient:
    return UntisClient(env("WEBUNTIS_SERVER"), env("WEBUNTIS_SCHOOL"),
                       env("WEBUNTIS_USER"), env("WEBUNTIS_SECRET"))


def calendar_names(lang: str) -> dict[str, str]:
    names = ics.texts(lang)["calendars"]
    return {"lessons": opt("CALENDAR_LESSONS") or names["lessons"],
            "exams": opt("CALENDAR_EXAMS") or names["exams"],
            "homework": opt("CALENDAR_HOMEWORK") or names["homework"]}


def homework_as(prefix: str, default: str = "tasks") -> str:
    value = (opt(f"{prefix}_HOMEWORK_AS") or default).lower()
    if value not in ("tasks", "events"):
        raise SystemExit(f"{prefix}_HOMEWORK_AS must be 'tasks' or 'events'")
    return value


def targets() -> list[Target]:
    names_ = [t.strip().lower() for t in
              (opt("TARGETS") or ("nextcloud" if opt("NEXTCLOUD_URL") else "")).split(",")
              if t.strip()]
    if not names_:
        raise SystemExit("set TARGETS (nextcloud, caldav and/or google)")
    lang = opt("LANGUAGE_TITLES").lower() or "lb"
    tz = timezone_()
    names = calendar_names(lang)
    out: list[Target] = []
    for name in names_:
        if name == "nextcloud":
            client = CalDAVClient.nextcloud(env("NEXTCLOUD_URL"), env("NEXTCLOUD_USER"),
                                            env("NEXTCLOUD_APP_PASSWORD"), USER_AGENT)
            out.append(CalDAVTarget("nextcloud", client, names, lang, tz,
                                    homework_as("NEXTCLOUD")))
        elif name == "caldav":
            client = CalDAVClient.discover(env("CALDAV_URL"), env("CALDAV_USER"),
                                           env("CALDAV_PASSWORD"), USER_AGENT)
            urls = {"lessons": opt("CALDAV_CALENDAR_URL_LESSONS"),
                    "exams": opt("CALDAV_CALENDAR_URL_EXAMS"),
                    "homework": opt("CALDAV_CALENDAR_URL_HOMEWORK")}
            out.append(CalDAVTarget("caldav", client, names, lang, tz,
                                    homework_as("CALDAV"), urls))
        elif name == "google":
            out.append(GoogleTarget(env("GOOGLE_CLIENT_ID"), env("GOOGLE_CLIENT_SECRET"),
                                    GOOGLE_TOKEN, names, lang, tz, homework_as("GOOGLE")))
        else:
            raise SystemExit(f"unknown target {name!r} (use nextcloud, caldav, google)")
    return out


def digest(payload: str) -> str:
    # DTSTAMP changes on every run and PRODID only names this program; neither is content.
    content = "\r\n".join(l for l in payload.split("\r\n")
                          if not l.startswith(("DTSTAMP:", "PRODID:")))
    return hashlib.sha256(content.encode()).hexdigest()


def digest_v1(payload: str) -> str:
    """How version 0.1 hashed an entry (it still had the old program name in PRODID)."""
    lines = []
    for line in payload.split("\r\n"):
        if line.startswith("DTSTAMP:"):
            continue
        lines.append("PRODID:-//webuntis-nextcloud-sync//LB" if line.startswith("PRODID:") else line)
    return hashlib.sha256("\r\n".join(lines).encode()).hexdigest()


def apply(target: Target, kind: str, items: list, day_of, window: tuple[date, date],
          seen: dict[str, dict]) -> dict[str, int]:
    """Bring one calendar of `target` in line with `items` inside `window`."""
    counts = {"written": 0, "deleted": 0, "unchanged": 0}
    wanted = set()
    for item in items:
        key = target.key(kind, item)
        wanted.add(key)
        payload = target.render(kind, item)
        h = digest(payload)
        known = seen.get(key)
        if known and known.get("v") != 2 and known["hash"] == digest_v1(payload):
            known.update(hash=h, v=2)  # written by 0.1 and unchanged: just upgrade the hash
        if known and known["hash"] == h:
            counts["unchanged"] += 1
            continue
        remote = target.put(kind, key, payload, (known or {}).get("remote"))
        seen[key] = {"hash": h, "day": day_of(item).isoformat(), "v": 2}
        if remote:
            seen[key]["remote"] = remote
        counts["written"] += 1
    lo, hi = window
    for key in list(seen):
        if key in wanted:
            continue
        if lo <= date.fromisoformat(seen[key]["day"]) <= hi:
            # Gone from WebUntis inside the window we asked for: remove it.
            target.delete(kind, key, seen[key].get("remote"))
            counts["deleted"] += 1
            del seen[key]
    return counts


def windows(today: date) -> dict[str, tuple[date, date]]:
    return {
        "lessons": (today - timedelta(days=7), today + timedelta(days=int(env("LESSON_DAYS", "28")))),
        "homework": (today - timedelta(days=14), today + timedelta(days=int(env("HOMEWORK_DAYS", "42")))),
        "exams": (today - timedelta(days=7), today + timedelta(days=int(env("EXAM_DAYS", "120")))),
    }


DAY_OF = {"lessons": lambda l: l.day, "exams": lambda e: e.day, "homework": lambda h: h.due}


def sync_once() -> dict:
    win = windows(datetime.now(timezone_()).date())
    with untis() as u:
        data = {"lessons": u.timetable(*win["lessons"]),
                "homework": u.homework(*win["homework"]),
                "exams": u.exams(*win["exams"])}
    log.info("WebUntis: %d lessons, %d homework, %d exams",
             len(data["lessons"]), len(data["homework"]), len(data["exams"]))

    state = load_state()
    result, failed = {}, []
    for target in targets():
        tstate = state["targets"].setdefault(target.name, {"kinds": {}, "meta": {}})
        try:
            for kind in target.prepare(tstate["meta"]):
                tstate["kinds"][kind] = {}  # new calendar: write everything again
            result[target.name] = {}
            for kind in KINDS:
                seen = tstate["kinds"].setdefault(kind, {})
                try:
                    result[target.name][kind] = apply(target, kind, data[kind], DAY_OF[kind],
                                                      win[kind], seen)
                finally:
                    save(STATE_FILE, state)
                log.info("%s %s: %s", target.name, kind, result[target.name][kind])
        except Exception as e:  # one broken target must not stop the others
            log.exception("%s: %s", target.name, e)
            result[target.name] = {"error": str(e)}
            failed.append(target.name)
        save(STATE_FILE, state)
    if failed:
        raise RuntimeError(f"sync failed for: {', '.join(failed)}")
    return result


def cmd_sync() -> int:
    status = {"last_attempt": now()}
    try:
        status.update(ok=True, last_success=now(), result=sync_once())
        code = 0
    except Exception as e:  # keep the loop alive
        log.error("sync failed: %s", e)
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
    today = datetime.now(timezone_()).date()
    with untis() as u:
        print("WebUntis login ok")
        print("  lessons next 7 days:", len(u.timetable(today, today + timedelta(days=7))))
        print("  homework next 14 days:", len(u.homework(today, today + timedelta(days=14))))
        print("  exams next 60 days:", len(u.exams(today, today + timedelta(days=60))))
    code = 0
    for target in targets():
        try:
            print("\n".join(target.describe()))
        except Exception as e:
            print(f"{target.name}: FAILED — {e}")
            code = 1
    return code


def cmd_google_login() -> int:
    client_id, client_secret = env("GOOGLE_CLIENT_ID"), env("GOOGLE_CLIENT_SECRET")
    print("1. Open this link in a browser and allow access:\n")
    print("   " + google.authorize_url(client_id) + "\n")
    print("2. Google then sends the browser to http://127.0.0.1:8765/?… — that page will")
    print("   not load, which is fine. Copy the whole address from the address bar.\n")
    pasted = input("3. Paste it here: ")
    token = google.exchange_code(client_id, client_secret, google.code_from(pasted))
    google.save_token(GOOGLE_TOKEN, token)
    print(f"Logged in. Token saved to {GOOGLE_TOKEN} (scopes: {token['scope']}).")
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
    commands = {"run": cmd_run, "sync": cmd_sync, "check": cmd_check,
                "google-login": cmd_google_login, "health": cmd_health}
    command = sys.argv[1] if len(sys.argv) > 1 else "run"
    if command not in commands:
        print(__doc__)
        sys.exit(64)
    sys.exit(commands[command]())


if __name__ == "__main__":
    main()

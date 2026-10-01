"""Build iCalendar objects for lessons, exams and homework, with titles in one of
several languages (lb, de, fr, en)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from .untis import Exam, Homework, Lesson

PRODID = "-//webuntis-nextcloud-sync//LB"

TEXTS = {
    "lb": {"cancelled": "❌ Fält aus", "changed": "Ännerung", "lesson": "Stonn", "exam": "Prüfung",
           "homework": "Hausaufgab", "subject": "Fach", "teacher": "Proff", "class": "Klass",
           "room": "Sall", "info": "Info", "title": "Titel", "type": "Aart", "task": "Aufgab",
           "remark": "Bemierkung", "assigned": "Opginn",
           "days": ["Méindeg", "Dënschdeg", "Mëttwoch", "Donneschdeg", "Freideg", "Samschdeg",
                    "Sonndeg"],
           "calendars": {"lessons": "Stonneplang", "exams": "Prüfungen",
                         "homework": "Hausaufgaben"}},
    "de": {"cancelled": "❌ Entfällt", "changed": "Änderung", "lesson": "Stunde", "exam": "Prüfung",
           "homework": "Hausaufgabe", "subject": "Fach", "teacher": "Lehrer", "class": "Klasse",
           "room": "Raum", "info": "Info", "title": "Titel", "type": "Art", "task": "Aufgabe",
           "remark": "Bemerkung", "assigned": "Aufgegeben",
           "days": ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag",
                    "Sonntag"],
           "calendars": {"lessons": "Stundenplan", "exams": "Prüfungen",
                         "homework": "Hausaufgaben"}},
    "fr": {"cancelled": "❌ Annulé", "changed": "modifié", "lesson": "Cours", "exam": "Examen",
           "homework": "Devoir", "subject": "Matière", "teacher": "Prof", "class": "Classe",
           "room": "Salle", "info": "Info", "title": "Titre", "type": "Type", "task": "Devoir",
           "remark": "Remarque", "assigned": "Donné le",
           "days": ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"],
           "calendars": {"lessons": "Horaire", "exams": "Examens", "homework": "Devoirs"}},
    "en": {"cancelled": "❌ Cancelled", "changed": "changed", "lesson": "Lesson", "exam": "Exam",
           "homework": "Homework", "subject": "Subject", "teacher": "Teacher", "class": "Class",
           "room": "Room", "info": "Info", "title": "Title", "type": "Type", "task": "Task",
           "remark": "Remark", "assigned": "Assigned",
           "days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
           "calendars": {"lessons": "Timetable", "exams": "Exams", "homework": "Homework"}},
}


def texts(lang: str) -> dict:
    return TEXTS.get(lang, TEXTS["lb"])


def _esc(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def _fold(line: str) -> str:
    out, raw = [], line.encode()
    while len(raw) > 75:
        cut = 75
        while (raw[cut] & 0xC0) == 0x80:  # don't split a UTF-8 character
            cut -= 1
        out.append(raw[:cut].decode())
        raw = b" " + raw[cut:]
    out.append(raw.decode())
    return "\r\n".join(out)


def _utc(day: date, hm: tuple[int, int], tz: ZoneInfo) -> str:
    local = datetime(day.year, day.month, day.day, hm[0], hm[1], tzinfo=tz)
    return local.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# On purpose there is never a VALARM: Nextcloud turns alarms into push and e-mail
# reminders, and notifications are meant to come from somewhere else.
def _wrap(component: str, props: list[tuple[str, str]]) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODID}", f"BEGIN:{component}",
             f"DTSTAMP:{stamp}"]
    lines += [_fold(f"{k}:{v}") for k, v in props if v]
    lines += [f"END:{component}", "END:VCALENDAR", ""]
    body = "\r\n".join(lines)
    assert "BEGIN:VALARM" not in body
    return body


def _desc(*parts: tuple[str, str]) -> str:
    return _esc("\n".join(f"{label}: {value}" for label, value in parts if value))


def lesson(l: Lesson, tz: ZoneInfo, lang: str = "lb") -> str:
    t = texts(lang)
    subject = l.subject or l.subject_long or t["lesson"]
    if l.code == "cancelled":
        summary, status = f"{t['cancelled']}: {subject}", "CANCELLED"
    elif l.code == "irregular":
        summary, status = f"🔄 {subject} ({t['changed']})", "CONFIRMED"
    else:
        summary, status = subject, "CONFIRMED"
    return _wrap("VEVENT", [
        ("UID", f"webuntis-lesson-{l.id}"),
        ("SUMMARY", _esc(summary)),
        ("DTSTART", _utc(l.day, l.start, tz)),
        ("DTEND", _utc(l.day, l.end, tz)),
        ("LOCATION", _esc(", ".join(l.rooms))),
        ("DESCRIPTION", _desc((t["subject"], l.subject_long or l.subject),
                              (t["teacher"], ", ".join(l.teachers)),
                              (t["class"], ", ".join(l.classes)),
                              (t["info"], l.info))),
        ("STATUS", status),
        ("TRANSP", "OPAQUE"),
    ])


def exam(e: Exam, tz: ZoneInfo, lang: str = "lb") -> str:
    t = texts(lang)
    kind = e.exam_type or t["exam"]
    summary = f"📝 {kind}: {e.subject}" if e.subject else f"📝 {e.name or kind}"
    if e.start and e.end:
        when = [("DTSTART", _utc(e.day, e.start, tz)), ("DTEND", _utc(e.day, e.end, tz))]
    else:
        nxt = date.fromordinal(e.day.toordinal() + 1)
        when = [("DTSTART;VALUE=DATE", e.day.strftime("%Y%m%d")),
                ("DTEND;VALUE=DATE", nxt.strftime("%Y%m%d"))]
    return _wrap("VEVENT", [
        ("UID", f"webuntis-exam-{e.id}"),
        ("SUMMARY", _esc(summary)),
        *when,
        ("LOCATION", _esc(", ".join(e.rooms))),
        ("DESCRIPTION", _desc((t["subject"], e.subject), (t["title"], e.name),
                              (t["type"], e.exam_type), (t["teacher"], ", ".join(e.teachers)),
                              (t["info"], e.text))),
        ("STATUS", "CONFIRMED"),
    ])


def homework(h: Homework, lang: str = "lb") -> str:
    t = texts(lang)
    first = (h.text.splitlines() or [""])[0].strip()
    if len(first) > 80:
        first = first[:77] + "…"
    summary = f"{h.subject}: {first}" if h.subject else (first or t["homework"])
    weekday = t["days"][h.assigned.weekday()]
    props = [
        ("UID", f"webuntis-homework-{h.id}"),
        ("SUMMARY", _esc(summary)),
        ("DUE;VALUE=DATE", h.due.strftime("%Y%m%d")),
        ("DTSTART;VALUE=DATE", h.assigned.strftime("%Y%m%d")),
        ("DESCRIPTION", _desc((t["subject"], h.subject), (t["task"], h.text),
                              (t["remark"], h.remark),
                              (t["assigned"], f"{weekday}, {h.assigned:%d.%m.%Y}"))),
        ("STATUS", "COMPLETED" if h.completed else "NEEDS-ACTION"),
    ]
    if h.completed:
        props.append(("PERCENT-COMPLETE", "100"))
    return _wrap("VTODO", props)

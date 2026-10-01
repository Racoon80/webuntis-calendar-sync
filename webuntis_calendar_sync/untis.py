"""WebUntis client: login with the app secret, timetable, homework, exams.

The timetable comes from the documented JSON-RPC API. Homework and exams are
not part of it; they come from the REST routes the WebUntis web app uses,
with the same session.

The login uses the secret from WebUntis → Profile → Data access ("Zugriff über
Untis Mobile"). It works for SSO accounts (e.g. IAM) where the password login
of the JSON-RPC API is refused.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import struct
import time
from dataclasses import dataclass, field
from datetime import date, datetime

import requests

TIMEOUT = 30
USER_AGENT = "webuntis-calendar-sync"
ELEMENT_TYPES = {"KLASSE": 1, "TEACHER": 2, "SUBJECT": 3, "ROOM": 4, "STUDENT": 5}


class UntisError(Exception):
    pass


def totp(secret: str, at: float | None = None) -> str:
    key = base64.b32decode(secret.strip().upper() + "=" * (-len(secret.strip()) % 8))
    counter = int((at or time.time()) // 30)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 15
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % 1_000_000).zfill(6)


def _date(value: int | str) -> date:
    return datetime.strptime(str(value), "%Y%m%d").date()


def _time(value: int | str) -> tuple[int, int]:
    v = int(value)
    return v // 100, v % 100


def _exam_id(e: dict) -> int:
    """A stable id for exams WebUntis returns with id 0 (seen with student accounts)."""
    key = "|".join(str(e.get(k) or "") for k in
                   ("examDate", "startTime", "subject", "examType", "name"))
    return int(hashlib.sha1(key.encode()).hexdigest()[:12], 16)


@dataclass
class Lesson:
    id: int
    day: date
    start: tuple[int, int]
    end: tuple[int, int]
    subject: str
    subject_long: str
    teachers: list[str]
    rooms: list[str]
    classes: list[str]
    code: str            # "", "cancelled" or "irregular"
    info: str            # substitution text, lesson text, info


@dataclass
class Homework:
    id: int
    subject: str
    assigned: date
    due: date
    text: str
    remark: str
    completed: bool


@dataclass
class Exam:
    id: int
    day: date
    start: tuple[int, int] | None
    end: tuple[int, int] | None
    subject: str
    name: str
    exam_type: str
    text: str
    teachers: list[str] = field(default_factory=list)
    rooms: list[str] = field(default_factory=list)


class UntisClient:
    def __init__(self, server: str, school: str, user: str, secret: str) -> None:
        self.base = f"https://{server}/WebUntis"
        self.school = school
        self.user = user
        self.secret = secret
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.person_id: int | None = None
        self.person_type: int | None = None

    def __enter__(self) -> UntisClient:
        self.login()
        return self

    def __exit__(self, *exc) -> None:
        self.logout()

    def _rpc(self, method: str, params=None, path: str = "jsonrpc.do", extra=None):
        r = self.session.post(
            f"{self.base}/{path}",
            params={"school": self.school, **(extra or {})},
            json={"id": "1", "method": method, "params": params or {}, "jsonrpc": "2.0"},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        body = r.json()
        if "error" in body:
            err = body["error"]
            raise UntisError(f"{method}: {err.get('code')} {err.get('message')}")
        return body.get("result")

    def login(self) -> None:
        result = self._rpc(
            "getUserData2017",
            [{"auth": {"clientTime": int(time.time() * 1000), "user": self.user,
                       "otp": totp(self.secret)}}],
            path="jsonrpc_intern.do",
            extra={"m": "getUserData2017", "v": "i2.2"},
        )
        user = (result or {}).get("userData") or {}
        self.person_id = user.get("elemId")
        self.person_type = ELEMENT_TYPES.get(user.get("elemType"), 5)
        if not self.person_id:
            raise UntisError("login worked but no person id came back")

    def logout(self) -> None:
        try:
            self._rpc("logout")
        except Exception:
            pass

    def _get(self, path: str, **params) -> dict:
        r = self.session.get(f"{self.base}/{path}", params=params, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json().get("data") or {}

    # --- data -------------------------------------------------------------

    def timetable(self, start: date, end: date) -> list[Lesson]:
        rows = self._rpc("getTimetable", {"options": {
            "element": {"id": self.person_id, "type": self.person_type},
            "startDate": int(start.strftime("%Y%m%d")),
            "endDate": int(end.strftime("%Y%m%d")),
            "showInfo": True, "showSubstText": True, "showLsText": True,
            "klasseFields": ["name"], "roomFields": ["name", "longname"],
            "subjectFields": ["name", "longname"], "teacherFields": ["name", "longname"],
        }}) or []
        lessons = []
        for row in rows:
            subjects = row.get("su") or []
            info = " · ".join(t for t in (row.get("substText"), row.get("lstext"),
                                          row.get("info")) if t)
            lessons.append(Lesson(
                id=row["id"],
                day=_date(row["date"]),
                start=_time(row["startTime"]),
                end=_time(row["endTime"]),
                subject=subjects[0].get("name", "") if subjects else (row.get("lstext") or ""),
                subject_long=subjects[0].get("longname", "") if subjects else "",
                teachers=[t.get("longname") or t.get("name", "") for t in row.get("te") or []
                          if t.get("name") or t.get("longname")],
                rooms=[r.get("name", "") for r in row.get("ro") or [] if r.get("name")],
                classes=[k.get("name", "") for k in row.get("kl") or [] if k.get("name")],
                code=row.get("code") or "",
                info=info,
            ))
        return lessons

    def homework(self, start: date, end: date) -> list[Homework]:
        data = self._get("api/homeworks/lessons",
                         startDate=start.strftime("%Y%m%d"), endDate=end.strftime("%Y%m%d"))
        subjects = {l.get("id"): l.get("subject", "") for l in data.get("lessons") or []}
        items = []
        for h in data.get("homeworks") or []:
            items.append(Homework(
                id=h["id"],
                subject=subjects.get(h.get("lessonId"), ""),
                assigned=_date(h.get("date") or h["dueDate"]),
                due=_date(h["dueDate"]),
                text=(h.get("text") or "").strip(),
                remark=(h.get("remark") or "").strip(),
                completed=bool(h.get("completed")),
            ))
        return items

    def exams(self, start: date, end: date) -> list[Exam]:
        data = self._get("api/exams", startDate=start.strftime("%Y%m%d"),
                         endDate=end.strftime("%Y%m%d"), studentId=self.person_id, klasseId=-1)
        items = []
        for e in data.get("exams") or []:
            items.append(Exam(
                id=e.get("id") or _exam_id(e),
                day=_date(e["examDate"]),
                start=_time(e["startTime"]) if e.get("startTime") else None,
                end=_time(e["endTime"]) if e.get("endTime") else None,
                subject=e.get("subject") or "",
                name=e.get("name") or "",
                exam_type=e.get("examType") or "",
                text=(e.get("text") or "").strip(),
                teachers=[t for t in e.get("teachers") or [] if isinstance(t, str)],
                rooms=[r for r in e.get("rooms") or [] if isinstance(r, str)],
            ))
        return items

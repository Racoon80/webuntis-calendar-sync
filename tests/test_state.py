import json

from webuntis_calendar_sync import __main__ as m


def test_v01_state_is_migrated(tmp_path, monkeypatch):
    old = {"objects": {
        "webuntis-stonneplang": {"webuntis-lesson-1.ics": {"hash": "a", "day": "2026-10-01"}},
        "webuntis-pruefungen": {},
        "webuntis-hausaufgaben": {"webuntis-homework-2.ics": {"hash": "b", "day": "2026-10-02"}},
    }}
    path = tmp_path / "state.json"
    path.write_text(json.dumps(old))
    monkeypatch.setattr(m, "STATE_FILE", path)
    state = m.load_state()
    nc = state["targets"]["nextcloud"]["kinds"]
    assert nc["lessons"] == old["objects"]["webuntis-stonneplang"]
    assert nc["homework"] == old["objects"]["webuntis-hausaufgaben"]
    assert nc["exams"] == {}
    assert "objects" not in state


def test_dtstamp_does_not_change_the_hash():
    a = "BEGIN:VCALENDAR\r\nDTSTAMP:20260101T000000Z\r\nSUMMARY:x\r\n"
    b = "BEGIN:VCALENDAR\r\nDTSTAMP:20270101T000000Z\r\nSUMMARY:x\r\n"
    assert m.digest(a) == m.digest(b)


def test_prodid_does_not_change_the_hash():
    a = "BEGIN:VCALENDAR\r\nPRODID:-//webuntis-nextcloud-sync//LB\r\nSUMMARY:x\r\n"
    b = "BEGIN:VCALENDAR\r\nPRODID:-//webuntis-calendar-sync//LB\r\nSUMMARY:x\r\n"
    assert m.digest(a) == m.digest(b)


class _Recorder:
    name = "rec"

    def __init__(self):
        self.puts = []

    def key(self, kind, item):
        return f"webuntis-lesson-{item.id}.ics"

    def render(self, kind, item):
        return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//webuntis-calendar-sync//LB\r\n"
                f"BEGIN:VEVENT\r\nDTSTAMP:20261001T000000Z\r\nUID:webuntis-lesson-{item.id}\r\n"
                "END:VEVENT\r\nEND:VCALENDAR\r\n")

    def put(self, kind, key, payload, remote):
        self.puts.append(key)

    def delete(self, kind, key, remote):
        pass


def test_entries_from_v01_are_not_rewritten():
    from conftest import TODAY, lesson
    rec = _Recorder()
    item = lesson(1)
    old_hash = m.digest_v1(rec.render("lessons", item).replace("calendar-sync", "nextcloud-sync"))
    seen = {"webuntis-lesson-1.ics": {"hash": old_hash, "day": TODAY.isoformat()}}
    counts = m.apply(rec, "lessons", [item], m.DAY_OF["lessons"], (TODAY, TODAY), seen)
    assert counts == {"written": 0, "deleted": 0, "unchanged": 1} and rec.puts == []
    assert seen["webuntis-lesson-1.ics"]["v"] == 2
    assert m.apply(rec, "lessons", [item], m.DAY_OF["lessons"], (TODAY, TODAY), seen)["unchanged"] == 1

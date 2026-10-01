from datetime import date

from webuntis_calendar_sync.untis import UntisClient, totp


def client_with(data):
    c = UntisClient("x.webuntis.com", "x", "u", "ABCDEFGH23456723")
    c.person_id = 1
    c._get = lambda path, **params: data
    return c


def test_exams_without_ids_get_distinct_stable_ids():
    exams = [{"id": 0, "examDate": 20261012, "startTime": 800, "endTime": 950,
              "subject": "MATH", "examType": "DC", "name": "", "text": ""},
             {"id": 0, "examDate": 20261019, "startTime": 800, "endTime": 950,
              "subject": "MATH", "examType": "DC", "name": "", "text": ""}]
    today = date.today()
    first = client_with({"exams": exams}).exams(today, today)
    second = client_with({"exams": exams}).exams(today, today)
    ids = [e.id for e in first]
    assert len(set(ids)) == 2 and all(ids)
    assert ids == [e.id for e in second]


def test_real_exam_ids_are_kept():
    exams = [{"id": 4711, "examDate": 20261012, "subject": "MATH"}]
    c = client_with({"exams": exams})
    today = date.today()
    assert c.exams(today, today)[0].id == 4711


def test_totp_matches_rfc6238():
    # RFC 6238 test vector (SHA-1, secret "12345678901234567890"): 94287082 at T=59 → 287082
    secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    assert totp(secret, at=59) == "287082"
    # same 30-second window, lower case accepted
    assert totp(secret.lower(), at=1_700_000_010) == totp(secret, at=1_700_000_020)

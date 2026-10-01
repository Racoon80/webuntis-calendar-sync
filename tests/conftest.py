import os
import socket
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("STATE_DIR", "/tmp/webuntis-calendar-sync-tests")

from webuntis_calendar_sync.untis import Exam, Homework, Lesson  # noqa: E402

TODAY = date.today()


def lesson(i, day_offset=0, code="", subject="MATH"):
    return Lesson(id=i, day=TODAY + timedelta(days=day_offset), start=(8, 0), end=(8, 50),
                  subject=subject, subject_long="Mathématiques", teachers=["DUPONT"],
                  rooms=["B12"], classes=["4C1"], code=code, info="")


def exam(i, day_offset=10, timed=True):
    return Exam(id=i, day=TODAY + timedelta(days=day_offset),
                start=(10, 0) if timed else None, end=(11, 40) if timed else None,
                subject="FRANC", name="Devoir en classe", exam_type="DC", text="Chapitres 1–3")


def homework(i, due_offset=1, completed=False, text="Exercices p. 42, n° 3; 4"):
    return Homework(id=i, subject="MATH", assigned=TODAY - timedelta(days=1),
                    due=TODAY + timedelta(days=due_offset), text=text, remark="",
                    completed=completed)


@pytest.fixture
def radicale(tmp_path):
    """A throw-away Radicale CalDAV server with user test/test."""
    port = socket.socket()
    port.bind(("127.0.0.1", 0))
    number = port.getsockname()[1]
    port.close()
    (tmp_path / "users").write_text("test:test\n")
    (tmp_path / "config").write_text(f"""
[server]
hosts = 127.0.0.1:{number}
[auth]
type = htpasswd
htpasswd_filename = {tmp_path / 'users'}
htpasswd_encryption = plain
[storage]
filesystem_folder = {tmp_path / 'collections'}
[logging]
level = warning
""")
    proc = subprocess.Popen([sys.executable, "-m", "radicale", "--config", str(tmp_path / "config")])
    url = f"http://127.0.0.1:{number}/"
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", number), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    yield url
    proc.terminate()
    proc.wait(5)

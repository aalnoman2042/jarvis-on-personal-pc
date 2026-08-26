"""The diary: parsing a date, storing it, and actually delivering it.

This is the suite for the bug that mattered most. Before phase 05, "remind me
about my exam on the 18th" was accepted, acknowledged, and dropped: the reminder
lived in a list in memory, on a server where nothing ever watched that list. It
looked like it worked. Nothing arrived.

So the last section is the one to keep honest. A reminder that comes due with
nobody listening must stay pending and arrive when someone opens the app — never
be marked delivered into an empty room.

Uses a throwaway database and the offline brain: no API quota, no touching
Rohan's real memory.
"""
import datetime as dt
import os
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SCRATCH = tempfile.mkdtemp(prefix="vondo-diary-test-")
PORT = 8734

os.environ["VONDO_DB"] = os.path.join(SCRATCH, "test.db")
os.environ["VONDO_PIN"] = "2042"
os.environ["VONDO_BRAIN"] = "free"
os.environ["VONDO_TZ"] = "Asia/Dhaka"

import httpx  # noqa: E402
import uvicorn  # noqa: E402
from websockets.sync.client import connect as ws_connect  # noqa: E402

from core import clock, reminders  # noqa: E402
from core.memory import agenda  # noqa: E402
from core.tools import llm_tools  # noqa: E402
from server import nudges  # noqa: E402
from server.app import app  # noqa: E402

import json  # noqa: E402

BASE = f"http://127.0.0.1:{PORT}"
passed = failed = 0


def check(label, got, want=None, contains=None):
    global passed, failed
    if contains is not None:
        ok = contains.lower() in str(got).lower()
        detail = f"{got!r} does not contain {contains!r}"
    else:
        ok = got == want
        detail = f"{got!r} != {want!r}"
    if ok:
        passed += 1
        print(f"  [ok  ] {label}")
    else:
        failed += 1
        print(f"  [FAIL] {label}: {detail}")


print("\n=== 1. reading a date out of a sentence ===")
# A Wednesday, deliberately: "next thursday" and "monday" both have to reach
# forward from somewhere in the middle of a week.
BASE_TS = clock.epoch(dt.datetime(2026, 8, 26, 14, 30))


def when(phrase):
    ts, all_day = clock.parse_when(phrase, BASE_TS)
    return (clock.local(ts).strftime("%Y-%m-%d %H:%M") if ts else None, all_day)


check("in 20 minutes", when("in 20 minutes"), ("2026-08-26 14:50", False))
check("in 2 hours", when("in 2 hours"), ("2026-08-26 16:30", False))
check("tomorrow at 5pm", when("tomorrow at 5pm"), ("2026-08-27 17:00", False))
check("18 sept — a day, with no time in it", when("18 sept"), ("2026-09-18 09:00", True))
check("  said the other way round", when("september 18"), ("2026-09-18 09:00", True))
check("  written as a date", when("18/9"), ("2026-09-18 09:00", True))
check("  with an hour on it", when("18 sept at 10am"), ("2026-09-18 10:00", False))
check("monday means the one coming", when("monday"), ("2026-08-31 09:00", True))
check("a month already past rolls to next year",
      when("18 january"), ("2027-01-18 09:00", True))
check("a phrase with no time in it is refused", when("something"), (None, False))
check("the year is never invented", clock.today_line(), contains=str(clock.local().year))
check("how long before to warn: 'the day before'", clock.parse_gap("the day before"), 86400.0)
check("  'an hour before'", clock.parse_gap("an hour before"), 3600.0)

print("\n=== 2. it survives being written down ===")
agenda.cancel("all")
exam = agenda.add(BASE_TS + 86400 * 22, "physics exam",
                  remind_at=BASE_TS + 86400 * 21, all_day=True, kind="event")
check("stored, with an id", isinstance(exam, int), True)
items = agenda.upcoming()
check("and comes back out", [i["message"] for i in items], contains="physics exam")
check("  keeping 'no time was given'", bool(items[0]["all_day"]), True)
check("  and the warning is earlier than the thing",
      items[0]["remind_at"] < items[0]["due"], True)
check("nothing is due yet", agenda.ready(), [])

print("\n=== 3. what Jarvis says back ===")
agenda.cancel("all")
said = reminders.schedule("18 sept", "physics exam", "the day before")
print(f"         -> {said!r}")
check("the date is read back, so a misheard one is caught now", said, contains="18th september")
check("  and so is the warning", said, contains="remind you")
check("a time already past is refused rather than stored",
      reminders.schedule("2020-01-01", "old thing"), contains="passed")
check("  and a phrase with no time in it asks",
      reminders.schedule("sometime", "vague thing"), contains="need a time")

print("")
print("=== 3c. a timetable said once ===")
#
# A repeating thing is ONE row that moves forward, not one row per occurrence.
# A term of weekly classes stored as fifty rows would all need rewriting the
# moment the timetable changed, and the fiftieth would arrive after the term.
agenda.cancel("all")
said = reminders.schedule("every monday and wednesday at 4pm", "EEE class")
print(f"         -> {said!r}")
check("said back as the pattern, not just the first one", said,
      contains="every monday and wednesday")
check("  stored as a repeat", agenda.upcoming(10)[0]["repeat_rule"], "weekly")

# The part that matters: delivering it must ADVANCE it, not finish it.
agenda.cancel("all")
rid = agenda.add(clock.now() - 5, "EEE class", remind_at=clock.now() - 5,
                 repeat_rule="weekly", repeat_days=[0, 2])
first = [i for i in agenda.upcoming(10) if i["id"] == rid][0]["due"]
agenda.mark_fired(rid)
after = [i for i in agenda.upcoming(10) if i["id"] == rid]
check("delivering it moves it on rather than ending it", len(after), 1)
check("  to a later date", after[0]["due"] > first, True)
check("  and it is pending again, not finished", after[0]["fired"], 0)
check("  landing on a day that was asked for",
      clock.local(after[0]["due"]).weekday() in (0, 2), True)

agenda.cancel("all")
gone = agenda.add(clock.now() - 5, "one off thing", remind_at=clock.now() - 5)
agenda.mark_fired(gone)
check("a one-off still finishes for good", agenda.ready(), [])
# By id, not cancel("all"): cancel deliberately only touches things still ahead,
# and both fixtures here are deliberately in the past. A fired row still counts
# as upcoming for a minute after its time, and the sections below count rows.
agenda.cancel_id(gone)
agenda.cancel_id(rid)

print("\n=== 4. the tools a brain reaches for ===")
agenda.cancel("all")
check("remind", llm_tools.DISPATCH["remind"]("in 20 minutes", "call dad"),
      contains="call dad")
check("check_agenda", llm_tools.DISPATCH["check_agenda"](), contains="call dad")
check("cancel_reminder", llm_tools.DISPATCH["cancel_reminder"]("call dad"),
      contains="cancelled 1")
check("  and it is gone", llm_tools.DISPATCH["check_agenda"](), contains="nothing in the diary")
check("every tool has a matching Groq schema",
      {f.__name__ for f in llm_tools.TOOL_FUNCTIONS}
      - {t["function"]["name"] for t in llm_tools.OPENAI_TOOLS}, set())

print("\n=== 5. and it is in the system prompt, so the brain knows ===")
agenda.cancel("all")
reminders.schedule("18 sept", "physics exam")
from core import memory  # noqa: E402  (after the database is pointed at scratch)
prompt = memory.system_prompt()
check("today's date is in it", prompt, contains="2026")
check("so is the agenda", prompt, contains="physics exam")

server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning"))
threading.Thread(target=server.run, daemon=True).start()
for _ in range(100):
    try:
        httpx.get(f"{BASE}/health", timeout=0.5)
        break
    except Exception:
        time.sleep(0.1)

try:
    token = httpx.post(f"{BASE}/login", json={"pin": "2042", "name": "phone"},
                       timeout=30).json()["token"]
    hdr = {"Authorization": f"Bearer {token}"}

    print("\n=== 6. over the API ===")
    agenda.cancel("all")
    r = httpx.post(f"{BASE}/agenda", headers=hdr,
                   json={"when": "18 sept", "message": "physics exam",
                         "warn": "the day before"})
    check("added over HTTP", r.status_code, 200)
    check("  and read back", r.json()["said"], contains="18th september")
    listed = httpx.get(f"{BASE}/agenda", headers=hdr).json()
    # Two rows, not one: an exam three weeks out earns a check-in partway
    # there, and the check-in is a real diary row so it rides the same
    # delivery, the same alarms and the same screens as everything else.
    check("it is in the diary, with its check-in", listed["count"], 2)
    check("  with a line the screen can show",
          " ".join(i["said"] for i in listed["items"]), contains="physics exam")
    check("  and the count reaches /status",
          httpx.get(f"{BASE}/status", headers=hdr).json()["upcoming"], 2)

    exam = next(i for i in listed["items"] if i["kind"] != "checkin")
    check("it can be dropped",
          httpx.delete(f"{BASE}/agenda/{exam['id']}", headers=hdr).json()["dropped"], True)
    check("  and its check-in goes with it",
          httpx.get(f"{BASE}/agenda", headers=hdr).json()["count"], 0)
    check("the diary needs a token",
          httpx.get(f"{BASE}/agenda").status_code, 401)

    print("\n=== 7. THE ACCEPTANCE TEST: one that is due actually arrives ===")
    agenda.cancel("all")
    agenda.add(clock.now() - 5, "take the bread out")   # due five seconds ago
    url = f"ws://127.0.0.1:{PORT}/ws/client?token={token}"
    with ws_connect(url) as socket:
        arrived, rid = "", 0
        deadline = time.time() + 10
        while time.time() < deadline:
            frame = json.loads(socket.recv(timeout=5))
            if frame.get("type") == "reminder":
                arrived, rid = frame.get("text", ""), frame.get("id", 0)
                break
        check("it was pushed to the open app", arrived, contains="take the bread out")

        # Sending bytes is not delivery. Until the client says it displayed the
        # thing, the row stays pending — see the regression below.
        check("  and stays pending until acknowledged",
              [i["message"] for i in agenda.ready()], contains="take the bread out")
        socket.send(json.dumps({"type": "seen", "id": rid}))
        time.sleep(1.0)
    check("acknowledged, it is not delivered twice",
          [i["message"] for i in agenda.ready()], [])

    print("\n=== 8. THE REGRESSION: nobody listening must not eat it ===")
    agenda.cancel("all")
    agenda.add(clock.now() - 5, "the exam warning nobody heard")
    check("no app is open", nudges.listeners.count(), 0)
    import asyncio
    sent = asyncio.run(nudges.deliver_due())
    check("nothing was delivered", sent, 0)
    check("  and it is STILL pending, not silently marked done",
          [i["message"] for i in agenda.ready()],
          contains="the exam warning nobody heard")
    with ws_connect(url) as socket:
        arrived, rid = "", 0
        deadline = time.time() + 12
        while time.time() < deadline:
            frame = json.loads(socket.recv(timeout=5))
            if frame.get("type") == "reminder" and "nobody heard" in frame.get("text", ""):
                arrived, rid = frame.get("text", ""), frame.get("id", 0)
                break
        check("it arrives the moment the app is opened", arrived,
              contains="the exam warning nobody heard")
        socket.send(json.dumps({"type": "seen", "id": rid}))
        time.sleep(1.0)

    print("")
    print("=== 8b. THE REGRESSION: a frozen app must not eat a reminder ===")
    #
    # An Android WebView that has been backgrounded keeps its TCP socket wide
    # open while its JavaScript is frozen. send_text succeeds, the bytes sit in
    # a buffer nobody will ever read, and marking the row fired on that basis
    # consumed the reminder for ever — which is exactly what happened to Rohan.
    # Sending must never be mistaken for delivering.
    agenda.cancel("all")
    agenda.add(clock.now() - 5, "must survive a sleeping app")
    with ws_connect(url) as socket:
        deadline = time.time() + 10
        while time.time() < deadline:
            frame = json.loads(socket.recv(timeout=5))
            if frame.get("type") == "reminder":
                break
        # Deliberately no acknowledgement — this is the frozen client.
        check("the frame went out", frame.get("type"), "reminder")
    time.sleep(0.5)
    check("  but with no acknowledgement it is STILL pending",
          [i["message"] for i in agenda.ready()],
          contains="must survive a sleeping app")

    print("\n=== 9. the wake-up call a sleeping free tier needs ===")
    r = httpx.post(f"{BASE}/tick")
    check("/tick answers without a token", r.status_code, 200)
    check("  and says what it did", set(r.json()), {"ok", "delivered", "listening"})

finally:
    server.should_exit = True
    time.sleep(0.3)

print(f"\n{'=' * 52}\n  {passed} passed, {failed} failed\n{'=' * 52}")
sys.exit(1 if failed else 0)

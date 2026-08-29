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
import importlib
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

print("")
print("=== 3d. people, and reaching them by name ===")
#
# A number used to be a sentence in `facts`, so "call dad" depended on a model
# finding the right sentence and reading the digits out correctly, every time,
# with no way to tell whether it had. A number is structured data.
from core.memory import contacts  # noqa: E402
from core import phone  # noqa: E402

check("saving someone", contacts.remember("dad", "01712 345678"), contains="saved")
check("  found by name", (contacts.find("dad") or {}).get("phone"), "01712 345678")
check("  and by a fragment", (contacts.find("da") or {}).get("name"), "dad")
contacts.remember("dad", "", "dad@example.com")
check("adding an email keeps the number",
      (contacts.find("dad") or {}).get("phone"), "01712 345678")

check("call by name", llm_tools.DISPATCH["call_contact"]("dad"), contains="calling dad")
check("  and it dials the right digits", phone.take(), "tel:01712345678")
check("someone unknown is asked about, not guessed",
      llm_tools.DISPATCH["call_contact"]("nobody"), contains="tell me it once")

# wa.me refuses a local number outright — it opens nothing at all, which looks
# exactly like the app being broken.
llm_tools.DISPATCH["message_contact"]("dad", "hello")
check("whatsapp gets an international number", phone.take(), contains="wa.me/88017123456")

# The prompt must know WHO exists so it can say it has no number for someone,
# without carrying everybody's number into every single turn.
people_block = contacts.block()
check("the prompt lists names", people_block, contains="dad")
check("  and never the numbers", "345678" in people_block, False)
contacts.forget("dad")
check("forgetting works", contacts.find("dad"), None)

print("")
print("=== 3e. things to do, as opposed to things that happen ===")
#
# The diary holds what happens at a time; this holds what has to get done. A
# task has no required date and does have a finished state, which is the whole
# distinction and the reason it is a separate table.
from core.memory import tasks as task_store  # noqa: E402

check("adding one", llm_tools.DISPATCH["add_task"]("write the methodology", "high"),
      contains="on the list")
llm_tools.DISPATCH["add_task"]("email supervisor", "normal", "friday")
llm_tools.DISPATCH["add_task"]("write the methodology", "high")   # said twice
check("saying it twice is still one task", task_store.counts()["open"], 2)

# A deadline outranks importance: the dated thing is the one that stops being
# possible, however important the undated one is.
order = [t["text"] for t in task_store.open_tasks()]
check("a deadline sorts above a priority", order[0], contains="email supervisor")

check("listing them", llm_tools.DISPATCH["my_tasks"](), contains="methodology")
check("ticking one off", llm_tools.DISPATCH["finish_task"]("methodology"),
      contains="done")
check("  and it leaves the list", task_store.counts()["open"], 1)
check("something not there is said so, not guessed",
      llm_tools.DISPATCH["finish_task"]("washing up"), contains="don't have anything")

# Finished, not deleted: what got done is worth knowing.
check("finished work is kept", len(task_store.done_since(0)), 1)

# And the model is told what is outstanding, every turn.
check("the prompt carries the open list", task_store.block(), contains="email supervisor")
for t in task_store.open_tasks(50):
    task_store.drop(t["id"])

print("")
print("=== 3f. following through on what you said you would do ===")
#
# The difference between a list and an assistant. A list holds what you put on
# it. Someone helping notices you said you would do something and asks, once,
# how it went — without having been asked to track it.
from core import brief as brief_mod  # noqa: E402

for t in task_store.open_tasks(50):
    task_store.drop(t["id"])

noticed = task_store.add("finish the NILM draft", source="noticed")
task_store.add("buy milk", source="asked")
# Backdate it: a commitment made an hour ago is not yet worth asking about.
store_conn = __import__("core.memory.store", fromlist=["store"]).connect()
store_conn.execute("UPDATE tasks SET created = ? WHERE id = ?",
                   (clock.now() - 3 * 86400, noticed))
store_conn.commit()

check("something said an hour ago is not chased yet",
      [t["id"] for t in task_store.noticed_to_chase()], contains=str(noticed))
first = brief_mod.compose()
check("the briefing asks about it", first, contains="did that happen")
check("  as a question, using their own words", first, contains="NILM draft")
check("something they ASKED for is never chased", first.count("buy milk"), 0)

# Once. Chasing the same commitment every morning is how a helpful assistant
# becomes a thing you close.
check("it does not ask a second time",
      "did that happen" in brief_mod.compose(), False)

for t in task_store.open_tasks(50):
    task_store.drop(t["id"])

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

    print("")
    print("")
    print("=== 8b2. searching everything, in one place ===")
    #
    # The index was wired for the MODEL months before it was wired for Rohan:
    # Jarvis could search his history and he could not.
    from core.memory import find as find_mod  # noqa: E402
    from core.memory import store as store_mod  # noqa: E402
    from core.memory import contacts as c_mod  # noqa: E402
    from core.memory import tasks as t_mod  # noqa: E402

    agenda.cancel("all")
    store_mod.add_turn("my supervisor wants CNN vs LSTM for NILM", "Noted.")
    memory.add_fact("Rohan researches NILM at CUET")
    reminders.schedule("18 sept", "NILM paper deadline")
    t_mod.add("write the NILM methodology", t_mod.HIGH)
    c_mod.remember("Dr Rahman", "01711111111", note="NILM supervisor")

    r = httpx.get(f"{BASE}/search?q=NILM", headers=hdr, timeout=60)
    check("search needs a token", httpx.get(f"{BASE}/search?q=x").status_code, 401)
    check("it answers", r.status_code, 200)
    kinds = {h["kind"] for h in r.json()["results"]}
    check("  reaches the conversation", "message" in kinds, True)
    check("  the remembered facts", "fact" in kinds, True)
    check("  the diary", "diary" in kinds, True)
    check("  the to-do list", "task" in kinds, True)
    check("  and the people", "person" in kinds, True)

    # A concentrated match beats a passing mention, or a one-word search
    # returns everything tied and ordered by nothing.
    top = r.json()["results"][0]
    check("the best match is first", top["score"] >= r.json()["results"][-1]["score"], True)

    # A search that returns rubbish is worse than one that returns nothing:
    # you stop trusting the good results too.
    empty = httpx.get(f"{BASE}/search?q=helicopter", headers=hdr, timeout=60).json()
    check("nothing irrelevant comes back", empty["total"], 0)
    check("an empty query is not a search", 
          httpx.get(f"{BASE}/search?q=", headers=hdr, timeout=60).json()["total"], 0)

    c_mod.forget("Dr Rahman")
    for t in t_mod.open_tasks(50):
        t_mod.drop(t["id"])
    agenda.cancel("all")


    print("=== 8c. getting your data out, and back ===")
    #
    # Everything lived in one hosted database with no export and no second copy.
    # A backup you cannot restore is half a backup, so both halves are checked.
    from core.memory import backup as backup_mod  # noqa: E402
    from core.memory import contacts as contacts_mod  # noqa: E402

    agenda.cancel("all")
    contacts_mod.remember("backup-test-person", "01700000000")
    reminders.schedule("18 sept", "backup test exam")
    dump = httpx.get(f"{BASE}/export", headers=hdr, timeout=60)
    check("export needs a token", httpx.get(f"{BASE}/export").status_code, 401)
    check("it downloads", dump.status_code, 200)
    check("  as a file, not a page", dump.headers.get("content-disposition", ""),
          contains="attachment")
    saved = dump.json()
    check("  in plain readable JSON", saved.get("format"), 1)
    check("  with the conversation in it", len(saved["tables"]["messages"]) > 0, True)
    check("  and the diary", len(saved["tables"]["reminders"]) > 0, True)
    check("  and the people", len(saved["tables"]["contacts"]) > 0, True)

    # Credentials must never travel in a file people email to themselves.
    check("no device tokens in the backup", "devices" in saved["tables"], False)
    check("no push subscriptions either",
          "push" in json.dumps(saved).lower().replace("pushed", ""), False)

    # Restoring what is already here must change nothing at all.
    again = httpx.post(f"{BASE}/restore", headers=hdr, json={"payload": saved},
                       timeout=60).json()
    check("restoring an existing backup adds nothing", again["total"], 0)
    check("  and deletes nothing", contacts_mod.find("backup-test-person") is not None, True)
    contacts_mod.forget("backup-test-person")
    agenda.cancel("all")


    print("\n=== 9. the wake-up call a sleeping free tier needs ===")
    r = httpx.post(f"{BASE}/tick")
    check("/tick answers without a token", r.status_code, 200)
    check("  and says what it did", set(r.json()),
          {"ok", "delivered", "embedded", "listening"})

    print("\n=== 10. the week, counted rather than guessed ===")
    from core import weekly  # noqa: E402
    from core.memory import store as store_mod  # noqa: E402

    conn = store_mod.connect()
    conn.execute("DELETE FROM tasks")
    conn.execute("DELETE FROM messages")
    conn.commit()

    now = clock.now()
    week_ago = now - 6 * 86400

    # Two finished, six added, four still open. The figures are the whole point
    # of the report, so they are pinned rather than sampled.
    for text in ("write the methodology section", "email the supervisor"):
        task_store.finish(task_store.add(text))
    for text in ("book the train", "read the NILM paper",
                 "renew the passport", "fix the bike"):
        task_store.add(text)

    for i, said in enumerate([
            "how is the NILM disaggregation going",
            "show me the NILM paper again",
            "what did the supervisor say about NILM",
            "remind me about the train",
    ]):
        conn.execute(
            "INSERT INTO messages(ts, brain, device, user, assistant) "
            "VALUES (?,?,?,?,?)",
            (week_ago + i * 3600, "free", "test", said,
             "Certainly. The disaggregation reminder is set."))
    conn.commit()

    figures = weekly.gather()
    check("finished tasks are counted", len(figures["finished"]), 2)
    check("open tasks are counted", figures["still_open"], 4)
    check("added tasks are counted", figures["added"], 6)
    check("conversations are counted", figures["conversations"], 4)

    # The topic count must read Rohan's words, never Jarvis's. "disaggregation"
    # appears in all four REPLIES and only one question — if it ranks at all,
    # the report is describing the assistant's vocabulary rather than his week.
    topics = dict(figures["topics"])
    check("what he talked about is counted from his own words",
          topics.get("nilm"), 3)
    check("  and not from the assistant's replies",
          "disaggregation" in topics, False)
    check("  and stopwords are not a topic", "about" in topics, False)

    text = weekly.compose()
    check("the report names what was finished", text,
          contains="write the methodology section")
    check("  and how much is left", text, contains="4 still to do")
    check("  and what it was mostly about", text, contains="nilm")

    # Six added against two finished: the observation is arithmetic, so it has
    # to say the list grew. A report that congratulates you on a bad week is
    # worse than no report at all.
    check("the closing line follows the figures", text,
          contains="growing faster than it is shrinking")

    check("a week already reported is not new",
          weekly.is_new_week(now - 3600), False)
    check("  last week is", weekly.is_new_week(now - 9 * 86400), True)
    check("  and never having seen one is", weekly.is_new_week(None), True)

    r = httpx.get(f"{BASE}/weekly", headers=hdr, timeout=30)
    check("/weekly answers", r.status_code, 200)
    check("  offering it on the first open of the week", r.json()["fresh"], True)
    httpx.post(f"{BASE}/weekly/seen", headers=hdr, timeout=30)
    check("  and going quiet once it has been read",
          httpx.get(f"{BASE}/weekly", headers=hdr, timeout=30).json()["fresh"], False)

    # Nothing to report must read as nothing, not as a page of zeroes.
    conn.execute("DELETE FROM tasks")
    conn.execute("DELETE FROM messages")
    conn.commit()
    check("an empty week says nothing at all", weekly.compose(), "")

    print("\n=== 11. finding things whose words do not match ===")
    from core.memory import vectors, recall as recall_mod  # noqa: E402

    # Offline throughout: a fixed toy embedding stands in for Google, so this
    # costs no quota and cannot go red because a free tier ran out overnight.
    # The numbers are chosen so the similarities are known in advance.
    AXES = {
        "nilm":     [1.0, 0.0, 0.0, 0.0],
        "supervisor": [0.0, 1.0, 0.0, 0.0],
        "keyboard": [0.0, 0.0, 1.0, 0.0],
        "nothing":  [0.0, 0.0, 0.0, 1.0],
    }

    def fake_embed(texts, query=False):
        out = []
        for text in texts:
            low = (text or "").lower()
            vec = [0.0, 0.0, 0.0, 0.0]
            for i, word in enumerate(("nilm", "supervisor", "keyboard")):
                if word in low:
                    vec[i] = 1.0
            # A paraphrase leans mostly the right way, which is what a real
            # embedding does and what the floor has to cope with.
            if "disaggregation" in low:
                vec[0] += 0.9
            if "report to" in low:
                vec[1] += 0.9
            if not any(vec):
                vec = list(AXES["nothing"])
            norm = sum(v * v for v in vec) ** 0.5
            out.append([v / norm for v in vec])
        return out

    real_embed, real_available = vectors.embed, vectors.available
    vectors.embed = fake_embed
    vectors.available = lambda: vectors._numpy() is not None

    conn = store_mod.connect()
    conn.execute("DELETE FROM messages")
    conn.execute("DELETE FROM vectors")
    conn.commit()
    vectors._cache.clear()
    vectors._loaded = False

    memory.add_turn("I am working on NILM for the thesis and it keeps overfitting",
                    "Try dropout on the dense layers.", brain="test")
    memory.add_turn("my supervisor prefers email to phone calls",
                    "Noted, email rather than phone.", brain="test")
    memory.add_turn("bought a mechanical keyboard with brown switches",
                    "Good choice.", brain="test")

    check("nothing is embedded on the write path", len(vectors._cache), 0)
    check("  and the archive knows what it still owes", vectors.pending() >= 3, True)
    check("the sweep fills it in", vectors.backfill(10) >= 3, True)
    check("  and then has nothing left to do", vectors.pending(), 0)

    # The whole point: a question sharing no content word with the answer.
    hits = vectors.search("what did I say about power disaggregation")
    check("a paraphrase finds the exchange it means", len(hits) >= 1, True)
    if hits:
        row = conn.execute("SELECT user FROM messages WHERE id = ?",
                           (hits[0]["id"],)).fetchone()
        check("  and it is the right one", row["user"], contains="NILM")

    check("something unrelated finds nothing at all",
          vectors.search("recipe for lasagne"), [])

    # recall must put the meaning hit where it will actually be read.
    found = recall_mod.find("who do I report to")
    check("recall reaches it through meaning", len(found) >= 1, True)
    if found:
        check("  and does not bury it", found[0]["user"], contains="supervisor")

    # Two searches, no shared scale, so neither may crowd the other out.
    woven = recall_mod._interleave(
        [{"ts": 1, "user": "word one"}, {"ts": 2, "user": "word two"}],
        [{"ts": 3, "user": "meaning one"}])
    check("the two searches take turns",
          [h["user"] for h in woven], ["word one", "meaning one", "word two"])
    check("  and the same row is never listed twice",
          len(recall_mod._interleave([{"ts": 9, "user": "same"}],
                                     [{"ts": 9, "user": "same"}])), 1)

    # Fragments are not worth an API call, and commands are not memories.
    check("a real question is worth indexing",
          vectors.worth_embedding("when is my exam",
                                  "Your exam is on the 18th of September."), True)
    check("  a bare fragment is not", vectors.worth_embedding("what is", "Sorry?"), False)
    check("  and a command never is",
          vectors.worth_embedding("open youtube", "Opening YouTube for you now."), False)
    check("a skipped row is not reconsidered every pass",
          vectors.pending(), 0)

    # int8 must not change which rows come back.
    sample = fake_embed(["nilm"])[0]
    check("the stored form survives the round trip",
          [round(float(x), 2) for x in vectors._unpack(vectors._pack(sample))],
          [round(v, 2) for v in sample])

    # Facts are embedded too, and until this was fixed they were stored, paid
    # for, and then dropped on the way out because retrieval only looked at
    # messages. What makes it matter is that facts_block() is capped by rendered
    # length: once enough is remembered the older half stops being sent at all.
    facts_mod = importlib.import_module("core.memory.facts")
    facts_mod.add("Rohan's supervisor is Dr Haque, who prefers email")
    vectors.backfill(10)
    back = recall_mod.remembered_facts("who do I report to", already="")
    check("a remembered fact is reachable by meaning", len(back), 1)
    check("  and it is the right one", back[0], contains="Haque")
    check("  and it is not repeated if already in the prompt",
          recall_mod.remembered_facts(
              "who do I report to",
              already="you know that Rohan's supervisor is Dr Haque, "
                      "who prefers email"),
          [])
    check("  and a command recalls nothing",
          recall_mod.remembered_facts("open chrome", already=""), [])
    facts_mod.forget("Haque")

    # And with no embedding at all, recall must behave exactly as it used to.
    vectors.available = lambda: False
    vectors.embed = lambda texts, query=False: [None] * len(texts)
    check("no embedding service means no meaning hits",
          vectors.search("what did I say about power disaggregation"), [])
    check("  and keyword recall still works",
          len(recall_mod.find("what did I say about NILM")) >= 1, True)
    check("  and the sweep asks for nothing", vectors.backfill(5), 0)

    # Nothing runs while nothing is happening. Once the archive is indexed,
    # looking again every thirty seconds is two full scans over the network for
    # ever, so a pass that finds nothing backs off.
    import asyncio as _asyncio  # noqa: E402
    nudges._next_catch_up = 0.0
    vectors.available = lambda: False
    _asyncio.run(nudges.catch_up())
    check("an idle sweep backs off instead of rescanning",
          nudges._next_catch_up > clock.now() + 60, True)
    check("  but an explicit pass is still honoured",
          _asyncio.run(nudges.catch_up(force=True)), 0)
    nudges._next_catch_up = 0.0

    vectors.embed, vectors.available = real_embed, real_available
    conn.execute("DELETE FROM messages")
    conn.execute("DELETE FROM vectors")
    conn.commit()
    vectors._cache.clear()

    print("\n=== 12. papers, notes and finding what is inside them ===")
    from core import documents  # noqa: E402

    conn = store_mod.connect()
    conn.execute("DELETE FROM documents")
    conn.execute("DELETE FROM doc_chunks")
    conn.execute("DELETE FROM vectors")
    conn.commit()
    vectors._cache.clear()

    PAPER = (
        "Low-Sampling-Rate Non-Intrusive Load Monitoring\n\n"
        "Abstract\n\n"
        "Non-intrusive load monitoring splits a household total into "
        "per-appliance consumption without a sensor on every device. We "
        "evaluate convolutional and recurrent designs at one-minute "
        "resolution, the rate deployed meters actually report.\n\n"
        "1. Introduction\n\n"
        "17\n\n"
        "Energy disaggregation has been studied since Hart. Recent deep "
        "learning work improves on hand-crafted features. Almost all "
        "published results assume one-second sampling, unavailable on the "
        "metering hardware installed in the field.\n\n"
        "3. Results\n\n"
        "The hybrid reaches 91 percent on refrigeration loads and 78 percent "
        "on washing machines. The convolutional baseline overfits once the "
        "window exceeds four hours.\n"
    )

    check("a PDF is recognised by name", documents.kind_of("paper.PDF"), "pdf")
    check("  and so is a note", documents.kind_of("thoughts.md"), "md")
    check("  and a photo is not something to read",
          documents.kind_of("cat.png"), "")

    tidy = documents.clean(PAPER)
    check("a page number is furniture, not text", "\n17\n" in tidy, False)
    check("  but the paragraphs survive it", "\n\n" in tidy, True)

    pieces = documents.chunks(tidy)
    check("a paper becomes several passages", len(pieces) >= 3, True)
    check("  none of them a whole document",
          max(len(p) for p in pieces) <= documents.TARGET * 2, True)
    check("  and none of them a fragment",
          min(len(p) for p in pieces) >= 20, True)
    # A fact sitting across a boundary has to be whole SOMEWHERE, or it is
    # findable in neither of the two chunks that share it.
    check("consecutive passages overlap",
          any(pieces[i][:60].split()[0] in pieces[i - 1]
              for i in range(1, len(pieces))), True)

    filed = documents.add(PAPER.encode(), "nilm.md", note="from my supervisor")
    check("filing a note works", filed["ok"], True)
    check("  and says how much it got", filed["chunks"] >= 3, True)

    same = documents.add(PAPER.encode(), "nilm-copy.md")
    check("the same file twice is one document", same["chunks"], 0)
    check("  and it says which one it already had", same["why"], contains="nilm.md")

    # The failure that must never be silent: a scan is pictures of a page.
    scan = documents.add(b"%PDF-1.4 no text layer here", "scan.pdf")
    check("an unreadable PDF is refused, not filed empty", scan["ok"], False)
    check("  and explains itself", scan["why"], contains="scan")
    check("  leaving nothing behind", len(documents.all_documents()), 1)

    # Now index it, with the same offline stand-in used above.
    vectors.embed = fake_embed
    vectors.available = lambda: vectors._numpy() is not None
    check("passages are waiting to be indexed", vectors.pending() >= 3, True)
    vectors.backfill(50)
    check("  and the sweep takes them", vectors.pending(), 0)

    # Filtered by kind rather than taking the top hit: the archive still holds
    # messages and facts from earlier sections, and which of them outranks a
    # passage for a given word is not what this section is testing.
    hits = [h for h in vectors.search("nilm", limit=10) if h["kind"] == "chunk"]
    check("a passage is reachable by meaning", len(hits) >= 1, True)

    got = documents.passage(hits[0]["id"])
    check("a hit can be read back", bool(got and got["text"]), True)
    check("  and names the document it came from", got["name"], "nilm.md")

    # Universal search must cover documents too — a paper you filed should turn
    # up beside the conversation where you talked about it.
    kinds = {h["kind"] for h in find_mod.search("disaggregation")}
    check("universal search reaches inside documents", "passage" in kinds, True)

    doc_id = documents.all_documents()[0]["id"]
    chunk_ids = [r["id"] for r in conn.execute(
        "SELECT id FROM doc_chunks WHERE doc_id = ?", (doc_id,)).fetchall()]
    check("forgetting a document works", documents.forget(doc_id), True)
    check("  and takes its passages with it",
          conn.execute("SELECT COUNT(*) n FROM doc_chunks").fetchone()["n"], 0)
    # Vectors outliving their text would return a hit that cannot be shown —
    # and SQLite reuses ids, so the next document would inherit them.
    check("  and their vectors, so no hit outlives its text",
          any(("chunk", int(c)) in vectors._cache for c in chunk_ids), False)

    # Asking for one kind must narrow the search BEFORE ranking. Filtering
    # afterwards returns nothing on a real archive, where messages outnumber
    # passages: the good passage is ranked eleventh and never looked at.
    everything = vectors.search("nilm", limit=20)
    only = vectors.search("nilm", limit=20, kinds=("chunk",))
    check("a search can ask for one kind",
          all(h["kind"] == "chunk" for h in only), True)
    check("  and narrows before ranking, not after",
          len(only) >= len([h for h in everything if h["kind"] == "chunk"]), True)

    # An embedding budget metered on CONTENT refuses a large batch and accepts a
    # small one in the same minute. Treating that as "nothing left" stalls the
    # whole archive until somebody notices; halving and retrying turns a tight
    # budget into slower progress, which needs no attention at all.
    conn.execute("DELETE FROM vectors")
    conn.commit()
    vectors._cache.clear()
    vectors._batch_chars = vectors.MAX_BATCH_CHARS

    # Enough text for several passages: halving cannot make ONE passage
    # smaller, so a single-chunk document could never exercise this.
    LIMIT = 1500
    tried = []

    def stingy_embed(texts, query=False):
        total = sum(len(t) for t in texts)
        tried.append(total)
        if total > LIMIT and not query:
            vectors._blocked_is_quota = True
            vectors._blocked = "quota"
            return [None] * len(texts)
        vectors._blocked_is_quota = False
        vectors._blocked = ""
        return fake_embed(texts, query)

    vectors.embed = stingy_embed
    gap = chr(10) * 2
    documents.add(
        gap.join(f"Passage {i} about NILM disaggregation research and the "
                 f"low sampling rate problem in deployed metering hardware, "
                 f"written out at length so that it becomes its own chunk."
                 for i in range(8)).encode(), "big.md")
    before = vectors.pending()
    done = vectors.backfill(50)
    check("a refused batch is halved rather than abandoned", len(tried) > 1, True)
    check("  and the retry is smaller than the attempt", tried[-1] < tried[0], True)
    check("  and progress is actually made", done > 0, True)
    check("  leaving less to do than before", vectors.pending() < before, True)

    # And when it is genuinely out, it stops rather than halving for ever.
    vectors._cache.clear()
    conn.execute("DELETE FROM vectors")
    conn.commit()
    tried.clear()

    def refuse_everything(texts, query=False):
        tried.append(sum(len(t) for t in texts))
        vectors._blocked_is_quota = True
        vectors._blocked = "quota"
        return [None] * len(texts)

    vectors.embed = refuse_everything
    check("a budget that is really gone stops trying", vectors.backfill(50), 0)
    check("  after a bounded number of attempts", len(tried) <= 6, True)
    check("  and says why, in words", vectors.blocked(), contains="quota")
    vectors._batch_chars = vectors.MAX_BATCH_CHARS

    vectors.embed, vectors.available = real_embed, real_available
    conn.execute("DELETE FROM documents")
    conn.execute("DELETE FROM doc_chunks")
    conn.commit()


    print("\n=== 13. learning from being corrected ===")
    from core.memory import corrections  # noqa: E402

    conn = store_mod.connect()
    conn.execute("DELETE FROM corrections")
    conn.execute("DELETE FROM messages")
    conn.commit()

    # A wrong correction is worse than a wrong recall: a bad recall is noise in
    # the prompt, a bad correction becomes an instruction the model follows over
    # its own judgement. So the refusals are the half that matters, and they are
    # pinned first.
    for said in ("no, I meant tomorrow", "not that one", "that's not what I said",
                 "I meant the NILM paper", "wrong, the other one"):
        check(f"  a correction: {said[:26]!r}",
              corrections.opens_like_a_correction(said), True)
    for said in ("no thanks", "remind me no later than five", "open notepad",
                 "what is the weather", "note that down", "nothing else"):
        check(f"  NOT a correction: {said[:26]!r}",
              corrections.opens_like_a_correction(said), False)

    # Teaching is unambiguous and is trusted more than inference.
    told = corrections.teach(
        "move it", "change the time on the existing reminder rather than making a new one")
    check("teaching says what it understood", told, contains="move it")
    corrections.teach("the paper", "mean the NILM one")

    # Only the RELEVANT lessons reach the prompt. All of them would crowd out
    # the thing actually being asked about.
    moved = [r["meant"] for r in corrections.relevant("move it to 4pm")]
    check("a lesson surfaces for the request it is about", len(moved), 1)
    check("  and it is the right one", moved[0], contains="existing reminder")
    check("an unrelated request gets none",
          corrections.relevant("what is the weather like"), [])

    block = corrections.block("move it to 4pm")
    check("the prompt block names the phrase", block, contains="move it")
    check("  and tells the model to follow it", block, contains="over your own instinct")
    check("an unrelated request adds nothing to the prompt",
          corrections.block("what is the weather like"), "")

    # The same lesson twice is one lesson that has happened twice.
    before = corrections.count()
    corrections.teach("move it", "change the time on the existing reminder rather than making a new one")
    check("the same lesson twice is not two rows", corrections.count(), before)
    again = [r for r in corrections.all_corrections() if "existing reminder" in r["meant"]]
    check("  it is counted instead", again[0]["hits"] >= 2, True)

    # Told beats guessed at equal overlap: one is what he said, the other is
    # what Jarvis inferred.
    corrections.noticed("the paper", "", "the paper means whichever I opened last")
    ranked = corrections.relevant("find the paper", limit=2)
    check("what he told it outranks what it guessed",
          ranked[0]["source"], "taught")

    # And a lesson learned wrongly has to be removable, or it is a black box.
    victim = corrections.all_corrections()[0]["id"]
    check("a correction can be unlearned", corrections.forget(victim), True)
    check("  and it is gone",
          victim in [r["id"] for r in corrections.all_corrections()], False)

    conn.execute("DELETE FROM corrections")
    conn.commit()
    check("nothing learned means nothing in the prompt",
          corrections.block("move it to 4pm"), "")


    print("\n=== 14. a deadline that can move, and an email you can read ===")
    from core import mail as mail_mod  # noqa: E402

    conn = store_mod.connect()
    conn.execute("DELETE FROM tasks")
    conn.commit()

    # The workaround used to LIE. tasks.add dedupes on lowered text and updated
    # only priority, so "the methodology is due Sunday now" answered "On the
    # list, due Sunday" and changed nothing at all. A confirmation of something
    # that did not happen is worse than a refusal.
    tid = task_store.add("write the methodology")
    sunday = clock.now() + 3 * 86400
    task_store.add("write the methodology", due=sunday)
    check("re-adding with a deadline actually sets it",
          task_store.open_tasks()[0]["due"], sunday)
    check("  and does not make a second row", len(task_store.open_tasks()), 1)

    friday = clock.now() + 5 * 86400
    check("a deadline can be moved", task_store.reschedule(tid, friday), True)
    check("  and it moved", task_store.open_tasks()[0]["due"], friday)
    check("  the slips are counted", task_store.open_tasks()[0]["moved"], 1)
    check("a deadline can be dropped entirely",
          task_store.reschedule(tid, 0) and task_store.open_tasks()[0]["due"], 0)
    check("moving something that is not there fails honestly",
          task_store.reschedule(99999, friday), False)

    # Said out loud from the third slip: once is life, four times means the task
    # is wrong rather than the date.
    for _ in range(2):
        task_store.reschedule(tid, friday)
    check("a task that keeps slipping says so",
          task_store.describe(task_store.open_tasks()[0]), contains="moved")

    said = llm_tools.DISPATCH["move_task"]("methodology", "next monday")
    check("the tool reads the new date back", said, contains="monday")
    check("  so a misheard one is caught now, not when it fails to arrive",
          said, contains="methodology")
    check("an unpinnable phrase is refused rather than guessed",
          llm_tools.DISPATCH["move_task"]("methodology", "sometime"),
          contains="isn't one")
    check("and nothing matching says so",
          llm_tools.DISPATCH["move_task"]("nonexistent thing", "friday"),
          contains="don't have anything")

    # --- reading one email ------------------------------------------------
    # Read-only is enforced by CODE, not intention. Checked by reading the
    # source, because a live IMAP server is not available here and the property
    # that matters is structural: the module cannot mark mail read even if
    # something asked it to.
    source = open(os.path.join(ROOT, "core", "mail.py"), encoding="utf-8").read()
    check("every fetch uses BODY.PEEK", "BODY.PEEK" in source, True)
    check("  and never the form that marks mail read",
          "BODY[" in source.replace("BODY.PEEK[", ""), False)
    for forbidden in ("box.store(", "box.copy(", "box.expunge(", "box.append("):
        check(f"  no {forbidden.split('.')[1][:-1]} call exists",
              forbidden in source, False)
    check("the body is fetched by PART, never as one unbounded blob",
          "BODY.PEEK[TEXT]" in source, False)

    # The quoted tail is where the value is: the ask is in the new writing at
    # the top, and keeping the thread means it arrives buried.
    threaded = (
        "Dear Rohan,\n\nCould you send the methodology by Friday?\n\n"
        "Best,\nHaque\n\nOn 12 March 2026, Rohan wrote:\n"
        "> here is the draft\n-----Original Message-----\nold thread"
    )
    trimmed = mail_mod._without_the_quoted_tail(threaded)
    check("the ask survives trimming", trimmed, contains="methodology by Friday")
    check("  and the quoted thread does not", "old thread" in trimmed, False)
    check("  nor the quoted lines", ">" in trimmed, False)
    check("html mail becomes readable text",
          mail_mod._strip_html("<p>Hi <b>Rohan</b></p><div>send it</div>"),
          contains="send it")
    check("  with the tags gone",
          "<" in mail_mod._strip_html("<p>Hi</p>"), False)

    conn.execute("DELETE FROM tasks")
    conn.commit()


finally:
    server.should_exit = True
    time.sleep(0.3)

print(f"\n{'=' * 52}\n  {passed} passed, {failed} failed\n{'=' * 52}")
sys.exit(1 if failed else 0)

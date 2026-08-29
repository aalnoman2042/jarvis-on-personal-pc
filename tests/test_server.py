"""End-to-end test of the VONDO cloud core.

Runs a real uvicorn on a real port and talks to it with real HTTP and real
websockets. Uses a throwaway database and the offline brain, so it costs no API
quota and never touches Rohan's actual memory.
"""
import os
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Must be set before core.config / store / auth are imported.
TMPDB = os.path.join(tempfile.mkdtemp(prefix="vondo-test-"), "test.db")
os.environ["VONDO_DB"] = TMPDB
os.environ["VONDO_BRAIN"] = "free"

import httpx  # noqa: E402
import json  # noqa: E402
import uvicorn  # noqa: E402
from websockets.sync.client import connect as ws_connect  # noqa: E402

from server.app import app  # noqa: E402

PORT = 8731
BASE = f"http://127.0.0.1:{PORT}"
WS = f"ws://127.0.0.1:{PORT}"

passed = failed = 0


def check(label, got, want=None, contains=None):
    global passed, failed
    if contains is not None:
        ok = contains.lower() in str(got).lower()
        detail = f"{got!r} contains {contains!r}"
    else:
        ok = got == want
        detail = f"{got!r} == {want!r}"
    if ok:
        passed += 1
        print(f"  [ok  ] {label}")
    else:
        failed += 1
        print(f"  [FAIL] {label}: {detail}")



def _ws_accepted(url):
    """True if the socket opened and stayed open.

    Not the inverse of _ws_rejected: that one waits for a frame, and the agent
    socket says nothing until it is spoken to, so a perfectly healthy PC link
    times out and reads as refused. Sending is the honest test of an open
    socket here.
    """
    try:
        with ws_connect(url) as sock:
            sock.send(json.dumps({"type": "telemetry", "cpu": 1, "memory": 1}))
        return True
    except Exception:
        return False


def _ws_rejected(url):
    """True if the server refused the socket rather than serving it."""
    try:
        with ws_connect(url) as sock:
            sock.recv(timeout=2)
        return False
    except Exception:
        return True


server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning"))
threading.Thread(target=server.run, daemon=True).start()
for _ in range(100):
    try:
        httpx.get(f"{BASE}/health", timeout=0.5)
        break
    except Exception:
        time.sleep(0.1)

try:
    print("\n=== 1. health is open, everything else is shut ===")
    r = httpx.get(f"{BASE}/health")
    check("/health needs no token", r.status_code, 200)
    check("  reports PC offline", r.json()["pc_online"], False)
    check("/chat without a token is refused", httpx.post(f"{BASE}/chat", json={"message": "hi"}).status_code, 401)
    check("/status without a token is refused", httpx.get(f"{BASE}/status").status_code, 401)

    print("\n=== 2. the PIN ===")
    bad = httpx.post(f"{BASE}/login", json={"pin": "1111", "name": "attacker"})
    check("a wrong PIN is refused", bad.status_code, 403)
    check("  and says how many tries are left", bad.json()["detail"], contains="attempt")

    r = httpx.post(f"{BASE}/login", json={"pin": "2042", "name": "phone", "kind": "client"})
    check("the right PIN signs you in", r.status_code, 200)
    phone = r.json()["token"]
    check("  a token came back", len(phone) > 20, True)
    auth_phone = {"Authorization": f"Bearer {phone}"}

    print("\n=== 3. more devices, then the lockout ===")
    again = httpx.post(f"{BASE}/login", json={"pin": "2042", "name": "desktop", "kind": "client"})
    check("a second device can sign in too", again.status_code, 200)
    agent_token = httpx.post(f"{BASE}/login", json={"pin": "2042", "name": "pc-agent", "kind": "agent"}).json()["token"]
    check("and so can the PC agent", len(agent_token) > 20, True)
    check("all three are listed", len(httpx.get(f"{BASE}/devices", headers=auth_phone).json()["devices"]), 3)

    print("\n=== 4. THE ACCEPTANCE TEST: a conversation that remembers ===")
    r1 = httpx.post(f"{BASE}/chat", headers=auth_phone, json={"message": "remember my favourite colour is green"}, timeout=30)
    check("first turn answers", r1.status_code, 200)
    print(f"         -> {r1.json()['reply'][:70]!r}")
    r2 = httpx.post(f"{BASE}/chat", headers=auth_phone, json={"message": "what time is it"}, timeout=30)
    check("second turn answers", r2.status_code, 200)
    print(f"         -> {r2.json()['reply'][:70]!r}")

    from core import memory
    turns = memory.recent(5)   # oldest first, newest last
    check("the second call can see the first in history", len(turns) >= 2, True)
    said = [t["user"] for t in turns]
    check("  turn 1 is in the history turn 2 could read", any("favourite colour" in u for u in said), True)
    check("  and turn 2 is the newest", turns[-1]["user"], contains="what time is it")

    print("\n=== 5. a PC action with no PC connected ===")
    #
    # Two different outcomes, and the difference is the point.
    #
    # Opening something has a second answer: the phone in your hand can open
    # YouTube perfectly well, so a sleeping PC falls back to it rather than
    # refusing. This used to say "your PC is offline" to a device holding a
    # browser, which was true and useless.
    r = httpx.post(f"{BASE}/chat", headers=auth_phone,
                   json={"message": "open youtube"}, timeout=30)
    check("answers immediately instead of hanging", r.status_code, 200)
    check("  opening falls back to the phone", r.json()["reply"], contains="opening")
    check("  and the phone is told where to go", r.json().get("open", ""),
          contains="youtube")
    print(f"         -> {r.json()['reply'][:60]!r} open={r.json().get('open')!r}")

    # Reading this machine's CPU has no second answer. There is exactly one PC
    # and it is asleep, so saying so is the honest thing — falling back to
    # anything here would mean inventing numbers.
    r = httpx.post(f"{BASE}/chat", headers=auth_phone,
                   json={"message": "what is my system status"}, timeout=30)
    check("  but reading the PC still says it is offline",
          r.json()["reply"], contains="offline")
    print(f"         -> {r.json()['reply'][:80]!r}")

    print("\n=== 6. now connect a PC agent and try again ===")
    stop = threading.Event()
    seen = []

    def fake_pc():
        with ws_connect(f"{WS}/ws/agent?token={agent_token}") as sock:
            sock.send(json.dumps({"type": "telemetry", "cpu": 12, "memory": 41}))
            while not stop.is_set():
                try:
                    frame = json.loads(sock.recv(timeout=0.4))
                except TimeoutError:
                    continue
                except Exception:
                    break
                if frame.get("type") == "call":
                    seen.append(frame)
                    sock.send(json.dumps({
                        "type": "result", "id": frame["id"],
                        "result": f"Opening {frame['args']['args'][0]}.", "ok": True}))

    t = threading.Thread(target=fake_pc, daemon=True)
    t.start()
    time.sleep(0.6)

    check("the server sees the PC online", httpx.get(f"{BASE}/health").json()["pc_online"], True)
    r = httpx.post(f"{BASE}/chat", headers=auth_phone, json={"message": "open chrome"}, timeout=30)
    check("the PC action is forwarded", len(seen) >= 1, True)
    if seen:
        check("  the right tool crossed the wire", seen[0]["tool"], "open_app")
        check("  with the right argument", seen[0]["args"]["args"][0], contains="chrome")
    check("  and the PC's answer came back", r.json()["reply"], contains="opening")
    print(f"         -> {r.json()['reply'][:80]!r}")

    st = httpx.get(f"{BASE}/status", headers=auth_phone).json()
    check("telemetry reached the server", st["pc"][0]["telemetry"].get("cpu"), 12)

    print("\n=== 7. the HUD's websocket ===")
    with ws_connect(f"{WS}/ws/client?token={phone}") as sock:
        hello = json.loads(sock.recv(timeout=5))
        check("greets with status on connect", hello["type"], "status")
        check("  and reports the PC", hello["pc_online"], True)
        sock.send(json.dumps({"type": "say", "text": "what time is it"}))
        thinking = json.loads(sock.recv(timeout=10))
        check("reports that it is thinking", thinking["state"], "thinking")
        reply = json.loads(sock.recv(timeout=30))
        check("then delivers the reply", reply["type"], "reply")
        print(f"         -> {reply['reply'][:70]!r}")

    check("an unauthorised socket is closed", _ws_rejected(f"{WS}/ws/client?token=nonsense"), True)

    # A valid token is not a licence to be any device you like. Without a kind
    # check, the phone's own token opens the PC's socket, registers as Rohan's
    # desktop, and is handed open_app, power_control and everything else on the
    # agent allow-list — while the real PC is marked offline.
    check("a phone token cannot pose as the PC",
          _ws_rejected(f"{WS}/ws/agent?token={phone}"), True)
    check("  and the PC's own token still can",
          _ws_accepted(f"{WS}/ws/agent?token={agent_token}"), True)

    stop.set()

    print("\n=== 8. revoking a device ===")
    devs = httpx.get(f"{BASE}/devices", headers=auth_phone).json()["devices"]
    victim = [d for d in devs if d["kind"] == "agent"][0]["id"]
    httpx.post(f"{BASE}/devices/{victim}/revoke", headers=auth_phone)
    check("the revoked token stops working",
          httpx.post(f"{BASE}/chat", headers={"Authorization": f"Bearer {agent_token}"},
                     json={"message": "hi"}).status_code, 401)
    check("the other device is unaffected",
          httpx.get(f"{BASE}/devices", headers=auth_phone).status_code, 200)
    # The settings screen filters on this field, so it has to survive the round
    # trip. It is SQLite's integer, not a boolean — writing the TypeScript as
    # `revoked?: boolean` compiled cleanly and was wrong.
    after = httpx.get(f"{BASE}/me", headers=auth_phone).json()["devices"]
    gone = [d for d in after if d["id"] == victim]
    check("a revoked device is still listed, marked revoked", len(gone), 1)
    check("  and the mark is what the screen filters on", bool(gone[0]["revoked"]), True)
    check("  so the live list no longer holds it",
          victim in [d["id"] for d in after if not d["revoked"]], False)


    print("\n=== 9. cross-origin, which the Android app depends on ===")
    # The APK loads its page from inside itself, so every call to the core is
    # cross-origin. Without a preflight answer the app just says "Failed to
    # fetch" and there is nothing on screen to say why.
    pre = httpx.request("OPTIONS", f"{BASE}/login", headers={
        "Origin": "https://localhost",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    })
    check("the preflight is answered", pre.status_code in (200, 204), True)
    check("  and allows the app's origin",
          pre.headers.get("access-control-allow-origin"), "https://localhost")
    check("  and the Authorization header",
          (pre.headers.get("access-control-allow-headers") or "").lower(), contains="authorization")

    real = httpx.post(f"{BASE}/login", json={"pin": "2042", "name": "android"},
                      headers={"Origin": "https://localhost"})
    check("a real cross-origin login works", real.status_code, 200)
    check("  and carries the origin header back",
          real.headers.get("access-control-allow-origin"), "https://localhost")

    print("\n=== 10. the parts that were silently doing the wrong thing ===")

    # /look and /listen had no coverage at all, which is how a typed question
    # could be dropped for months without anyone noticing: the request still
    # succeeded and still returned a perfectly good description of something
    # nobody had asked about.
    import inspect  # noqa: E402
    from fastapi import params as fastapi_params  # noqa: E402
    from server.app import look as look_route  # noqa: E402

    spec = inspect.signature(look_route).parameters["question"]
    check("a typed question to /look is read from the body, not the query",
          isinstance(spec.default, fastapi_params.Form), True)

    # Sending it the way the HUD does must reach eyes.look unchanged.
    import core.eyes as eyes_mod  # noqa: E402
    asked = {}
    real_look = eyes_mod.look
    eyes_mod.look = lambda data, question="", name="": (
        asked.update({"q": question}) or "a picture of something")
    try:
        httpx.post(f"{BASE}/look", headers=auth_phone,
                   files={"clip": ("x.jpg", b"not-a-real-jpeg", "image/jpeg")},
                   data={"question": "what does this error say"}, timeout=30)
    finally:
        eyes_mod.look = real_look
    check("  and arrives at the vision model as asked",
          asked.get("q"), "what does this error say")

    # Every brain must build its prompt through memory, or it knows the persona
    # and nothing about Rohan. Read as TEXT rather than imported: the paid brain
    # needs the anthropic SDK, which is deliberately not installed, and the one
    # brain nobody can exercise is exactly the one a regression hides in.
    def source(path):
        return open(os.path.join(ROOT, path), encoding="utf-8").read()

    claude = source("core/brains/brain_claude.py")
    check("the paid brain builds its prompt from memory",
          "memory.system_prompt(text)" in claude, True)
    check("  and not from the bare persona", "system=SYSTEM_PROMPT" in claude, False)

    check("the local brain passes the utterance, so recall happens",
          "memory.system_prompt(text)" in source("core/brains/brain_ollama.py"), True)
    check("  and never asks for the prompt without it",
          "memory.system_prompt()" in source("core/brains/brain_ollama.py"), False)

    # The offline brain is the one still answering when everything else has
    # failed. It was also the one force-killing apps without asking.
    offline = source("core/brains/brain_free.py")
    check("the offline brain force-closes through the confirm gate",
          "llm_tools.close_app(" in offline, True)
    check("  and never straight past it", "actions.close_app(" in offline, False)



    print("\n=== 11. the lockout, last, because it shuts this address out ===")
    detail = ""
    for _ in range(6):
        detail = httpx.post(f"{BASE}/login", json={"pin": "0000", "name": "attacker"}).json()["detail"]
    check("five wrong tries locks the address out", detail, contains="too many")
    check("  and a correct PIN is refused while locked",
          httpx.post(f"{BASE}/login", json={"pin": "2042", "name": "x"}).json()["detail"],
          contains="too many")
    check("  but an already-issued token still works",
          httpx.get(f"{BASE}/devices", headers=auth_phone).status_code, 200)


finally:
    server.should_exit = True
    time.sleep(0.3)

print(f"\n{'=' * 52}\n  {passed} passed, {failed} failed\n{'=' * 52}")
sys.exit(1 if failed else 0)

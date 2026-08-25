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
os.environ["VONDO_PAIR_SECRET"] = "open-sesame"
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

    print("\n=== 2. first device pairing ===")
    bad = httpx.post(f"{BASE}/pair/bootstrap", json={"secret": "guess", "name": "attacker"})
    check("wrong secret is refused", bad.status_code, 403)
    r = httpx.post(f"{BASE}/pair/bootstrap", json={"secret": "open-sesame", "name": "phone", "kind": "client"})
    check("right secret pairs the first device", r.status_code, 200)
    phone = r.json()["token"]
    check("  a token came back", len(phone) > 20, True)

    again = httpx.post(f"{BASE}/pair/bootstrap", json={"secret": "open-sesame", "name": "second"})
    check("the bootstrap door shuts once a device exists", again.status_code, 403)
    check("  and says why", again.json()["detail"], contains="already paired")

    auth_phone = {"Authorization": f"Bearer {phone}"}

    print("\n=== 3. pairing a second device from the first ===")
    code = httpx.post(f"{BASE}/pair/start", headers=auth_phone).json()["code"]
    check("an authorised device gets a 6-digit code", len(code), 6)
    check("a wrong code is refused", httpx.post(f"{BASE}/pair/claim", json={"code": "000000", "name": "x"}).status_code, 403)
    r = httpx.post(f"{BASE}/pair/claim", json={"code": code, "name": "desktop-agent", "kind": "agent"})
    check("the real code pairs a device", r.status_code, 200)
    agent_token = r.json()["token"]
    check("codes are single use", httpx.post(f"{BASE}/pair/claim", json={"code": code, "name": "y"}).status_code, 403)
    check("both devices are listed", len(httpx.get(f"{BASE}/devices", headers=auth_phone).json()["devices"]), 2)

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
    r = httpx.post(f"{BASE}/chat", headers=auth_phone, json={"message": "open chrome"}, timeout=30)
    check("answers immediately instead of hanging", r.status_code, 200)
    check("  and says the PC is offline", r.json()["reply"], contains="offline")
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

finally:
    server.should_exit = True
    time.sleep(0.3)

print(f"\n{'=' * 52}\n  {passed} passed, {failed} failed\n{'=' * 52}")
sys.exit(1 if failed else 0)

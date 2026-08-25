"""End-to-end test of the PC agent against a real cloud core.

Runs a real uvicorn, pairs the real agent to it, lets the real agent connect,
then asks over HTTP for something only this PC can answer — and checks the
answer really came off this machine.

Deliberately harmless: the only PC action exercised is reading CPU and memory.
Nothing is opened, closed, or shut down, and no confirmation dialog appears.
Uses a throwaway database, a throwaway token file and the offline brain, so it
costs no API quota and never touches Rohan's real memory or credentials.
"""
import os
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SCRATCH = tempfile.mkdtemp(prefix="vondo-agent-test-")
PORT = 8732

# All of this must be set before core.config / agent.settings are imported.
os.environ["VONDO_DB"] = os.path.join(SCRATCH, "test.db")
os.environ["VONDO_AGENT_TOKEN_FILE"] = os.path.join(SCRATCH, "agent.token")
os.environ["VONDO_PAIR_SECRET"] = "open-sesame"
os.environ["VONDO_BRAIN"] = "free"
os.environ["VONDO_URL"] = f"http://127.0.0.1:{PORT}"
os.environ["VONDO_AGENT_NAME"] = "test-pc"

import asyncio  # noqa: E402
import httpx  # noqa: E402
import uvicorn  # noqa: E402

from agent import agent as pc_agent, guard, settings  # noqa: E402
from server.app import app  # noqa: E402

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


server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning"))
threading.Thread(target=server.run, daemon=True).start()
for _ in range(100):
    try:
        httpx.get(f"{BASE}/health", timeout=0.5)
        break
    except Exception:
        time.sleep(0.1)

try:
    print("\n=== 1. the guard, before anything is connected ===")
    check("allow-list matches the cloud's routed set", len(guard.ALLOWED), 18)
    try:
        guard.check("eval_python", ["import os"], {})
        check("refuses a tool that is not on the list", "allowed it", "refused")
    except guard.Refused as exc:
        check("refuses a tool that is not on the list", str(exc), contains="doesn't allow")
    try:
        guard.check("system_info", [], {})
        check("allows a listed, harmless tool", True, True)
    except guard.Refused:
        check("allows a listed, harmless tool", False, True)
    check("shutdown would ask on screen",
          guard._needs_local_confirmation("power_control", ["shutdown"], {}), contains="shut down")
    check("reading CPU would not", guard._needs_local_confirmation("system_info", [], {}), "")

    print("\n=== 2. pairing this PC the way Rohan will ===")
    phone = httpx.post(f"{BASE}/pair/bootstrap",
                       json={"secret": "open-sesame", "name": "phone"}).json()["token"]
    hdr = {"Authorization": f"Bearer {phone}"}
    code = httpx.post(f"{BASE}/pair/start", headers=hdr).json()["code"]
    check("the phone produced a code", len(code), 6)

    from agent.pair import claim
    token = claim(code)                      # exactly what pair_agent.bat runs
    settings.save_token(token)
    check("the agent redeemed it for a token", len(token) > 20, True)
    check("  and saved it outside the repo",
          os.path.exists(os.environ["VONDO_AGENT_TOKEN_FILE"]), True)
    check("  the device is listed as an agent",
          [d["kind"] for d in httpx.get(f"{BASE}/devices", headers=hdr).json()["devices"]],
          contains="agent")

    print("\n=== 3. the real agent connects ===")

    def run_agent():
        asyncio.run(pc_agent.run())

    threading.Thread(target=run_agent, daemon=True).start()

    for _ in range(60):
        if httpx.get(f"{BASE}/health").json()["pc_online"]:
            break
        time.sleep(0.1)
    check("the cloud sees this PC", httpx.get(f"{BASE}/health").json()["pc_online"], True)

    print("\n=== 4. telemetry the HUD will draw ===")
    telemetry = {}
    for _ in range(80):
        pc = httpx.get(f"{BASE}/status", headers=hdr).json()["pc"]
        if pc and pc[0]["telemetry"].get("cpu") is not None:
            telemetry = pc[0]["telemetry"]
            break
        time.sleep(0.1)
    check("CPU arrived", isinstance(telemetry.get("cpu"), (int, float)), True)
    check("memory arrived", isinstance(telemetry.get("memory"), (int, float)), True)
    print(f"         -> cpu {telemetry.get('cpu')}%  memory {telemetry.get('memory')}%"
          f"  battery {telemetry.get('battery')}")

    print("\n=== 5. THE ACCEPTANCE TEST: a request that only this PC can answer ===")
    r = httpx.post(f"{BASE}/chat", headers=hdr,
                   json={"message": "what is my system status"}, timeout=40)
    check("the request succeeded", r.status_code, 200)
    reply = r.json()["reply"]
    print(f"         -> {reply!r}")
    check("the answer came off this machine", reply, contains="cpu")
    check("  and it is not the offline message", "offline" in reply.lower(), False)

    print("\n=== 6. what happens when the PC goes away ===")
    pc_agent.request_stop()          # what closing the agent window does
    for _ in range(80):
        if not httpx.get(f"{BASE}/health").json()["pc_online"]:
            break
        time.sleep(0.1)
    check("the cloud notices immediately", httpx.get(f"{BASE}/health").json()["pc_online"], False)
    r = httpx.post(f"{BASE}/chat", headers=hdr,
                   json={"message": "what is my system status"}, timeout=40)
    check("and answers instead of hanging", r.json()["reply"], contains="offline")
    print(f"         -> {r.json()['reply'][:80]!r}")

finally:
    server.should_exit = True
    time.sleep(0.3)

print(f"\n{'=' * 52}\n  {passed} passed, {failed} failed\n{'=' * 52}")
sys.exit(1 if failed else 0)

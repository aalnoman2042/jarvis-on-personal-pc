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
os.environ["VONDO_PIN"] = "2042"
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


def _refused(fn) -> bool:
    """True if the guard turned this away."""
    from agent import guard as _g
    try:
        fn()
        return False
    except _g.Refused:
        return True


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
    # The identity, not the count. A number here says nothing about whether the
    # two lists agree — it only fails when either changes, which is exactly the
    # case where somebody is already looking. `ALLOWED is PC_FUNCTIONS` is the
    # property that matters: the agent must never carry a second copy that can
    # drift into "the server can ask for something this PC forgot about".
    from core.lazy import PC_FUNCTIONS  # noqa: E402
    check("allow-list IS the cloud's routed set, not a copy of it",
          guard.ALLOWED is PC_FUNCTIONS, True)
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

    print("\n=== 2. signing this PC in the way Rohan will ===")
    phone = httpx.post(f"{BASE}/login",
                       json={"pin": "2042", "name": "phone"}, timeout=30).json()["token"]
    hdr = {"Authorization": f"Bearer {phone}"}

    from agent.login import claim
    token = claim("2042")                    # exactly what link_pc.bat runs
    settings.save_token(token)
    check("the agent signed in with the PIN", len(token) > 20, True)
    check("  and saved the token outside the repo",
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

    print("\n=== 7. remote control: refused until the desk says yes ===")
    from agent import guard  # noqa: E402

    # A mouse and a keyboard are every action at once, so the allow-list cannot
    # protect this one — the dialog on the PC is the whole gate. These checks
    # are what stop it being quietly removed.
    guard._remote_allowed = None
    asked = []
    real_ask = guard._ask_on_screen
    guard._ask_on_screen = lambda question: (asked.append(question), False)[1]
    try:
        try:
            guard.check("screen_input", ["click"], {})
            refused = False
        except guard.Refused:
            refused = True
        check("a click is refused when the desk says no", refused, True)
        check("  and the question named remote control",
              asked and "CONTROL THIS PC" in asked[0], True)

        # A refusal has to stick. A gate that asks again every few seconds is a
        # gate that gets clicked through eventually.
        before = len(asked)
        try:
            guard.check("screen_input", ["click"], {})
        except guard.Refused:
            pass
        check("  and it is not asked twice", len(asked), before)

        # Watching is not driving, and take_screenshot has never asked.
        guard.check("screen_frame", [900, 45], {})
        check("seeing the screen needs no permission", len(asked), before)

        # Now allow it, and it stays allowed for the run.
        guard._remote_allowed = None
        asked.clear()
        guard._ask_on_screen = lambda question: (asked.append(question), True)[1]
        guard.check("screen_input", ["click"], {})
        guard.check("screen_input", ["type"], {})
        guard.check("screen_input", ["key"], {})
        check("once allowed, it asks once for the whole session", len(asked), 1)
    finally:
        guard._ask_on_screen = real_ask
        guard._remote_allowed = None

    check("the allow-list carries the screen functions",
          {"screen_frame", "screen_input", "screen_size"} <= guard.ALLOWED, True)
    check("  and still refuses anything not on it",
          _refused(lambda: guard.check("eval", [], {})), True)


    print("\n=== 8. the agent's dependencies are declared, not assumed ===")
    import re as _re  # noqa: E402

    # This section exists because of a real failure. pyautogui declares
    # pyscreeze, pyscreeze declares Pillow, so Pillow was treated as "already
    # there" and never listed. On the actual machine the chain had not produced
    # it: the venv held pyautogui and no PIL, and BOTH take_screenshot and the
    # remote screen view failed at the moment of use, from a phone in another
    # room. A dependency you rely on belongs in the file whether or not
    # something else usually drags it in.
    req = open(os.path.join(ROOT, "requirements", "agent.txt"),
               encoding="utf-8").read()
    listed = {ln.split(">=")[0].split("==")[0].strip().lower()
              for ln in req.splitlines()
              if ln.strip() and not ln.strip().startswith("#")}
    for needed in ("websockets", "psutil", "pyautogui", "pillow", "python-dotenv"):
        check(f"  agent.txt lists {needed}", needed in listed, True)

    # And the launcher must check everything it lists, or it passes and the
    # agent fails later — which is worse than not checking at all.
    launcher = open(os.path.join(ROOT, "start_agent.bat"),
                    encoding="utf-8", errors="replace").read()
    probe = _re.search(r'-c "([^"]+)"', launcher)
    checked = probe.group(1) if probe else ""
    check("the launcher verifies the imports before starting",
          bool(probe), True)
    for module in ("psutil", "websockets", "pyautogui", "PIL", "dotenv"):
        check(f"  it checks {module}", module in checked, True)

    # The screen functions must not merely exist — they must be reachable in
    # whatever interpreter is running, and say something useful when they are
    # not. Both were returning an error string that named the fault and not the
    # remedy, which is no help at all from another room.
    from core import actions as _actions  # noqa: E402
    frame = _actions.screen_frame(320, 20)
    if frame.startswith("error:"):
        check("a failed capture names the fix, not just the fault",
              frame, contains="pip install")
    else:
        import base64 as _b64
        check("a frame is real JPEG data", _b64.b64decode(frame)[:2], b"\xff\xd8")
        check("  and it is not enormous", len(frame) < 400_000, True)
    check("a silly frame request is clamped rather than obeyed",
          _actions.screen_frame(99999, 999).startswith("error:"), False)

finally:
    server.should_exit = True
    time.sleep(0.3)

print(f"\n{'=' * 52}\n  {passed} passed, {failed} failed\n{'=' * 52}")
sys.exit(1 if failed else 0)

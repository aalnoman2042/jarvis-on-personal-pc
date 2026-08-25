"""Rohan's PC, answering the cloud.

This is the only piece of VONDO that runs on his machine, and it is meant to
stay that way: no AI, no models, no speech, no window. It holds one outbound
websocket open, runs the handful of things only a desktop can do, and reports
CPU and memory so the HUD has something to draw.

It dials *out* on purpose. A cloud server cannot open a connection into a home
network — routers exist to stop that — so the connection is one this machine
chose to make, and there is no port open on this PC for anyone to find.

Run:  python -m agent.agent        (or start_agent.bat)
Pair: python -m agent.pair         (once, with a code from the phone)
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import random
import sys
import time

import psutil
import websockets
from websockets.asyncio.client import connect

from agent import guard
from agent.settings import CLOUD_WS, agent_name, load_token

TELEMETRY_SECONDS = 5.0
BACKOFF_START = 1.0
BACKOFF_MAX = 60.0


def _say(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


# ---------------------------------------------------------------------------
# Doing the work
# ---------------------------------------------------------------------------

def _run_tool(tool: str, args: list, kwargs: dict) -> str:
    """Run one call, in a worker thread. Returns what to send back.

    Never raises: the cloud is mid-conversation with Rohan and a traceback here
    would surface as silence. Everything comes back as a sentence.
    """
    try:
        guard.check(tool, args, kwargs)
    except guard.Refused as exc:
        _say(f"refused {tool}: {exc}")
        return str(exc)

    try:
        from core import actions          # imported here: heavy, and only now needed
        return str(getattr(actions, tool)(*args, **kwargs))
    except Exception as exc:  # noqa: BLE001
        _say(f"{tool} failed: {exc}")
        return f"That didn't work on your PC. ({exc})"


async def _handle_call(ws, frame: dict) -> None:
    """One call from the cloud, answered without blocking anything else.

    Each runs in its own task and its own thread, so a screenshot that takes a
    second, or a confirmation dialog waiting on a human, does not stop telemetry
    or hold up the next request.
    """
    call_id = str(frame.get("id", ""))
    tool = str(frame.get("tool", ""))
    payload = frame.get("args") or {}
    args = list(payload.get("args") or [])
    kwargs = dict(payload.get("kwargs") or {})

    _say(f"call {tool}({', '.join(map(str, args))})")
    result = await asyncio.to_thread(_run_tool, tool, args, kwargs)
    with contextlib.suppress(Exception):
        await ws.send(json.dumps(
            {"type": "result", "id": call_id, "result": result, "ok": True}))


# ---------------------------------------------------------------------------
# Telemetry — what the HUD draws
# ---------------------------------------------------------------------------

def _snapshot() -> dict:
    """Cheap enough to send every few seconds and not be noticed."""
    out: dict = {"type": "telemetry", "ts": round(time.time(), 1)}
    try:
        out["cpu"] = psutil.cpu_percent(interval=None)   # since the last call
        out["memory"] = psutil.virtual_memory().percent
    except Exception:  # noqa: BLE001
        pass
    try:
        battery = psutil.sensors_battery()
        if battery is not None:
            out["battery"] = int(battery.percent)
            out["charging"] = bool(battery.power_plugged)
    except Exception:  # noqa: BLE001
        pass
    return out


async def _telemetry_loop(ws) -> None:
    psutil.cpu_percent(interval=None)      # prime it; the first reading is junk
    while True:
        with contextlib.suppress(Exception):
            await ws.send(json.dumps(_snapshot()))
        await asyncio.sleep(TELEMETRY_SECONDS)


# ---------------------------------------------------------------------------
# The connection
# ---------------------------------------------------------------------------

# Stopping cleanly matters more than it looks. Killing the process leaves the
# socket half-open until TCP works it out, and until then the cloud still thinks
# this PC is listening — so "open chrome" from the phone waits for a timeout
# instead of saying the PC is asleep. Closing the websocket tells the server
# immediately.
_stop: asyncio.Event | None = None
_loop: asyncio.AbstractEventLoop | None = None


def request_stop() -> None:
    """Ask the agent to disconnect and exit. Safe to call from another thread."""
    if _loop is not None and _stop is not None and not _loop.is_closed():
        _loop.call_soon_threadsafe(_stop.set)


async def _receive(ws, calls: set[asyncio.Task]) -> None:
    async for raw in ws:
        try:
            frame = json.loads(raw)
        except ValueError:
            continue
        if frame.get("type") != "call":
            continue   # unknown frames are ignored, not fatal: a newer server
                       # may say things this agent has not learned yet
        task = asyncio.create_task(_handle_call(ws, frame))
        calls.add(task)
        task.add_done_callback(calls.discard)


async def _session(url: str) -> None:
    """One connection, held until it drops or we're asked to stop."""
    async with connect(url, ping_interval=20, ping_timeout=20) as ws:
        _say("connected to the cloud")
        calls: set[asyncio.Task] = set()
        telemetry = asyncio.create_task(_telemetry_loop(ws))
        receiver = asyncio.create_task(_receive(ws, calls))
        stopper = asyncio.create_task(_stop.wait())
        try:
            await asyncio.wait({receiver, stopper},
                               return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (telemetry, receiver, stopper, *calls):
                task.cancel()
            # Leaving the `async with` closes the socket, which is what makes
            # the cloud mark this PC offline at once rather than on a timeout.


async def run() -> None:
    global _stop, _loop
    _stop = asyncio.Event()
    _loop = asyncio.get_running_loop()

    token = load_token()
    if not token:
        _say("not paired yet — run:  python -m agent.pair")
        return

    url = f"{CLOUD_WS}/ws/agent?token={token}"
    backoff = BACKOFF_START
    _say(f"agent '{agent_name()}' starting | cloud: {CLOUD_WS}")

    while not _stop.is_set():
        try:
            await _session(url)
            if _stop.is_set():
                _say("disconnected cleanly")
                return
            backoff = BACKOFF_START          # a real session resets the wait
            _say("connection closed; reconnecting")
        except websockets.InvalidStatus as exc:
            # 4401 / 401 means the token is wrong or revoked. Retrying forever
            # would hammer the server for nothing, and the fix is human.
            if "401" in str(exc) or "403" in str(exc):
                _say("this PC is not authorised any more — pair it again:"
                     "  python -m agent.pair")
                return
            _say(f"server refused the connection: {exc}")
        except (OSError, websockets.WebSocketException) as exc:
            _say(f"cloud unreachable ({type(exc).__name__}); retrying")
        except Exception as exc:  # noqa: BLE001  (stay up whatever happens)
            _say(f"unexpected: {exc}; retrying")

        # Jittered backoff: without the jitter, a PC and a phone that both lost
        # the same wifi come back in lockstep and hit the server together.
        wait = min(backoff, BACKOFF_MAX) * (0.5 + random.random())
        # Waiting on the stop event rather than sleeping: otherwise closing the
        # window during a sixty-second backoff hangs for up to a minute.
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(_stop.wait(), timeout=wait)
        backoff = min(backoff * 2, BACKOFF_MAX)


def main() -> int:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        request_stop()
        _say("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())

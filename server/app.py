"""The cloud core — Jarvis with an address.

Everything the desktop app does, behind an API that a phone can reach. The
brains, the memory and the tools are unchanged; this file is only plumbing:
who is asking, which machine should do the work, and how the answer gets back.

Run it locally exactly as it will run in the cloud:

    set VONDO_PIN=2042
    python -m uvicorn server.app:app --reload --port 8000

Two things worth knowing before reading on.

**Brains block.** They make network calls and wait. Calling one directly inside
an async endpoint would freeze the whole event loop — including the websocket
carrying the PC agent — so every turn is run in a worker thread. A lock around
it keeps turns strictly one at a time, which is what the shared conversation
history assumes anyway.

**"Streaming" here means events, not tokens.** The websocket reports what Jarvis
is doing as it happens (thinking, calling a tool, done) and delivers the reply
as one message, because the brains return a finished string today. The frame
format already has a `token` type, so when a brain learns to stream, tokens flow
to the existing HUD without a protocol change. It is not faked in the meantime.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time

from fastapi import (Depends, FastAPI, Header, HTTPException, Request,
                     WebSocket, WebSocketDisconnect)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from core import config
from core.brains import factory
from core import memory
from core import reminders
from core.memory import agenda as agenda_store
from core.memory import store
from server import agents, auth, nudges

log = logging.getLogger("vondo")

# One brain for the whole server, and one turn at a time. Both deliberate: the
# conversation is a single shared thread, and brains keep internal state that is
# not safe to drive from two requests at once.
_brain = None
_brain_lock = asyncio.Lock()

# Requests per device per minute. Generous for a person, useless for a script
# that found the URL.
RATE_LIMIT = 60
_buckets: dict[str, list[float]] = {}


def get_brain():
    global _brain
    if _brain is None:
        _brain = factory.make()
        log.info("brain ready: %s", getattr(_brain, "name", "?"))
    return _brain


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    store.connect()                                   # open the database, migrate v1 files
    agents.install_hook(asyncio.get_running_loop())   # PC tools now route to the agent
    stop = asyncio.Event()
    # Watches the diary. Cheap — one indexed query every thirty seconds — and it
    # is the only reason a reminder set on the phone ever arrives anywhere.
    sweeper = asyncio.create_task(nudges.loop(stop))
    log.info("vondo core up | pin set: %s | devices: %d | upcoming: %d",
             bool(auth.PIN), auth.device_count(), agenda_store.count())
    try:
        yield
    finally:
        stop.set()
        sweeper.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sweeper


app = FastAPI(title="VONDO core", version="2.0.0-dev", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Cross-origin, for the Android app
#
# In a browser the HUD is served by this app, so everything is same-origin and
# none of this is needed. The Android build changed that: the page is loaded out
# of the APK, its origin is localhost, and every call here is cross-origin. A
# JSON POST then triggers a preflight, which without this returns 405 and the
# app shows "Failed to fetch" — a message that says nothing about what is wrong.
#
# Named origins rather than "*": these are the only ones that exist. Credentials
# are off because auth is a Bearer header, not a cookie, so there is nothing for
# a hostile page to replay even if one asked.
# ---------------------------------------------------------------------------

APP_ORIGINS = [
    "https://localhost",      # Capacitor Android with androidScheme https
    "http://localhost",       # Capacitor Android default scheme
    "capacitor://localhost",  # Capacitor iOS
    "ionic://localhost",
    "http://localhost:5173",  # vite dev server
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=APP_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=86400,
)


# ---------------------------------------------------------------------------
# Who is asking
# ---------------------------------------------------------------------------

def _bearer(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        return ""
    return authorization[7:].strip()


def _rate_ok(device_id: str) -> bool:
    now = time.time()
    hits = [t for t in _buckets.get(device_id, []) if now - t < 60.0]
    hits.append(now)
    _buckets[device_id] = hits
    return len(hits) <= RATE_LIMIT


async def caller(authorization: str | None = Header(default=None)) -> dict:
    """FastAPI dependency: the device behind this request, or 401."""
    try:
        device = auth.identify(_bearer(authorization))
    except auth.AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from None
    if not _rate_ok(device["id"]):
        raise HTTPException(status_code=429, detail="Slow down a moment.")
    return device


async def socket_caller(websocket: WebSocket) -> dict | None:
    """Same, for websockets, where headers are awkward and query strings are not.

    Closes the socket and returns None on failure — websockets have no 401.
    """
    token = websocket.query_params.get("token", "")
    try:
        return auth.identify(token)
    except auth.AuthError:
        await websocket.close(code=4401, reason="unauthorised")
        return None


# ---------------------------------------------------------------------------
# Signing in
# ---------------------------------------------------------------------------

class LoginIn(BaseModel):
    pin: str = Field(min_length=1, max_length=32)
    name: str = Field(default="device", max_length=60)
    kind: str = Field(default="client", max_length=20)


def _client_ip(request: Request) -> str:
    """The address the lockout counts against.

    Behind Render's proxy `request.client.host` is the proxy, not the visitor —
    every attempt in the world would share one bucket, so one bad guess anywhere
    would lock out everyone including Rohan. The left-most X-Forwarded-For entry
    is the original client. It is spoofable, which matters less than it sounds:
    an attacker who rotates it gets more guesses, but a normal visitor keeps a
    working lockout, and the alternative locks the owner out of his own house.
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:45]
    return request.client.host if request.client else "unknown"


@app.post("/login")
async def login(body: LoginIn, request: Request):
    """Type the PIN, get a device token. The token is what everything else uses."""
    try:
        device_id, token = auth.login(body.pin, body.name, body.kind, _client_ip(request))
    except auth.AuthError as exc:
        log.warning("failed login from %s: %s", _client_ip(request), exc)
        raise HTTPException(status_code=403, detail=str(exc)) from None
    log.info("device signed in: %s (%s)", body.name, body.kind)
    return {"device_id": device_id, "token": token}


@app.get("/devices")
async def list_devices(device: dict = Depends(caller)):
    return {"devices": auth.devices(), "you": device["id"]}


@app.post("/devices/{device_id}/revoke")
async def revoke_device(device_id: str, device: dict = Depends(caller)):
    if not auth.revoke(device_id):
        raise HTTPException(status_code=404, detail="no such device")
    return {"revoked": device_id}


# ---------------------------------------------------------------------------
# Talking
# ---------------------------------------------------------------------------

class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


async def _answer(text: str) -> dict:
    """One turn, off the event loop, one at a time."""
    brain = get_brain()
    async with _brain_lock:
        reply = await run_in_threadpool(brain.handle, text)
    return {"reply": reply, "brain": getattr(brain, "name", "brain"),
            "pc_online": agents.registry.online()}


@app.post("/chat")
async def chat(body: ChatIn, device: dict = Depends(caller)):
    """Ask Jarvis something and get the whole answer back.

    Deliberately not streaming: this is the endpoint for curl, scripts and
    anything that just wants the reply. The HUD uses the websocket.
    """
    return await _answer(body.message)


@app.get("/health")
async def health():
    """Unauthenticated on purpose — a load balancer has no token.

    `pin_set` tells the login screen whether this server is configured at all,
    so "no PIN on the server" reads differently from "wrong PIN". Nothing beyond
    that is anyone's business — no counts, no names.
    """
    return {"ok": True, "assistant": config.ASSISTANT_NAME,
            "pc_online": agents.registry.online(),
            "pin_set": bool(auth.PIN)}


class ForgetIn(BaseModel):
    fragment: str = Field(min_length=1, max_length=200)


@app.get("/me")
async def me(device: dict = Depends(caller)):
    """Everything the settings screen shows.

    Deliberately one call: settings is a screen you glance at, and three
    round-trips to fill it means three chances to look half-broken.
    """
    brain = get_brain()
    return {
        "device": device,
        "brain": getattr(brain, "name", "?"),
        "assistant": config.ASSISTANT_NAME,
        "user": config.USER_TITLE,
        "facts": memory.facts(),
        "remembered": store.count(),
        "recent_actions": store.recent_actions(8),
        "pc": agents.registry.status(),
        "devices": auth.devices(),
        # The dashboard's UP NEXT panel. Carried here rather than fetched
        # separately for the same reason as everything else in this response:
        # a screen filling in two stages looks broken on a slow connection.
        "upcoming": [{**item, "said": agenda_store.describe(item)}
                     for item in agenda_store.upcoming(8)],
    }


@app.post("/facts/forget")
async def forget_fact(body: ForgetIn, device: dict = Depends(caller)):
    """Drop something Jarvis remembers. 'all' clears the lot."""
    return {"said": memory.forget_fact(body.fragment), "facts": memory.facts()}


@app.get("/status")
async def status(device: dict = Depends(caller)):
    return {
        "brain": getattr(get_brain(), "name", "?"),
        "exchanges_remembered": store.count(),
        "pc": agents.registry.status(),
        "devices": len(auth.devices()),
        "upcoming": agenda_store.count(),
    }


# ---------------------------------------------------------------------------
# The diary
# ---------------------------------------------------------------------------

class RemindIn(BaseModel):
    when: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=500)
    warn: str = Field(default="", max_length=60)


@app.get("/agenda")
async def get_agenda(device: dict = Depends(caller)):
    """What is coming up, soonest first — the dashboard's UP NEXT panel.

    `said` is the same line Jarvis would speak, so a screen and a spoken answer
    can never disagree about what is in the diary.
    """
    items = await run_in_threadpool(agenda_store.upcoming, 20)
    return {
        "items": [{**item, "said": agenda_store.describe(item)} for item in items],
        "count": len(items),
    }


@app.post("/agenda")
async def add_agenda(body: RemindIn, device: dict = Depends(caller)):
    """Add something without going through a brain.

    Worth having on its own: typing a date into a form should not depend on a
    free tier being up, and the offline outbox needs somewhere to replay to.
    """
    said = await run_in_threadpool(reminders.schedule, body.when, body.message, body.warn)
    items = await run_in_threadpool(agenda_store.upcoming, 20)
    return {"said": said,
            "items": [{**item, "said": agenda_store.describe(item)} for item in items]}


@app.delete("/agenda/{item_id}")
async def drop_agenda(item_id: int, device: dict = Depends(caller)):
    dropped = await run_in_threadpool(agenda_store.cancel_id, item_id)
    items = await run_in_threadpool(agenda_store.upcoming, 20)
    return {"dropped": dropped,
            "items": [{**item, "said": agenda_store.describe(item)} for item in items]}


@app.post("/tick")
async def tick():
    """Wake up, look at the diary, deliver anything due.

    Unauthenticated on purpose, and it does nothing an anonymous caller could
    misuse: no arguments, no output but a count, and the work is identical to
    what the server does by itself every thirty seconds.

    It exists because the free tier sleeps after a quarter of an hour with no
    traffic, and a sleeping server has no timers. An external cron hitting this
    every few minutes is what keeps a 7am reminder possible at all.
    """
    sent = await nudges.deliver_due()
    return {"ok": True, "delivered": sent, "listening": nudges.listeners.count()}


# ---------------------------------------------------------------------------
# The HUD's socket
# ---------------------------------------------------------------------------

@app.websocket("/ws/client")
async def ws_client(websocket: WebSocket):
    """What the phone and the desktop HUD hold open.

    Frames out: {"type": "status"|"reply"|"token"|"error"|"telemetry", ...}
    Frames in:  {"type": "say", "text": "..."}
    """
    await websocket.accept()
    device = await socket_caller(websocket)
    if device is None:
        return

    await websocket.send_text(json.dumps({
        "type": "status", "state": "online",
        "brain": getattr(get_brain(), "name", "?"),
        "pc_online": agents.registry.online(),
    }))

    nudges.listeners.add(websocket)
    # Anything that came due while nobody had the app open is waiting, not lost.
    # It arrives the moment there is someone to tell — which is the whole reason
    # the sweeper refuses to mark an item delivered into an empty room.
    await nudges.deliver_due()

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                frame = json.loads(raw)
            except ValueError:
                await websocket.send_text(json.dumps(
                    {"type": "error", "error": "that wasn't valid JSON"}))
                continue

            if frame.get("type") != "say":
                continue
            text = (frame.get("text") or "").strip()
            if not text:
                continue
            if not _rate_ok(device["id"]):
                await websocket.send_text(json.dumps(
                    {"type": "error", "error": "Slow down a moment."}))
                continue

            await websocket.send_text(json.dumps({"type": "status", "state": "thinking"}))
            try:
                answer = await _answer(text)
            except Exception as exc:  # noqa: BLE001  (one bad turn, not a dead socket)
                log.exception("turn failed")
                await websocket.send_text(json.dumps(
                    {"type": "error", "error": f"Something went wrong: {exc}"}))
                continue
            await websocket.send_text(json.dumps({"type": "reply", **answer}))
            # A turn may well have just put something in the diary for one
            # minute from now. Looking straight after means it arrives then,
            # rather than up to thirty seconds late.
            await nudges.deliver_due()
    except WebSocketDisconnect:
        pass
    finally:
        nudges.listeners.remove(websocket)


# ---------------------------------------------------------------------------
# The PC's socket
# ---------------------------------------------------------------------------

@app.websocket("/ws/agent")
async def ws_agent(websocket: WebSocket):
    """The link to Rohan's desktop. The agent dials in; the cloud calls back.

    Frames out: {"type": "call", "id": ..., "tool": ..., "args": {...}}
    Frames in:  {"type": "result", "id": ..., "result": "...", "ok": true}
                {"type": "telemetry", "cpu": .., "memory": .., "battery": ..}
    """
    await websocket.accept()
    device = await socket_caller(websocket)
    if device is None:
        return

    agent = agents.Agent(device["id"], device["name"], websocket)
    agents.registry.add(agent)
    log.info("PC agent connected: %s", device["name"])
    try:
        while True:
            raw = await websocket.receive_text()
            agent.last_seen = time.time()
            try:
                frame = json.loads(raw)
            except ValueError:
                continue
            kind = frame.get("type")
            if kind == "result":
                agent.resolve(str(frame.get("id", "")),
                              str(frame.get("result", "")),
                              bool(frame.get("ok", True)))
            elif kind == "telemetry":
                agent.telemetry = {k: v for k, v in frame.items() if k != "type"}
            # anything else is ignored rather than fatal: an agent from a newer
            # version may send frames this server has never heard of.
    except WebSocketDisconnect:
        pass
    finally:
        agents.registry.remove(agent)
        log.info("PC agent gone: %s", device["name"])


@app.exception_handler(auth.AuthError)
async def auth_error(request, exc):  # pragma: no cover - belt and braces
    return JSONResponse(status_code=401, content={"detail": str(exc)})


# ---------------------------------------------------------------------------
# The HUD
#
# Served by this same app, deliberately. One origin means no CORS, no
# preflights, and a token that never crosses an origin boundary — and it means
# the whole of VONDO is one thing to deploy rather than two.
#
# Mounted LAST: a mount at "/" matches everything the routes above did not, so
# putting it earlier would swallow /chat and /health.
# ---------------------------------------------------------------------------

_HUD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "web", "dist")

if os.path.isdir(_HUD):
    app.mount("/", StaticFiles(directory=_HUD, html=True), name="hud")
else:  # pragma: no cover - developer convenience
    @app.get("/")
    async def no_hud():
        return {"detail": "The HUD isn't built yet. Run:  cd web && npm run build"}

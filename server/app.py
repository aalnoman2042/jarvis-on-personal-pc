"""The cloud core — Jarvis with an address.

Everything the desktop app does, behind an API that a phone can reach. The
brains, the memory and the tools are unchanged; this file is only plumbing:
who is asking, which machine should do the work, and how the answer gets back.

Run it locally exactly as it will run in the cloud:

    set VONDO_PAIR_SECRET=something-only-you-know
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
import time

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from core import config
from core.brains import factory
from core.memory import store
from server import agents, auth

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
    log.info("vondo core up | devices paired: %d", auth.device_count())
    yield


app = FastAPI(title="VONDO core", version="2.0.0-dev", lifespan=lifespan)


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
# Pairing
# ---------------------------------------------------------------------------

class BootstrapIn(BaseModel):
    secret: str
    name: str = Field(default="first device", max_length=60)
    kind: str = Field(default="client", max_length=20)


class ClaimIn(BaseModel):
    code: str
    name: str = Field(default="device", max_length=60)
    kind: str = Field(default="client", max_length=20)


@app.post("/pair/bootstrap")
async def pair_bootstrap(body: BootstrapIn):
    """Pair the very first device. Refuses once any device exists."""
    try:
        device_id, token = auth.bootstrap(body.secret, body.name, body.kind)
    except auth.AuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    log.info("first device paired: %s (%s)", body.name, body.kind)
    return {"device_id": device_id, "token": token,
            "note": "Save this token — it is not shown again."}


@app.post("/pair/start")
async def pair_start(device: dict = Depends(caller)):
    """An authorised device asks for a code to read out to a new one."""
    code, ttl = auth.start_pairing(device["id"])
    return {"code": code, "expires_in": ttl}


@app.post("/pair/claim")
async def pair_claim(body: ClaimIn):
    """A new device redeems the code."""
    try:
        device_id, token = auth.claim(body.code, body.name, body.kind)
    except auth.AuthError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    log.info("device paired: %s (%s)", body.name, body.kind)
    return {"device_id": device_id, "token": token,
            "note": "Save this token — it is not shown again."}


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
    """Unauthenticated on purpose — a load balancer has no token."""
    return {"ok": True, "assistant": config.ASSISTANT_NAME,
            "pc_online": agents.registry.online()}


@app.get("/status")
async def status(device: dict = Depends(caller)):
    return {
        "brain": getattr(get_brain(), "name", "?"),
        "exchanges_remembered": store.count(),
        "pc": agents.registry.status(),
        "devices": len(auth.devices()),
    }


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
    except WebSocketDisconnect:
        pass


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

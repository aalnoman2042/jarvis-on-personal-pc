"""The cloud's end of the link to Rohan's PC.

A cloud server cannot open a connection into a home network — routers exist to
stop exactly that. So the PC agent dials *out*, and this module keeps the
resulting websocket and calls back down it when a brain asks for something only
the desktop can do.

Two things this must get right:

* **A dead PC is answered, not waited for.** If nothing is connected, a PC tool
  fails instantly with a sentence worth speaking, rather than hanging a
  conversation for thirty seconds. Rohan chose that behaviour explicitly.
* **The brains stay unaware.** They reach the desktop exactly as they do at
  home — the AI brains through `llm_tools.DISPATCH`, the rule-based one by
  calling `actions` directly — and the swap happens beneath both, in
  `core.lazy`. No brain contains the word "websocket".
"""
from __future__ import annotations

import asyncio
import json
import time

# Which functions need the physical PC is decided in core.lazy.PC_FUNCTIONS,
# because that is the layer every brain reaches the desktop through. Keeping a
# second copy of that list here is exactly how the two drift apart.

CALL_TIMEOUT = 20.0     # a PC action that takes longer than this has gone wrong


class PCOffline(Exception):
    """No agent is connected. The message is meant to be spoken aloud."""


class Agent:
    """One connected PC, and the calls in flight to it."""

    def __init__(self, device_id: str, name: str, websocket) -> None:
        self.device_id = device_id
        self.name = name
        self.ws = websocket
        self.connected_at = time.time()
        self.last_seen = time.time()
        self.telemetry: dict = {}
        self._pending: dict[str, asyncio.Future] = {}
        self._seq = 0

    def next_id(self) -> str:
        self._seq += 1
        return f"{self.device_id[:8]}-{self._seq}"

    async def call(self, tool: str, args: dict) -> str:
        """Ask the PC to run one tool and wait for its answer."""
        call_id = self.next_id()
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[call_id] = future
        try:
            await self.ws.send_text(json.dumps(
                {"type": "call", "id": call_id, "tool": tool, "args": args}))
            return await asyncio.wait_for(future, timeout=CALL_TIMEOUT)
        except asyncio.TimeoutError:
            raise PCOffline(
                f"Your PC didn't answer in time, so I couldn't {tool.replace('_', ' ')}."
            ) from None
        finally:
            self._pending.pop(call_id, None)

    def resolve(self, call_id: str, result: str, ok: bool = True) -> None:
        """A result came back up the socket."""
        future = self._pending.get(call_id)
        if future is None or future.done():
            return  # timed out already, or a duplicate — nothing to do
        if ok:
            future.set_result(result)
        else:
            future.set_exception(PCOffline(result))

    def fail_all(self, why: str) -> None:
        """The socket dropped; nothing in flight will ever be answered."""
        for future in self._pending.values():
            if not future.done():
                future.set_exception(PCOffline(why))
        self._pending.clear()


class Registry:
    """Every connected agent. In practice Rohan has one PC, but not by design."""

    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}

    REPLACED = 4409     # close code: a newer connection took this device over

    async def add(self, agent: Agent) -> None:
        """Register a PC, displacing any earlier connection for the same device.

        The old socket is now CLOSED rather than merely forgotten, and that is
        the important part. Forgetting it left two agents alive and neither
        aware of the other: two processes started by accident, each replacing
        the other in this dict every few seconds, so the PC looked like it was
        reconnecting constantly when both connections were in fact perfectly
        healthy. The symptom was indistinguishable from a bad network, and the
        cause was a second window nobody had noticed was open.

        Closing it with a distinct code lets the loser say what happened and
        stop, instead of reconnecting and starting the fight again.
        """
        old = self._agents.get(agent.device_id)
        self._agents[agent.device_id] = agent
        if old is None:
            return
        # A reconnect after a network blip: the old socket is gone even if it
        # has not noticed yet, so anything waiting on it is already lost.
        old.fail_all("The connection to your PC dropped.")
        try:
            await old.ws.close(code=self.REPLACED,
                               reason="another connection took over")
        except Exception:  # noqa: BLE001  (already gone, which is the usual case)
            pass

    def remove(self, agent: Agent) -> None:
        if self._agents.get(agent.device_id) is agent:
            del self._agents[agent.device_id]
        agent.fail_all("Your PC disconnected before that finished.")

    def any_agent(self) -> Agent | None:
        return next(iter(self._agents.values()), None)

    def online(self) -> bool:
        return bool(self._agents)

    def status(self) -> list[dict]:
        return [
            {"device_id": a.device_id, "name": a.name,
             "connected_at": a.connected_at, "last_seen": a.last_seen,
             "telemetry": a.telemetry}
            for a in self._agents.values()
        ]


registry = Registry()


def offline_reply(tool: str) -> str:
    """What Jarvis says when the PC is asleep and the answer is honest."""
    doing = tool.replace("_", " ")
    return (f"Your PC is offline, so I can't {doing} right now. "
            "Everything else still works.")


async def call_pc(tool: str, args: dict) -> str:
    agent = registry.any_agent()
    if agent is None:
        raise PCOffline(offline_reply(tool))
    return await agent.call(tool, args)


def install_hook(loop: asyncio.AbstractEventLoop) -> None:
    """Point the tool dispatcher at the PC agent.

    Brains run in a worker thread (they block on network calls), while the agent
    websocket lives on the event loop. `run_coroutine_threadsafe` is the bridge,
    and the `.result()` call blocks only that worker thread — never the loop.
    """
    from core import lazy

    def handler(tool: str, args: list, kwargs: dict) -> str:
        if not registry.online():
            return offline_reply(tool)
        payload = {"args": list(args), "kwargs": dict(kwargs)}
        try:
            future = asyncio.run_coroutine_threadsafe(call_pc(tool, payload), loop)
            return future.result(timeout=CALL_TIMEOUT + 5)
        except PCOffline as exc:
            return str(exc)
        except Exception as exc:  # noqa: BLE001  (never break a conversation)
            return f"I couldn't reach your PC just then. ({exc})"

    lazy.pc_handler = handler

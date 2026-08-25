"""Where the agent points, and where it keeps its key.

The token is kept in its own file rather than in `.env` for one reason: `.env`
is the file Rohan opens, edits and occasionally screenshots when something needs
configuring. A long-lived credential should not be in the middle of that.
`agent.token` is written once by the pairing step, gitignored, and never needs
looking at again.
"""
from __future__ import annotations

import os
import socket

from core import config

# VONDO_AGENT_TOKEN_FILE lets the tests point this somewhere disposable
# instead of writing a real credential into the repo.
TOKEN_FILE = (os.getenv("VONDO_AGENT_TOKEN_FILE")
              or os.path.join(config.PROJECT_DIR, "agent.token"))

# Where the cloud core lives. Defaults to a local server so the whole thing can
# be run end-to-end on one machine before anything is deployed.
CLOUD_URL = (os.getenv("VONDO_URL") or "http://127.0.0.1:8000").rstrip("/")
CLOUD_WS = CLOUD_URL.replace("https://", "wss://").replace("http://", "ws://")


def agent_name() -> str:
    """What this PC calls itself when pairing, so the device list is readable."""
    return os.getenv("VONDO_AGENT_NAME") or f"{socket.gethostname()} (PC)"


def load_token() -> str:
    try:
        with open(TOKEN_FILE, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def save_token(token: str) -> None:
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(token.strip())

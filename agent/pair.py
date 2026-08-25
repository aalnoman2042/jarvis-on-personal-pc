"""Link this PC to the cloud, once.

Run it, type your PIN. The token is saved to agent.token and that is the last
time any of this needs thinking about.

    python -m agent.pair

Typing the PIN rather than pasting a token around is the point: the long-lived
credential is generated on the server and written straight to a file, so it
never passes through a clipboard, a chat window or a text editor.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

from agent.settings import CLOUD_URL, TOKEN_FILE, agent_name, load_token, save_token


def claim(pin: str) -> str:
    """Exchange the PIN for this PC's long-lived token."""
    body = json.dumps({"pin": pin, "name": agent_name(), "kind": "agent"}).encode()
    request = urllib.request.Request(
        f"{CLOUD_URL}/login", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read())["token"]


def main() -> int:
    print(f"\n  Linking this PC to {CLOUD_URL}\n")

    if load_token():
        print(f"  This PC already has a token ({TOKEN_FILE}).")
        if input("  Sign in again and replace it? [y/N] ").strip().lower() != "y":
            print("  Left alone.\n")
            return 0
    pin = input("  Enter your Jarvis PIN: ").strip()
    if not pin:
        print("\n  No PIN, nothing to do.\n")
        return 1

    try:
        token = claim(pin)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        try:
            detail = json.loads(detail).get("detail", detail)
        except ValueError:
            pass
        print(f"\n  The server said no: {detail}")
        print("  Five wrong tries locks this address out for fifteen minutes.\n")
        return 1
    except OSError as exc:
        print(f"\n  Couldn't reach {CLOUD_URL} ({exc}).")
        print("  Is the cloud core running, and is VONDO_URL right?\n")
        return 1

    save_token(token)
    print(f"\n  Linked. Token saved to {TOKEN_FILE}")
    print("  Start the agent with:  start_agent.bat\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

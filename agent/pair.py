"""Pair this PC with the cloud, once.

On the phone: ask Jarvis to pair a device, and it gives you a six-digit code.
Here: run this, type the code. The token is saved to agent.token and that is the
last time any of this needs thinking about.

    python -m agent.pair

The code is worth typing rather than pasting a token around: it is good for five
minutes, works exactly once, and the credential itself never passes through a
clipboard, a chat window or a text editor.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

from agent.settings import CLOUD_URL, TOKEN_FILE, agent_name, load_token, save_token


def claim(code: str) -> str:
    body = json.dumps({"code": code, "name": agent_name(), "kind": "agent"}).encode()
    request = urllib.request.Request(
        f"{CLOUD_URL}/pair/claim", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read())["token"]


def main() -> int:
    print(f"\n  Pairing this PC with {CLOUD_URL}\n")

    if load_token():
        print(f"  This PC already has a token ({TOKEN_FILE}).")
        if input("  Pair again and replace it? [y/N] ").strip().lower() != "y":
            print("  Left alone.\n")
            return 0

    print("  On your phone, ask Jarvis to pair a new device.")
    code = input("  Then type the six-digit code here: ").strip()
    if not code:
        print("\n  No code, nothing to do.\n")
        return 1

    try:
        token = claim(code)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        try:
            detail = json.loads(detail).get("detail", detail)
        except ValueError:
            pass
        print(f"\n  The server said no: {detail}")
        print("  Codes last five minutes and work once. Ask for a fresh one.\n")
        return 1
    except OSError as exc:
        print(f"\n  Couldn't reach {CLOUD_URL} ({exc}).")
        print("  Is the cloud core running, and is VONDO_URL right?\n")
        return 1

    save_token(token)
    print(f"\n  Paired. Token saved to {TOKEN_FILE}")
    print("  Start the agent with:  start_agent.bat\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

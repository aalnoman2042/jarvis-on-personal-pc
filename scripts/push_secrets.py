"""Push the API keys from .env into Fly's secret vault.

Keys belong in Fly's vault, not in the image and not in git. This reads the
.env Rohan already maintains and sets the same names as Fly secrets, so there
is one place to edit a key rather than two.

It also mints VONDO_PAIR_SECRET on first run and prints it once. That secret
pairs the very first device and stops working the moment a device exists, so it
is worth exactly one showing and no storage.
"""
from __future__ import annotations

import os
import pathlib
import secrets
import subprocess
import sys

CARRIED = ("GROQ_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY")


def read_env(path: pathlib.Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def fly(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["flyctl", *args], capture_output=True, text=True)


def main() -> int:
    app = os.environ.get("VONDO_APP") or "vondo-jarvis"
    env = read_env(pathlib.Path(".env"))

    pairs: list[str] = []
    for key in CARRIED:
        value = env.get(key)
        # A placeholder in .env is worse than nothing: it would look configured
        # and fail at the first question.
        if value and "your_" not in value.lower() and len(value) > 12:
            pairs.append(f"{key}={value}")

    listed = fly("secrets", "list", "-a", app).stdout
    if "VONDO_PAIR_SECRET" not in listed:
        made = secrets.token_urlsafe(24)
        pairs.append(f"VONDO_PAIR_SECRET={made}")
        print()
        print("  " + "=" * 58)
        print("   FIRST-DEVICE PAIRING SECRET — write this down now.")
        print("   It is not shown again, and it stops working as soon as")
        print("   your first device is paired.")
        print()
        print(f"       {made}")
        print("  " + "=" * 58)
        print()

    if not pairs:
        print("   Secrets already set; nothing to push.")
        return 0

    names = ", ".join(p.split("=", 1)[0] for p in pairs)
    print(f"   Setting: {names}")
    # --stage so they land with the deploy that follows rather than triggering
    # a restart of a machine that does not exist yet.
    result = subprocess.run(["flyctl", "secrets", "set", "-a", app, "--stage", *pairs])
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())

"""Checks the built HUD is actually served and reachable.

Not a browser test — there is no headless browser here, and pretending
otherwise would be worse than being honest about it. What this proves is the
part that silently breaks: that `npm run build` output exists, that the cloud
core serves it at the root, that the JavaScript and CSS it references really
resolve, and that the API routes are not shadowed by the static mount.

Rendering, layout and the reactor still need a pair of eyes on a real screen.
"""
import os
import re
import sys
import tempfile
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

SCRATCH = tempfile.mkdtemp(prefix="vondo-hud-test-")
PORT = 8733

os.environ["VONDO_DB"] = os.path.join(SCRATCH, "test.db")
os.environ["VONDO_PIN"] = "2042"
os.environ["VONDO_BRAIN"] = "free"

import httpx  # noqa: E402
import uvicorn  # noqa: E402

from server.app import app  # noqa: E402

BASE = f"http://127.0.0.1:{PORT}"
DIST = os.path.join(ROOT, "web", "dist")

passed = failed = 0


def check(label, got, want=None, contains=None):
    global passed, failed
    if contains is not None:
        ok = contains.lower() in str(got).lower()
        detail = f"{str(got)[:120]!r} does not contain {contains!r}"
    else:
        ok = got == want
        detail = f"{got!r} != {want!r}"
    if ok:
        passed += 1
        print(f"  [ok  ] {label}")
    else:
        failed += 1
        print(f"  [FAIL] {label}: {detail}")


print("\n=== 1. the build produced something ===")
check("web/dist exists", os.path.isdir(DIST), True)
if not os.path.isdir(DIST):
    print("\n  Run:  cd web && npm run build\n")
    sys.exit(1)
check("index.html is there", os.path.isfile(os.path.join(DIST, "index.html")), True)

sizes = {}
for folder, _, files in os.walk(DIST):
    for name in files:
        sizes[name] = os.path.getsize(os.path.join(folder, name))
js = sum(v for k, v in sizes.items() if k.endswith(".js"))
css = sum(v for k, v in sizes.items() if k.endswith(".css"))
print(f"         -> {js / 1024:.0f} kB JavaScript, {css / 1024:.1f} kB CSS")
# "Lightweight" was a stated requirement, so it gets an actual number and a
# ceiling rather than a good intention.
check("the whole HUD is under 400 kB unzipped", js + css < 400_000, True)

server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning"))
threading.Thread(target=server.run, daemon=True).start()
for _ in range(100):
    try:
        httpx.get(f"{BASE}/health", timeout=0.5)
        break
    except Exception:
        time.sleep(0.1)

try:
    print("\n=== 2. the core serves it ===")
    page = httpx.get(f"{BASE}/")
    check("GET / returns the HUD", page.status_code, 200)
    check("  it is the right page", page.text, contains="<title>VONDO</title>")
    check("  and it is dark by default", page.text, contains='data-theme="jarvis"')

    print("\n=== 3. every asset the page asks for resolves ===")
    assets = re.findall(r'(?:src|href)="(/assets/[^"]+)"', page.text)
    check("the page references built assets", len(assets) >= 2, True)
    for path in assets:
        r = httpx.get(f"{BASE}{path}")
        check(f"  {path.split('/')[-1]}", r.status_code, 200)

    print("\n=== 4. the static mount has not swallowed the API ===")
    check("/health still answers", httpx.get(f"{BASE}/health").status_code, 200)
    check("  and says a PIN is configured",
          httpx.get(f"{BASE}/health").json()["pin_set"], True)
    check("/chat still refuses without a token",
          httpx.post(f"{BASE}/chat", json={"message": "hi"}).status_code, 401)
    check("/login is reachable and not swallowed by the static mount",
          httpx.post(f"{BASE}/login", json={"pin": "0000", "name": "probe"}).status_code, 403)

    print("\n=== 5. the login flow works over HTTP ===")
    r = httpx.post(f"{BASE}/login",
                   json={"pin": "2042", "name": "desktop", "kind": "client"})
    check("the PIN signs a device in", r.status_code, 200)
    token = r.json()["token"]
    check("and the token works",
          httpx.post(f"{BASE}/chat", headers={"Authorization": f"Bearer {token}"},
                     json={"message": "what time is it"}, timeout=30).status_code, 200)

finally:
    server.should_exit = True
    time.sleep(0.3)

print(f"\n{'=' * 52}\n  {passed} passed, {failed} failed\n{'=' * 52}")
print("\n  Note: this proves the HUD is built and served. How it LOOKS still")
print("  needs a real screen — start the core and open it.\n")
sys.exit(1 if failed else 0)

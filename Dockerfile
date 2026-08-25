# VONDO's cloud core, as one image.
#
# Two stages. The first builds the HUD with Node; the second is the Python
# runtime that actually ships. Node and node_modules never reach the final
# image — only the handful of built files in web/dist do, which keeps the thing
# that runs small and keeps a JavaScript toolchain out of production.

# ---------------------------------------------------------------------------
# 1. Build the HUD
# ---------------------------------------------------------------------------
FROM node:22-alpine AS hud

WORKDIR /build

# package files first, so a change to the app's source does not re-download
# every dependency on every deploy.
COPY web/package.json web/package-lock.json ./
RUN npm ci

COPY web/ ./
RUN npm run build


# ---------------------------------------------------------------------------
# 2. The service
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# PYTHONUNBUFFERED so logs appear in `fly logs` as they happen rather than when
# a buffer happens to flush — the difference between watching a deploy and
# guessing at one.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    VONDO_DB=/data/vondo.db

WORKDIR /app

COPY requirements/cloud.txt requirements/cloud.txt
RUN pip install --no-cache-dir -r requirements/cloud.txt

# Only what the server actually needs. legacy/ and agent/ are Rohan's desktop
# and have no business in a container: agent/ would be pointless there, and
# legacy/ would drag in a microphone stack that cannot exist on this machine.
COPY core/ core/
COPY server/ server/
COPY --from=hud /build/dist web/dist

# Not root. The process only ever needs to read the app and write /data.
RUN useradd --create-home --uid 10001 vondo \
    && mkdir -p /data \
    && chown -R vondo:vondo /app /data
USER vondo

EXPOSE 8080

# One worker, deliberately. The conversation is a single shared thread and the
# PC agent holds one websocket — a second worker would be a second brain with a
# second view of the world, and the agent would only be reachable from whichever
# worker it happened to connect to.
#
# Shell form, not exec form, so ${PORT} actually expands: Render assigns the
# port at runtime and an exec-form CMD would try to bind to the literal string
# "${PORT}". Falls back to 8080, which is what Fly expects.
CMD python -m uvicorn server.app:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1

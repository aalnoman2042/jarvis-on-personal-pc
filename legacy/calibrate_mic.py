"""Measure your microphone, so Jarvis stops guessing at it.

Guessing how loud "speech" is goes wrong badly in both directions: set it too
high and your voice is thrown away as silence, too low and every rustle gets
transcribed as nonsense. A phone used as a mic makes it worse, because its
level jumps around between launches.

So this measures the real thing. Sit quietly for a moment, then talk normally,
and it works out where the line between the two actually is on YOUR setup and
offers to save it.

    python calibrate_mic.py

It also transcribes you in a few accent models, so you can pick whichever one
gets your words right rather than trusting the default.
"""
from __future__ import annotations

# --- repo-root bootstrap -------------------------------------------------
# These scripts are launched directly (double-clicked via the .bat files), so
# Python puts legacy/ on sys.path, not the repo root -- and `core` would not be
# importable. Sibling imports below (voice, vondo) still resolve normally.
import os as _os
import sys as _sys

_ROOT = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
if _ROOT not in _sys.path:
    _sys.path.insert(0, _ROOT)
# -------------------------------------------------------------------------

import audioop
import time

import speech_recognition as sr

from core import config

SAMPLE_SECONDS = 4
ACCENTS = ["en-IN", "en-US", "en-GB"]


def _levels(source, recognizer, seconds: float) -> list[int]:
    """Loudness readings taken over a stretch of time."""
    readings = []
    end = time.time() + seconds
    while time.time() < end:
        readings.append(audioop.rms(source.stream.read(source.CHUNK),
                                    source.SAMPLE_WIDTH))
    return sorted(readings)


def _percentile(values: list[int], pct: float) -> int:
    if not values:
        return 0
    return values[min(len(values) - 1, int(len(values) * pct))]


def main() -> int:
    names = sr.Microphone.list_microphone_names()
    index = config.MIC_INDEX
    print(f"\nMicrophone: {names[index] if index is not None else 'system default'}"
          f"  (MIC_INDEX={index})\n")

    recognizer = sr.Recognizer()
    try:
        mic = sr.Microphone(device_index=index)
    except Exception as exc:  # noqa: BLE001
        print(f"Couldn't open that microphone: {exc}")
        print("Run 'python list_mics.py' and set MIC_INDEX in .env.")
        return 1

    with mic as source:
        input(f"1/2  Stay QUIET for {SAMPLE_SECONDS} seconds. Press Enter when ready...")
        quiet = _levels(source, recognizer, SAMPLE_SECONDS)
        room = _percentile(quiet, 0.95)   # ignore the odd click
        print(f"     room noise: typically {_percentile(quiet, 0.5)}, "
              f"peaking around {room}\n")

        input(f"2/2  Now TALK normally for {SAMPLE_SECONDS} seconds — say anything.\n"
              f"     Press Enter, then start talking...")
        loud = _levels(source, recognizer, SAMPLE_SECONDS)
        # The median of a stretch of speech skews low (words have gaps between
        # them), so judge the level from the louder part of what was said.
        voice = _percentile(loud, 0.75)
        print(f"     your voice: typically {voice}, peaking around {loud[-1]}\n")

    if voice <= room:
        print("Your voice didn't measure louder than the room.")
        print("Nothing here can fix that — the microphone isn't picking you up well.")
        print("Move it closer, or use a wired headset instead of a phone.\n")
        return 1

    # Sit between the two, nearer the noise, since missing what you said is
    # worse than occasionally listening to nothing.
    threshold = int(room + (voice - room) * 0.35)
    margin = voice / max(room, 1)
    print(f"Recommended STT_ENERGY: {threshold}")
    print(f"Your voice is {margin:.1f}x louder than the room "
          f"({'plenty of room to work with' if margin >= 3 else 'a bit close — a nearer mic would help'}).\n")

    print("Checking which accent model understands you best...")
    with mic as source:
        recognizer.energy_threshold = threshold
        recognizer.dynamic_energy_threshold = False
        recognizer.pause_threshold = config.STT_PAUSE
        print("     Say a full sentence now, something you'd normally ask Jarvis:")
        try:
            audio = recognizer.listen(source, timeout=10, phrase_time_limit=7)
        except sr.WaitTimeoutError:
            print("     (heard nothing at that threshold)\n")
            audio = None

    if audio is not None:
        for accent in ACCENTS:
            try:
                heard = recognizer.recognize_google(audio, language=accent)
                print(f"     {accent}: {heard!r}")
            except sr.UnknownValueError:
                print(f"     {accent}: (couldn't make it out)")
            except sr.RequestError as exc:
                print(f"     {accent}: (speech service error: {exc})")
        print("\n     Whichever got your words right — put it in .env as STT_LANGUAGE.")

    print()
    if input(f"Save STT_ENERGY={threshold} to .env? [y/N] ").strip().lower() in ("y", "yes"):
        config._write_env("STT_ENERGY", str(threshold))
        print(f"Saved. Jarvis will use {threshold} from now on, without re-guessing.")
    else:
        print(f"Not saved. Add STT_ENERGY={threshold} to .env yourself if you want it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

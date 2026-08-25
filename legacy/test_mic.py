# """Quick mic test — confirms DroidCam audio reaches VONDO as text.

# Run:  python test_mic.py
# Speak when it says 'Listening...'. It prints whatever it heard.
# If it never hears you, the problem is the mic/DroidCam, not VONDO.
# """
# import speech_recognition as sr

# import config

# r = sr.Recognizer()
# r.dynamic_energy_threshold = True
# mic = sr.Microphone(device_index=config.MIC_INDEX)

# print(f"Using mic index: {config.MIC_INDEX} "
#       f"({sr.Microphone.list_microphone_names()[config.MIC_INDEX] if config.MIC_INDEX is not None else 'system default'})")
# print("Calibrating for background noise... (stay quiet 1 sec)")
# with mic as src:
#     r.adjust_for_ambient_noise(src, duration=1)
# print(f"Energy threshold: {r.energy_threshold:.0f}")

# for attempt in range(5):
#     print(f"\n[{attempt + 1}/5] Listening... speak now:")
#     try:
#         with mic as src:
#             audio = r.listen(src, timeout=8, phrase_time_limit=6)
#     except sr.WaitTimeoutError:
#         print("  (heard nothing — is DroidCam connected and its audio on?)")
#         continue
#     try:
#         text = r.recognize_google(audio)
#         print(f"  HEARD: {text!r}")
#     except sr.UnknownValueError:
#         print("  (got audio, but couldn't understand it — try speaking clearer/louder)")
#     except sr.RequestError as e:
#         print(f"  (Google speech error: {e} — check internet)")

# print("\nDone. If nothing was heard at all, try MIC_INDEX 8 or 14 in .env.")


"""Quick mic test — confirms your mic reaches VONDO as text.

Run:  python test_mic.py
Speak when it says 'Listening...'. It prints whatever it heard.
If it never hears you, the problem is the mic setup, not VONDO.
"""

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
import pyaudio
import speech_recognition as sr

from core import config


def validate_mic_index(index):
    """Make sure MIC_INDEX actually points at an input-capable device.
    Prevents the confusing 'stream is None' crash when it's an output
    device (e.g. Speakers / Sound Mapper - Output) by mistake."""
    p = pyaudio.PyAudio()
    try:
        if index is None:
            info = p.get_default_input_device_info()
            print(f"MIC_INDEX not set — using system default: "
                  f"{info['index']}: {info['name']}")
            return info["index"]

        if index < 0 or index >= p.get_device_count():
            raise SystemExit(
                f"MIC_INDEX={index} is out of range. "
                f"Run list_mics.py and pick a valid input index."
            )

        info = p.get_device_info_by_index(index)
        if info.get("maxInputChannels", 0) <= 0:
            raise SystemExit(
                f"MIC_INDEX={index} ('{info['name']}') has NO input channels "
                f"— it's an output device (speaker), not a mic.\n"
                f"Run list_mics.py and pick one of the devices listed there."
            )
        print(f"Using mic index: {index} ({info['name']})")
        return index
    finally:
        p.terminate()


mic_index = validate_mic_index(config.MIC_INDEX)

r = sr.Recognizer()
r.dynamic_energy_threshold = True
mic = sr.Microphone(device_index=mic_index)

print("Calibrating for background noise... (stay quiet 1 sec)")
with mic as src:
    r.adjust_for_ambient_noise(src, duration=1)
print(f"Energy threshold: {r.energy_threshold:.0f}")

for attempt in range(5):
    print(f"\n[{attempt + 1}/5] Listening... speak now:")
    try:
        with mic as src:
            audio = r.listen(src, timeout=8, phrase_time_limit=6)
    except sr.WaitTimeoutError:
        print("  (heard nothing — is your mic plugged in and unmuted?)")
        continue
    try:
        text = r.recognize_google(audio)
        print(f"  HEARD: {text!r}")
    except sr.UnknownValueError:
        print("  (got audio, but couldn't understand it — try speaking clearer/louder)")
    except sr.RequestError as e:
        print(f"  (Google speech error: {e} — check internet)")

print("\nDone. If nothing was heard at all, re-run list_mics.py and double-check MIC_INDEX.")
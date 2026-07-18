"""Quick mic test — confirms DroidCam audio reaches VONDO as text.

Run:  python test_mic.py
Speak when it says 'Listening...'. It prints whatever it heard.
If it never hears you, the problem is the mic/DroidCam, not VONDO.
"""
import speech_recognition as sr

import config

r = sr.Recognizer()
r.dynamic_energy_threshold = True
mic = sr.Microphone(device_index=config.MIC_INDEX)

print(f"Using mic index: {config.MIC_INDEX} "
      f"({sr.Microphone.list_microphone_names()[config.MIC_INDEX] if config.MIC_INDEX is not None else 'system default'})")
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
        print("  (heard nothing — is DroidCam connected and its audio on?)")
        continue
    try:
        text = r.recognize_google(audio)
        print(f"  HEARD: {text!r}")
    except sr.UnknownValueError:
        print("  (got audio, but couldn't understand it — try speaking clearer/louder)")
    except sr.RequestError as e:
        print(f"  (Google speech error: {e} — check internet)")

print("\nDone. If nothing was heard at all, try MIC_INDEX 8 or 14 in .env.")

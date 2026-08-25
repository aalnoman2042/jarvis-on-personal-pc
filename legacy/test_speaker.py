"""Diagnose Jarvis's voice output.

Run:  python test_speaker.py
It prints WHERE your PC is sending audio, then speaks a test sentence.
If you see the text but hear nothing, the 'Default OUTPUT device' below is
the culprit — it should be your speakers/headphones, NOT DroidCam or HDMI.
Fix: right-click taskbar speaker icon -> Sound settings -> Output -> pick your speakers.
"""
import pyaudio

import voice

# Show where Windows is currently sending sound.
p = pyaudio.PyAudio()
try:
    out = p.get_default_output_device_info()
    print(f"\n>>> Default OUTPUT device: {out['name']}")
    if "droidcam" in out["name"].lower():
        print("    !!! This is DroidCam — that's why you hear nothing.")
        print("    !!! Change your Windows Output device to your real speakers/headphones.")
except Exception as e:
    print(f"(couldn't read default output device: {e})")
print("\nAll output devices on this PC:")
for i in range(p.get_device_count()):
    d = p.get_device_info_by_index(i)
    if d.get("maxOutputChannels", 0) > 0:
        print(f"  {i}: {d['name']}")
p.terminate()

print(f"\nVoice = {__import__('config').TTS_VOICE or 'system default'} | rate {voice._SAPI_RATE}")
print("Speaking now — you should HEAR this...\n")
voice._speak_sapi("Hello Rohan. This is Jarvis, your assistant. If you can hear me, everything works.")
print("Done. Did you hear it?")

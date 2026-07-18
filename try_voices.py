"""Hear the available neural voices and pick the one you like.

Run:  python try_voices.py
Each voice speaks a sample. Note the name you like, then set it in .env:
    TTS_VOICE=jenny
"""
import config
import voice

SAMPLES = [
    "aria", "jenny", "michelle", "ana", "sonia", "libby",
    "natasha", "neerja", "guy", "eric", "christopher", "ryan",
]
LINE = "Hi Rohan. This is how I sound as your assistant. If you like this voice, pick me."

for name in SAMPLES:
    config.TTS_VOICE = name  # override for this sample
    print(f">>> {name}  ({voice.EDGE_VOICES[name]})")
    try:
        voice._speak_edge(f"{LINE} My name is {name}.")
    except Exception as exc:  # noqa: BLE001
        print(f"    (failed: {exc})")

print("\nPick your favourite, then set  TTS_VOICE=<name>  in your .env file.")

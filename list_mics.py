"""List the microphone input devices VONDO can use.

Run:  python list_mics.py
Then put the number of the mic you want into MIC_INDEX in your .env file.
"""
import speech_recognition as sr

print("Available microphones (set MIC_INDEX in .env to one of these numbers):\n")
for i, name in enumerate(sr.Microphone.list_microphone_names()):
    hint = "   <-- DroidCam" if "droid" in name.lower() else ""
    print(f"  {i:2}: {name}{hint}")

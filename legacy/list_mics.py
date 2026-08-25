# """List the microphone input devices VONDO can use.

# Run:  python list_mics.py
# Then put the number of the mic you want into MIC_INDEX in your .env file.
# """
# import speech_recognition as sr

# print("Available microphones (set MIC_INDEX in .env to one of these numbers):\n")
# for i, name in enumerate(sr.Microphone.list_microphone_names()):
#     hint = "   <-- DroidCam" if "droid" in name.lower() else ""
#     print(f"  {i:2}: {name}{hint}")


"""List ONLY real input-capable microphone devices VONDO can use.

Run:  python list_mics.py
Then put the number of the mic you want into MIC_INDEX in your .env file.

Why this version is different:
speech_recognition's Microphone.list_microphone_names() just echoes
PyAudio's raw device list, which on Windows (MME host API) can include
output devices like "Speakers" or "Microsoft Sound Mapper - Output" with
a nonzero index but NO usable input stream. This script filters by
maxInputChannels so you only see devices that can actually record.
"""
import pyaudio

p = pyaudio.PyAudio()

print("Available INPUT devices (set MIC_INDEX in .env to one of these numbers):\n")

found_any = False
for i in range(p.get_device_count()):
    info = p.get_device_info_by_index(i)
    if info.get("maxInputChannels", 0) > 0:
        found_any = True
        name = info.get("name", "Unknown")
        host_api = p.get_host_api_info_by_index(info.get("hostApi", 0)).get("name", "?")
        default_sr = int(info.get("defaultSampleRate", 0))
        hint = "   <-- DroidCam" if "droid" in name.lower() else ""
        is_default = ""
        try:
            default_input = p.get_default_input_device_info()
            if default_input.get("index") == i:
                is_default = "   <-- Windows default"
        except Exception:
            pass
        print(f"  {i:2}: {name}  [{host_api}, {default_sr} Hz]{hint}{is_default}")

if not found_any:
    print("  No input devices found! Check Windows Sound settings > Recording tab.")

p.terminate()
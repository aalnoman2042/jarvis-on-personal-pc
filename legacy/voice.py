"""VONDO's ears and mouth.

- Speech-to-text: Google's free web speech API (needs internet).
- Text-to-speech: Microsoft Edge neural voices (free, natural-sounding, needs
  internet), with Windows SAPI and then pyttsx3 as offline fallbacks.

Pick a voice with TTS_VOICE in .env (a friendly name like 'aria' or 'neerja',
or a full Edge voice id). Run `python try_voices.py` to hear the options.
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

import asyncio
import base64
import ctypes
import os
import subprocess
import tempfile
import threading

import speech_recognition as sr

from core import config

# Friendly name -> Edge neural voice id. Add more from `edge-tts --list-voices`.
EDGE_VOICES = {
    # Female
    "aria": "en-US-AriaNeural",        # warm, natural (US)
    "jenny": "en-US-JennyNeural",      # friendly, assistant-like (US)
    "michelle": "en-US-MichelleNeural",  # calm (US)
    "ana": "en-US-AnaNeural",          # youthful (US)
    "sonia": "en-GB-SoniaNeural",      # British female
    "libby": "en-GB-LibbyNeural",      # British female
    "natasha": "en-AU-NatashaNeural",  # Australian female
    "neerja": "en-IN-NeerjaNeural",    # Indian female
    # Male
    "guy": "en-US-GuyNeural",          # US male
    "eric": "en-US-EricNeural",        # US male, calm
    "christopher": "en-US-ChristopherNeural",  # US male, deep
    "ryan": "en-GB-RyanNeural",        # British male
    "prabhat": "en-IN-PrabhatNeural",  # Indian male
}

# Which of the friendly names above are male. Used to keep the offline fallback
# voices male too — Windows has no "Ryan", so without this a dropped connection
# would suddenly answer you in the default female SAPI voice.
MALE_VOICES = {"guy", "eric", "christopher", "ryan", "prabhat"}
# Voices actually installed on Windows: David is the male one, Zira the female.
SAPI_MALE, SAPI_FEMALE = "David", "Zira"


def _sapi_voice_name() -> str:
    """The installed Windows voice that best matches the chosen Edge voice."""
    v = (config.TTS_VOICE or "").strip().lower()
    if v in EDGE_VOICES:
        return SAPI_MALE if v in MALE_VOICES else SAPI_FEMALE
    if "neural" in v:  # a full Edge id like en-GB-RyanNeural
        return SAPI_MALE if any(m in v for m in
                                ("ryan", "guy", "eric", "christopher", "prabhat")) else SAPI_FEMALE
    return config.TTS_VOICE.strip()  # already a Windows voice name, e.g. "David"
DEFAULT_EDGE_VOICE = "en-US-AriaNeural"


def _resolve_edge_voice() -> str:
    v = (config.TTS_VOICE or "").strip()
    if v.lower() in EDGE_VOICES:
        return EDGE_VOICES[v.lower()]
    if "Neural" in v:  # already a full Edge voice id
        return v
    return DEFAULT_EDGE_VOICE  # e.g. blank, or old SAPI names like "Zira"


def _edge_rate() -> str:
    pct = max(-50, min(50, round((config.TTS_RATE - 175) * 0.6)))
    return f"{'+' if pct >= 0 else ''}{pct}%"


_play_counter = 0


def _play_mp3(path: str) -> None:
    """Play an mp3 synchronously using Windows' built-in winmm (no extra deps)."""
    global _play_counter
    _play_counter += 1
    alias = f"vondoaudio{_play_counter}"
    mci = ctypes.windll.winmm.mciSendStringW
    mci(f'open "{path}" type mpegvideo alias {alias}', None, 0, None)
    try:
        mci(f"play {alias} wait", None, 0, None)
    finally:
        mci(f"close {alias}", None, 0, None)


def _speak_edge(text: str) -> None:
    """Speak with an Edge neural voice (best quality; needs internet)."""
    import edge_tts

    fd, path = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)
    try:
        asyncio.run(
            edge_tts.Communicate(text, _resolve_edge_voice(), rate=_edge_rate()).save(path)
        )
        _play_mp3(path)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def _speak_sapi(text: str) -> None:
    """Speak with Windows SAPI (offline fallback)."""
    b64 = base64.b64encode(text.encode("utf-16-le")).decode()
    voice_pick = ""
    wanted = _sapi_voice_name()
    if wanted:
        v = "".join(c for c in wanted if c.isalnum() or c == " ")
        voice_pick = (
            "$v = $s.GetInstalledVoices() | "
            f"? {{ $_.VoiceInfo.Name -like '*{v}*' }} | select -First 1; "
            "if ($v) { $s.SelectVoice($v.VoiceInfo.Name) };"
        )
    sapi_rate = max(-10, min(10, round((config.TTS_RATE - 175) / 15)))
    ps = (
        "Add-Type -AssemblyName System.Speech;"
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        f"$s.Rate = {sapi_rate};"
        f"{voice_pick}"
        f"$t = [Text.Encoding]::Unicode.GetString([Convert]::FromBase64String('{b64}'));"
        "$s.Speak($t);"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
        check=True, capture_output=True,
    )


def _speak_pyttsx3(text: str) -> None:
    """Last-resort offline TTS."""
    import pyttsx3

    e = pyttsx3.init()
    e.setProperty("rate", config.TTS_RATE)
    # Match the chosen voice's gender here too, so the very last fallback
    # doesn't answer in a different voice than every other route.
    wanted = _sapi_voice_name().lower()
    if wanted:
        for v in e.getProperty("voices"):
            if wanted in v.name.lower():
                e.setProperty("voice", v.id)
                break
    e.say(text)
    e.runAndWait()
    e.stop()


class Voice:
    def __init__(self) -> None:
        # A lock so a reminder firing mid-reply doesn't talk over the main voice.
        self._speak_lock = threading.Lock()

        # ---- Speech to text ----
        self._recognizer = sr.Recognizer()
        self._recognizer.dynamic_energy_threshold = True
        # Let a natural mid-sentence breath pass without ending the phrase —
        # cutting early is what turns "open chrome and search" into "open chro".
        self._recognizer.pause_threshold = config.STT_PAUSE
        self._recognizer.non_speaking_duration = min(0.5, config.STT_PAUSE / 2)
        try:
            self._mic = sr.Microphone(device_index=config.MIC_INDEX)
        except Exception as exc:  # noqa: BLE001
            print(f"[mic index {config.MIC_INDEX} unavailable ({exc}); using default mic]")
            self._mic = sr.Microphone()
        self.calibrate(config.STT_CALIBRATE)
        if config.STT_ENERGY > 0:
            # A fixed floor beats auto-tuning in a room with constant background
            # noise (fan, traffic), which otherwise drags the threshold down.
            self._recognizer.energy_threshold = config.STT_ENERGY
            self._recognizer.dynamic_energy_threshold = False

    # The loudness range within which "is this speech?" is a sensible question.
    #
    # Listening to the room for a moment is only a good estimate if the room is
    # steady. A phone used as a microphone streams in bursts — measured on this
    # PC the same mic calibrated to 18 one minute and 1161 the next — and the
    # reading lands wherever it happened to land.
    #
    # Too low and every keyboard tap is transcribed as nonsense. Too high and
    # your voice is thrown away as silence. Those aren't equally bad: a
    # threshold that's too low costs a wasted lookup that returns nothing, while
    # one that's too high loses the sentence you just said. So the band is
    # deliberately generous at the top and the ceiling matters more than the
    # floor. Set STT_ENERGY in .env to skip the guessing entirely.
    MIN_ENERGY = 80
    MAX_ENERGY = 400

    def calibrate(self, seconds: float = 1.5) -> None:
        """Learn the room's noise floor. Re-run it if your surroundings change."""
        try:
            with self._mic as source:
                self._recognizer.adjust_for_ambient_noise(source, duration=seconds)
            measured = self._recognizer.energy_threshold
            clamped = min(self.MAX_ENERGY, max(self.MIN_ENERGY, measured))
            self._recognizer.energy_threshold = clamped
            if clamped != measured:
                why = ("that would have ignored you" if measured > clamped
                       else "that would have heard every rustle")
                print(f"[mic calibrated — measured {measured:.0f}, using {clamped:.0f}: "
                      f"{why}]")
            else:
                print(f"[mic calibrated — noise floor {measured:.0f}]")
        except Exception as exc:  # noqa: BLE001
            print(f"[couldn't calibrate the mic: {exc}]")

    def say(self, text: str) -> None:
        """Speak text aloud (Edge -> SAPI -> pyttsx3), printing it too."""
        if not text:
            return
        print(f"{config.ASSISTANT_NAME}: {text}")
        with self._speak_lock:
            for method in (_speak_edge, _speak_sapi, _speak_pyttsx3):
                try:
                    method(text)
                    return
                except Exception as exc:  # noqa: BLE001
                    print(f"[{method.__name__} failed: {exc}; trying next]")

    def listen(self, timeout: float | None = 6, phrase_limit: float | None = 8) -> str:
        """Listen once and return recognized text (lowercased), or '' on failure."""
        try:
            with self._mic as source:
                audio = self._recognizer.listen(
                    source, timeout=timeout, phrase_time_limit=phrase_limit
                )
        except sr.WaitTimeoutError:
            return ""
        try:
            # show_all returns every candidate transcription with a confidence
            # score; the plain call just hands back the first, which often isn't
            # the best one. Picking the highest-confidence line measurably cuts
            # misheard commands.
            result = self._recognizer.recognize_google(
                audio, language=config.STT_LANGUAGE, show_all=True
            )
            if not result:
                return ""
            if isinstance(result, dict):
                guesses = result.get("alternative", [])
                if not guesses:
                    return ""
                best = max(guesses, key=lambda g: g.get("confidence", 0))
                text = best.get("transcript", "")
                score = best.get("confidence")
                print(f"You: {text}" + (f"  [{score:.0%} sure]" if score else ""))
            else:  # older API shape — already a plain string
                text = str(result)
                print(f"You: {text}")
            return text.lower().strip()
        except sr.UnknownValueError:
            return ""
        except sr.RequestError as exc:
            print(f"[speech recognition error: {exc}]")
            return ""

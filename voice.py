"""VONDO's ears and mouth.

- Speech-to-text: Google's free web speech API (needs internet).
- Text-to-speech: Microsoft Edge neural voices (free, natural-sounding, needs
  internet), with Windows SAPI and then pyttsx3 as offline fallbacks.

Pick a voice with TTS_VOICE in .env (a friendly name like 'aria' or 'neerja',
or a full Edge voice id). Run `python try_voices.py` to hear the options.
"""
from __future__ import annotations

import asyncio
import base64
import ctypes
import os
import subprocess
import tempfile
import threading

import speech_recognition as sr

import config

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
    if config.TTS_VOICE and "Neural" not in config.TTS_VOICE:
        v = "".join(c for c in config.TTS_VOICE if c.isalnum() or c == " ")
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
        try:
            self._mic = sr.Microphone(device_index=config.MIC_INDEX)
        except Exception as exc:  # noqa: BLE001
            print(f"[mic index {config.MIC_INDEX} unavailable ({exc}); using default mic]")
            self._mic = sr.Microphone()
        with self._mic as source:
            self._recognizer.adjust_for_ambient_noise(source, duration=1)

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
            text = self._recognizer.recognize_google(audio)
            print(f"You: {text}")
            return text.lower().strip()
        except sr.UnknownValueError:
            return ""
        except sr.RequestError as exc:
            print(f"[speech recognition error: {exc}]")
            return ""

"""JARVIS desktop UI — a small window instead of the cmd console.

Run:  pythonw jarvis_gui.py     (no black console window)
   or double-click start_jarvis.bat

Shows a glowing status orb (Listening / Thinking / Speaking), the live
conversation, and Pause / Power-off buttons. Uses the same brain, voice,
and reminders as the console version.
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

import sys
import threading
import time
import tkinter as tk
from tkinter import scrolledtext, ttk

from core import actions
from core import config
from core import reminders
import vondo
from voice import Voice

# --- JARVIS dark theme ---
BG = "#0a0e14"
PANEL = "#0d1117"
FG = "#e6edf3"
ACCENT = "#00d4ff"
DIM = "#3a4657"
STATUS_COLORS = {
    "Starting": DIM,
    "Online": ACCENT,
    "Listening": "#3fb950",
    "Thinking": "#d29922",
    "Speaking": "#58a6ff",
    "Paused": DIM,
    "Offline": "#f85149",
    "Switching": "#d29922",
}

# Dropdown label -> VONDO_BRAIN value. Switch any time while Jarvis is running.
BRAIN_LABELS = {
    "Auto  ·  cloud first, local only if needed": "auto",
    "Gemini  ·  free, cloud": "gemini",
    "Groq  ·  free, fastest": "groq",
    "Ollama  ·  free, offline, on this PC": "ollama",
    "Claude  ·  paid, smartest": "claude",
    "Offline rules  ·  no AI": "free",
}
BRAIN_VALUES = {v: k for k, v in BRAIN_LABELS.items()}


class JarvisGUI:
    def __init__(self, root: tk.Tk, booted: bool = False) -> None:
        self.root = root
        self.booted = booted
        self.running = True
        self.paused = False
        self._active = False
        self._pulse = 0
        self.voice = None
        self.brain = None

        root.title(config.ASSISTANT_NAME)
        root.configure(bg=BG)
        root.geometry("440x580")
        root.minsize(380, 460)
        root.attributes("-topmost", True)  # always on top

        tk.Label(root, text=config.ASSISTANT_NAME.upper(), fg=ACCENT, bg=BG,
                 font=("Segoe UI", 24, "bold"), pady=6).pack(pady=(16, 0))

        self.canvas = tk.Canvas(root, width=130, height=130, bg=BG, highlightthickness=0)
        self.canvas.pack(pady=4)
        self.orb = self.canvas.create_oval(35, 35, 95, 95, outline=ACCENT, width=3, fill=BG)

        self.status_var = tk.StringVar(value="Starting...")
        tk.Label(root, textvariable=self.status_var, fg=FG, bg=BG,
                 font=("Segoe UI", 12)).pack()

        # ---- Brain picker: swap AI backends live, no restart ----
        picker = tk.Frame(root, bg=BG)
        picker.pack(pady=(10, 0))
        tk.Label(picker, text="Brain", fg=DIM, bg=BG, font=("Segoe UI", 9)).pack(side=tk.LEFT,
                                                                                 padx=(0, 8))
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Jarvis.TCombobox", fieldbackground=PANEL, background=PANEL,
                        foreground=FG, arrowcolor=ACCENT, bordercolor=DIM, lightcolor=PANEL,
                        darkcolor=PANEL, selectbackground=PANEL, selectforeground=FG)
        self.brain_var = tk.StringVar(value=BRAIN_VALUES.get(config.BRAIN, config.BRAIN))
        self.brain_box = ttk.Combobox(
            picker, textvariable=self.brain_var, values=list(BRAIN_LABELS),
            state="readonly", width=30, style="Jarvis.TCombobox", font=("Segoe UI", 9))
        self.brain_box.pack(side=tk.LEFT)
        self.brain_box.bind("<<ComboboxSelected>>", self._on_brain_picked)

        self.log = scrolledtext.ScrolledText(
            root, bg=PANEL, fg=FG, font=("Consolas", 10), wrap=tk.WORD,
            relief=tk.FLAT, height=14, insertbackground=FG, borderwidth=0)
        self.log.pack(fill=tk.BOTH, expand=True, padx=14, pady=12)
        self.log.tag_config("you", foreground="#8b949e")
        self.log.tag_config("me", foreground=ACCENT, font=("Consolas", 10, "bold"))
        self.log.configure(state=tk.DISABLED)

        bar = tk.Frame(root, bg=BG)
        bar.pack(pady=(0, 16))
        self.pause_btn = tk.Button(bar, text="⏸  Pause", width=12, command=self.toggle_pause,
                                   bg=DIM, fg=FG, relief=tk.FLAT, font=("Segoe UI", 10),
                                   activebackground=ACCENT, cursor="hand2")
        self.pause_btn.pack(side=tk.LEFT, padx=6)
        tk.Button(bar, text="⏻  Power Off", width=12, command=self.power_off,
                  bg="#3d1518", fg="#ff7b72", relief=tk.FLAT, font=("Segoe UI", 10),
                  activebackground="#f85149", cursor="hand2").pack(side=tk.LEFT, padx=6)

        root.protocol("WM_DELETE_WINDOW", self.power_off)
        self._animate()
        threading.Thread(target=self._loop, daemon=True).start()

    # ---- thread-safe UI helpers (always scheduled on the main thread) ----
    def set_status(self, text: str) -> None:
        def upd():
            self.status_var.set(text)
            self.canvas.itemconfig(self.orb, outline=STATUS_COLORS.get(text, ACCENT))
            self._active = text in ("Listening", "Speaking")
        self.root.after(0, upd)

    def add_line(self, who: str, text: str) -> None:
        def upd():
            self.log.configure(state=tk.NORMAL)
            self.log.insert(tk.END, f"{who}:  ", "you" if who == "You" else "me")
            self.log.insert(tk.END, f"{text}\n")
            self.log.see(tk.END)
            self.log.configure(state=tk.DISABLED)
        self.root.after(0, upd)

    def _animate(self) -> None:
        if self._active:
            self._pulse = (self._pulse + 1) % 40
            tri = self._pulse if self._pulse < 20 else 40 - self._pulse  # 0..20..0
            r = 26 + tri * 0.5
        else:
            r = 30
        self.canvas.coords(self.orb, 65 - r, 65 - r, 65 + r, 65 + r)
        self.root.after(60, self._animate)

    # ---- speaking ----
    def say(self, text: str) -> None:
        self.add_line(config.ASSISTANT_NAME, text)
        if self.voice:
            self.voice.say(text)

    def reminder_say(self, text: str) -> None:
        self.add_line(config.ASSISTANT_NAME, text)
        if self.voice:
            self.voice.say(text)

    # ---- controls ----
    def toggle_pause(self) -> None:
        self.paused = not self.paused
        self.pause_btn.config(text="▶  Resume" if self.paused else "⏸  Pause")

    # ---- brain switching ----
    def _on_brain_picked(self, _event=None) -> None:
        """Dropdown changed — build the new brain off the UI thread so the
        window never freezes (a local model can take a moment to warm up)."""
        choice = BRAIN_LABELS.get(self.brain_var.get())
        if not choice or (self.brain and choice == getattr(self, "_brain_choice", None)):
            return
        self.brain_box.configure(state=tk.DISABLED)
        self.set_status("Switching")
        threading.Thread(target=self._switch_brain, args=(choice,), daemon=True).start()

    def _switch_brain(self, choice: str) -> None:
        new_brain = vondo.make_brain(choice)
        # make_brain() never raises — it falls back to the offline brain and says
        # why on the console. Detect that so the UI doesn't claim a false success.
        landed_on = getattr(new_brain, "name", "free").split("+")[0]
        self.brain = new_brain
        self._brain_choice = choice
        try:
            config.set_brain(choice)  # remember for next launch
        except Exception as exc:  # noqa: BLE001
            print(f"[couldn't save brain choice: {exc}]")

        if landed_on == choice:
            self.say(f"Switched to the {choice} brain.")
        elif choice == "ollama":
            self.say("I couldn't reach the local model. Make sure Ollama is running. "
                     "Using offline commands for now.")
        else:
            self.say(f"The {choice} brain wouldn't start, so I'm on offline commands. "
                     f"Check the key in your settings file.")
        self.root.after(0, lambda: self.brain_box.configure(state="readonly"))

    def power_off(self) -> None:
        """Full off: stop now AND stay off across reboots until started again.

        We remember 'off' rather than removing the boot launcher, so at the next
        PC start Jarvis knows you turned it off and stays quiet. Start it again
        (start_jarvis.bat or a reboot after turning it back on) to resume.
        """
        self.running = False
        try:
            actions.set_power_state(False)  # won't auto-start next boot
        except Exception:  # noqa: BLE001
            pass
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    # ---- main worker loop (background thread) ----
    def _loop(self) -> None:
        self.set_status("Starting")
        actions.set_power_state(True)  # I'm on now -> come back at next boot
        self.voice = Voice()
        reminders.start(self.reminder_say)
        self.brain = vondo.make_brain()
        self._brain_choice = config.BRAIN
        self.say(config.boot_greeting() if self.booted else self.brain.greeting())

        while self.running:
            if self.paused:
                self.set_status("Paused")
                time.sleep(0.3)
                continue
            self.set_status("Listening")
            try:
                command = vondo.wants_action(self.voice, self.brain)
            except Exception:  # noqa: BLE001
                command = ""
            if not self.running:
                break
            if not command:
                continue
            self.add_line("You", command)
            self.set_status("Thinking")
            reply = self.brain.handle(command)
            if reply == "__EXIT__":
                self.say("Goodbye.")
                self.running = False
                try:
                    actions.set_power_state(False)  # you told me to stop -> stay off next boot
                except Exception:  # noqa: BLE001
                    pass
                self.root.after(400, self.root.destroy)
                break
            if reply:
                self.set_status("Speaking")
                self.say(reply)
        self.set_status("Offline")


def main() -> None:
    booted = "--boot" in sys.argv
    root = tk.Tk()
    JarvisGUI(root, booted)
    root.mainloop()


if __name__ == "__main__":
    main()

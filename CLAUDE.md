# VONDO — working notes

Jarvis: a personal assistant for Rohan. v1 was a Windows desktop app; v2 moves
the brain to the cloud and puts a HUD on every screen. Both live in this repo
during the migration.

## Where things are

| Folder | What it is | May it touch Windows? |
|---|---|---|
| `core/` | Brains, memory, tools, settings. Deploys to the cloud. | **No** (one exception below) |
| `legacy/` | v1: console loop, Tkinter window, local mic/speakers. Still works. | Yes |
| `requirements/` | Three dependency lists: `cloud`, `agent`, `legacy`. | — |
| `server/` | FastAPI cloud core. **Phase 02.** | No |
| `agent/` | The thin PC agent. **Phase 03.** | Yes — that's its job |
| `web/` | The React PWA / FUI. **Phase 04.** | — |

`.bat` launchers stay at the repo root because Rohan double-clicks them.

## Rules that are easy to break

**`core/` must import cleanly on Linux with no mic, no screen, no Windows.**
That is the whole point of the split — it is what gets deployed.

**The one exception is `core/actions.py`**, which still holds the Windows half of
the tool set (`pyautogui`, `psutil`, `ctypes`, `taskkill`). It is split into the
PC agent in phase 03. Until then it is imported *lazily* by `core/tools/llm_tools.py`
and never at package-import time. Do not add new Windows code to `core/`.

**`PROJECT_DIR` is the repo root, not the folder the module sits in.** Both
`core/config.py` and `core/actions.py` walk up one level from `__file__`:

```python
CORE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(CORE_DIR)          # <- the extra dirname matters
```

Collapse that and `.env`, `jarvis.state`, `jarvis.history.jsonl` and
`jarvis.facts.json` all silently resolve inside `core/`. Nothing raises. Jarvis
just boots with no API keys and no memory, which reads as "it forgot everything".

**Legacy scripts are run directly, not imported.** `legacy/` is deliberately not
a package. Each entry point carries a small bootstrap that puts the repo root on
`sys.path` so `core` resolves; sibling imports (`from voice import Voice`,
`import vondo`) work because Python already put `legacy/` on the path.

**Brains are imported lazily, never in `core/brains/__init__.py`.** Importing
them all would drag in every provider SDK, and one missing optional package
would break the entire core.

## Memory

`core/memory/` is a package: `store.py` (SQLite), `facts.py` (the notes Jarvis
keeps about Rohan), `migrate.py` (the one-time import from v1's files), and
`__init__.py` as the public face. **Callers must go through `__init__`** —
`memory.add_turn(...)`, `memory.wrap(brain)`, `memory.as_openai(...)`. That
indirection is what let flat files become SQLite without touching a brain.

- The database is `vondo.db` at the repo root, `VONDO_DB` overrides the path
  (that is how the cloud core will point at its mounted volume). Gitignored.
- WAL mode, one connection per thread — there is a reminder thread, a UI thread
  and soon a websocket loop, and sqlite3 connections are not thread-safe.
- **Nothing in the package may raise into a conversation.** Every public function
  swallows storage errors and degrades to "nothing remembered", exactly as the
  file version did. Memory failing is annoying; memory taking Jarvis down is not.
- **Retention is forever; context is trimmed.** Storage keeps everything (a few
  MB for years). `as_openai` decides how much a model sees this turn. These are
  different decisions — do not conflate them again.
- `jarvis.history.jsonl` and `jarvis.facts.json` are **frozen, not deleted**.
  Nothing writes to them. They are the way back if the database disappoints.
  A marker row in `meta` makes the import run exactly once.
- Still text only, never tool-call scaffolding — see the note in `__init__`.

**Retrieval is `core/memory/recall.py`, and the query is the whole job.** The
FTS5 index existed from phase 01 and nothing called it for months: every turn
the model saw `recent(MEMORY_TURNS)` — six exchanges — so anything older was
answered by something that had never been shown it.

Wiring it up naively would have looked like it worked and returned nothing
forever, because `store.search` hands its argument straight to FTS5 and FTS5
reads a bare word list as *all of these must appear*. "What did I say about
NILM" therefore asks for messages containing *what* AND *did* AND *I* AND
*say* — essentially never — and punctuation raises an error that is swallowed
into an empty list. So `recall` strips stopwords, drops the punctuation (which
doubles as the escaping), and joins what is left with **OR**.

Two guards keep OR from becoming noise:
- **a relevance floor.** OR returns anything with one common word in it, and
  ranking orders the results without excluding the rubbish. A hit must match two
  query terms (one, if the question was two words). A recalled irrelevance is
  worse than an empty recall — it is noise in the prompt and a lie on screen.
- **commands recall nothing.** "Open youtube" wants a tool, and searching it
  drags in every past "open calculator".

Recalled text goes in the **system prompt**, never as extra messages — injecting
old exchanges as real turns is the fastest way to build the non-alternating
history providers reject.

**Meaning-based recall is `core/memory/vectors.py`, and the floor is the load
bearing part.** FTS5 is keyword matching however carefully the query is built:
*"what did I say about power disaggregation"* shares not one content word with
the conversation about NILM that answers it, so the word floor above refuses it
— correctly, on the evidence it has. So every worthwhile exchange and every fact
also carries a Gemini embedding, and a question is compared against those by
cosine. FTS5 is not replaced; the two find different things.

- **The floor was measured, not guessed.** Gemini's embeddings sit high — two
  texts about nothing in common still score ~0.52, so "similarity above a half"
  recalls rubbish on every query. Against Rohan's real archive, true matches
  land at 0.68-0.74. Hence **0.65**. Re-measure before changing the model; do
  not nudge it because one query missed.
- **Short vague messages are attractors.** "what is", "example", "open it" mean
  almost nothing and are therefore close to almost everything — "anything about
  my schedule" pulled back "what is" at 0.62. The floor stops them, and
  `worth_embedding` keeps most out of the index in the first place. Those are
  different jobs: the filter saves the API call and the storage, the floor saves
  the precision. Only the floor is load bearing.
- **Nothing is embedded on the write path.** `add_turn` must not wait on Google
  to store a sentence, and an embedding outage must not become a memory outage.
  `backfill()` fills rows in afterwards from the sweeper and from `/tick` — the
  latter because a free instance that sleeps has no sweeper running. Facts go
  first in each batch or messages, which arrive continuously and outnumber them,
  would starve them for ever.
- **A skipped row gets an empty vector, not no row.** Otherwise every pass picks
  up the same fragments, spends the batch deciding to ignore them again, and
  never reaches anything useful.
- **The model name is stored beside the vector.** Two models' vectors are not
  comparable and mixing them produces confident nonsense rather than an error, so
  a change of model invalidates the old rows instead of poisoning the results.
- **int8, not float32** — a quarter of the size, which is what the cold start
  pays for over HTTPS to Turso. Measured against float32 on the real archive it
  returns the same rows above the floor on every query tried; worst similarity
  error 0.006.
- **A finished sweep stops sweeping.** Once everything is indexed there is
  nothing to find, and looking anyway is two full scans over the network every
  thirty seconds for ever. A pass that finds nothing waits five minutes before
  looking again — same rule as the rest of the system: nothing runs while
  nothing is happening.
- `numpy` is the one dependency this added. Hand-rolling the float maths over a
  few thousand vectors costs about a second per question, which a turn does not
  have.

**Two searches, no shared scale, so `recall` interleaves them.** Appending the
meaning hits behind the keyword hits was the first attempt and it buried the good
one: asked about "power disaggregation" the prompt led with an exchange that
merely contained "power", and pushed the conversation actually about the subject
past the character budget. bm25 and cosine measure different things in different
units, so neither list can be declared better — but each is ordered well within
itself, and a hit only one of them found is exactly the hit worth keeping.

**Searching everything is `core/memory/find.py`, and bm25 is a shortlist, not a
score.** FTS5 ranks messages against each other well and against nothing else:
its numbers are negative, corpus-dependent and unbounded, so putting one beside
"this fact contains two of your three words" gives an order that shifts as the
archive grows and cannot be explained to whoever is reading it. MATCH picks
which messages are worth looking at, its rank is discarded, and every candidate
from all six stores is scored again by one function on one scale.

**SQL is broad, Python is strict.** `LIKE '%ai%'` matches "said" and FTS5 folds
"Café" to "cafe" — both fine, because nothing is returned on the strength of a
SQL match. The scorer re-checks each candidate on folded, word-boundary terms,
so the stores cannot disagree about what matched. A zero score means SQL found
it and the scorer did not agree, and those are dropped: a search that returns
rubbish is worse than one that returns nothing, because you stop trusting the
good results too.

**`clock.was`, not `clock.say`, for anything from the archive.** `say` is
written for things that have not happened, so it renders a sentence spoken this
morning as "later today at 3pm", which reads as Jarvis losing track of which way
time runs.

**Every brain must build its prompt through `memory.system_prompt(text)`, and
two of them were not.** Claude passed the module-level `SYSTEM_PROMPT` — the
persona alone, no facts, no diary, no tasks, no contacts, no recall — so the
*paid* brain knew Jarvis's manner and nothing whatever about Rohan. Ollama
called `system_prompt()` with no argument, which keeps the facts and the date
but silently drops the recall block, since that is built from what was just
said. Both are the same bug recorded below for Gemini, and both survived because
neither brain is exercised in normal use. `test_server.py` section 10 now reads
the source of all three, because a brain that needs an unavailable SDK or a
paid key cannot be tested any other way — and the untestable one is exactly
where a regression hides.
Groq rebuilds it per turn. Gemini did not: `system_instruction` is fixed when
the chat is created, and it was built from `config.system_prompt()` — the
persona *without* facts, diary, date or recall. So Gemini knew Jarvis's manner
and nothing whatever about Rohan, and since Gemini is what answers when Groq's
free tier runs out, running out looked exactly like Jarvis forgetting
everything. It prepends the prompt to each message instead, because the SDK will
not let a live chat's system instruction change and rebuilding the chat would
throw away its history.

**Known gap:** the action log is written by wrapping `DISPATCH` in
`core/tools/llm_tools.py`. That covers Groq and Ollama and **not** the other
three, which is wider than this note used to claim: Gemini calls
`TOOL_FUNCTIONS` directly (its schema generator introspects each callable, so
wrapping those risks emitting `(*args, **kwargs)` schemas), Claude declares its
own `@beta_tool` functions and bypasses `DISPATCH` entirely, and `FreeBrain`
calls `actions.*` in most branches. So three brains of five leave no trace of
what they did. Close it in each brain's own call path, not by wrapping harder.

## The cloud core (phase 02)

`server/` is FastAPI in front of the same brains, memory and tools. `app.py`
(routes), `auth.py` (pairing and tokens), `agents.py` (the link to the PC).

```
python -m uvicorn server.app:app --reload --port 8000
python tests/test_server.py      # 34 checks, real server, real sockets, temp DB
```

**Brains block, so every turn runs in a worker thread** (`run_in_threadpool`)
behind an `asyncio.Lock`. Calling a brain directly in an async endpoint would
freeze the event loop — including the websocket carrying the PC agent. The lock
also matches what the single shared conversation history already assumes.

**PC routing lives in `core/lazy.py`, not in the tool dispatcher.** This matters:
the AI brains reach the desktop through `llm_tools.DISPATCH`, but the rule-based
`FreeBrain` calls `actions.open_app(...)` directly. Hooking the dispatcher alone
covered the AI brains and silently missed the offline one — the brain most
likely to be answering when everything else has failed. `core.lazy` sits under
both and cannot be bypassed. `PC_FUNCTIONS` there is the single list of what
needs the desktop; do not keep a second copy anywhere.

**A missing PC is answered, not waited for.** No agent connected means an
immediate spoken sentence, never a hung conversation. Rohan chose that.

**Signing in is a four-digit PIN**, and the PIN is the whole story — there is no
pairing flow any more. It is typed once per device and exchanged for a
long-lived token; tokens are stored as hashes only.

Four digits is 10,000 combinations on a public URL, so the throttle is not
optional: five wrong tries locks that **address** for fifteen minutes, and every
attempt pays a fixed delay whether it is right or wrong (a delay only on failure
tells an attacker which guesses were warm). The lockout must stay per-address —
a global one lets anyone lock Rohan out by guessing badly on purpose. Behind a
proxy that means reading the forwarded address, or every visitor shares one
bucket.

**"Streaming" is events, not tokens.** Brains return finished strings today, so
the websocket reports status (`thinking`) and then one `reply`. The frame format
already has a `token` type so real streaming needs no protocol change. Do not
fake it by chunking a finished string.

## The PC agent (phase 03)

`agent/` is the only VONDO process on Rohan's machine and must stay small:
`agent.py` (the loop), `guard.py` (what it will do), `pair.py` (one-time setup),
`settings.py`. Four dependencies, no AI, no models, no speech, no window. If
something here starts needing a heavyweight package, the work belongs in the
cloud instead.

```
link_pc.bat        # once — type your PIN
start_agent.bat    # run it
python tests/test_agent.py    # 17 checks, real agent, real server, temp everything
```

**The allow-list is imported, never retyped.** `guard.ALLOWED` *is*
`core.lazy.PC_FUNCTIONS`. Two copies drift into "the server can ask for
something the agent forgot about". It is an allow-list on purpose: a block-list
would have to anticipate every dangerous thing, this has to anticipate nothing.

**Remote control is the one capability the allow-list cannot protect, so it
has its own gate.** `screen_frame` / `screen_size` / `screen_input` in
`core/actions.py` give the phone the PC's screen and its mouse and keyboard.
Rohan asked for that knowing the trade: a cursor is every action at once, so an
allow-list of named functions means nothing when one of them is "click here",
and a per-action dialog would ask fifty times a minute. So `guard.py` asks
**once per run of the agent, for the whole capability** — and remembers a *no*
as firmly as a yes, because a gate that re-asks is one that gets clicked
through. Restarting the agent is what re-opens the question. Watching is not
driving: `screen_frame` is read-only and no more revealing than
`take_screenshot`, which has never asked, so only input is gated.

**Frames are pulled, never pushed.** The viewer asks for the next one when it
has drawn the last. That is what makes closing the sheet sufficient to stop
everything — no timer on the PC, no subscription on the server, nothing to
remember to cancel — and a slow link produces fewer frames rather than a queue
that grows. Same rule as everywhere else: nothing runs while nothing is
happening.

**Coordinates travel as fractions of the screen**, so the phone never needs to
know the PC's resolution and a frame scaled down for the wire still points at
the right pixel. `width` and `quality` are clamped in `screen_frame` rather than
trusted — they arrive from a phone over the internet, and a 30,000-pixel request
is a way to make the desktop spend a minute on one call.

**pyautogui's corner failsafe is left ON deliberately.** It is the only physical
override: shove the real mouse into a corner and the next remote action raises
instead of landing. For a feature that hands a phone the keyboard, an escape
hatch needing no software is worth the rare misfire of a genuine click at the
very top-left.

**Every remote click is written to the action log.** "What did it do while I was
not looking" needs an answer for this most of all.

**Destructive actions ask again, here.** Shutdown, restart and force-closing a
named app pop a `MessageBoxTimeoutW` on the desk (30s, "No" focused, timeout
means no). The cloud's confirm gate is code on a server; if that server were
compromised it is exactly as trustworthy as the thing that failed. Closing the
*front* window is exempt — that is a polite WM_CLOSE and still prompts to save.
If `MessageBoxTimeoutW` were ever missing we refuse rather than risk a dialog
that hangs forever on an unattended machine.

**A websocket must be REFUSED at the handshake, never accepted and then
closed.** `socket_caller` runs before `accept()` for exactly one reason: closing
an un-accepted socket refuses the upgrade, so the client sees HTTP 403 and its
own "not authorised" branch fires. Accepting first and closing after looks, from
the far end, like a healthy connection that dropped — indistinguishable from a
flaky network. That is what it did, and the PC agent sat in a reconnect loop
printing "connection closed; reconnecting" every ten seconds with a dead token,
never once reaching the line that says *sign in again*. The symptom read as an
unstable connection and was an expired credential.

The agent treats close codes **4401, 4403 and 1008** as terminal for the same
reason, as belt and braces: if anything in between turns the refusal into an
ordinary close, it still stops rather than re-asking a rejected question every
few seconds for ever.

**Stopping cleanly is a feature, not tidiness.** `request_stop()` closes the
websocket so the cloud marks the PC offline *at once*. Killing the process
leaves the socket half-open, and until TCP notices, "open chrome" from the phone
waits out a timeout instead of saying the PC is asleep. The reconnect backoff
waits on the stop event too, or quitting during a 60-second backoff hangs.

**The token lives in `agent.token`, not `.env`.** `.env` is the file Rohan
opens, edits and occasionally screenshots. A long-lived credential does not
belong in the middle of that. Gitignored; `VONDO_AGENT_TOKEN_FILE` overrides it
for tests.

## The diary (phase 05)

`core/clock.py` reads a date out of a phrase, `core/memory/agenda.py` stores it,
`core/reminders.py` announces it on the desktop, `server/nudges.py` delivers it
in the cloud, `web/src/lib/notify.ts` mirrors it onto the phone.

```
python tests/test_reminders.py    # 45 checks, real server, real socket, temp DB
```

**A task is not a reminder, and that is why there are two tables.** The diary
holds what happens at a time; `core/memory/tasks.py` holds what has to get
done. A task has no required date and does have a finished state — those two
differences are the whole distinction. Without it, "write the methodology"
either became a reminder at an invented hour or was lost, and "what should I
work on now?" had nothing to answer from.

**`source` is what stops follow-through becoming nagging.** `asked` is a task
Rohan put on the list; `noticed` is one Jarvis inferred from "I'll finish the
draft tonight". Only `noticed` ones get chased, once, two days later, in the
briefing — and `asked_at` is what makes it once. Chasing the same commitment
every morning is how a helpful assistant becomes a thing you close. Something
explicitly put on the list does not need chasing; it needs doing.

**Open tasks sort by deadline before priority.** A normal thing due tomorrow
beats an important thing with no date, because the deadline is the part that
stops being possible. A due of 0 means none and must sort last, not first.

**Finished, never deleted.** What got done is worth knowing, and it is what the
weekly look back is built on — see below.

**Parsing happens in Python, not in the model.** Asking a brain for an ISO
timestamp is tempting and unreliable — it invents the year, forgets the
timezone, and the rule-based brain cannot do it at all. The `remind` tool takes
the phrase Rohan actually said and `clock.parse_when` turns it into an epoch, so
every brain gets the same dates for free.

**Dates are built in Rohan's timezone and stored as epochs.** The core runs in
UTC in Singapore; "18 September" means the 18th in Dhaka. `VONDO_TZ` names the
zone, `VONDO_UTC_OFFSET` is the fallback for platforms with no tz database
(Windows). Getting this wrong shifts every reminder by six hours.

**`due` and `remind_at` are different columns on purpose.** An exam warning
delivered as the invigilator hands out papers is not a warning. `all_day` is a
third: "18 September" names no hour, and inventing nine in the morning and
reading it back confidently is how you stop trusting the thing.

**A repeating thing is ONE row that moves forward**, never one row per
occurrence. `mark_fired` advances `due` to the next occurrence and clears
`fired` instead of ending it; only a one-off finishes. A term of weekly classes
as fifty rows would all need rewriting the moment the timetable changed, and the
fiftieth would arrive after the term. The lead time is preserved across the
move, so "warn me an hour before" keeps its hour.

**A reminder is marked delivered only if somebody was actually told.** The
sweeper broadcasts to open sockets and marks `fired` per successful send. A free
tier waking at some arbitrary moment with nobody connected must not consume the
exam warning and go back to sleep — it waits, and arrives when the app opens.
`test_reminders.py` section 8 is exactly this regression. The desktop's
`sweep()` still marks immediately, because speaking out loud *is* delivery.

**A closed PWA is reached by Web Push and nothing else.** It has no process, no
alarms and no way to wake itself, so without push a reminder can only arrive
while the tab is already open — which is exactly when you least need telling.
`server/push.py` needs **no Firebase and no account**: the VAPID pair is
generated on first use and kept in `settings`, and the browser hands out its own
endpoint. Never rotate those keys casually — every existing subscription is
signed against that exact public key.

The service worker acknowledges the notification it actually *showed*, via
`/push/seen`. Same rule as the socket: a push the service accepted is not a
push a person saw, and nothing is marked delivered on the strength of a send.

**Phones schedule their own alarms.** `notify.ts` mirrors the diary into
Capacitor local notifications, so the OS fires them with the app closed, the
phone offline and the server asleep. Push was the obvious answer and the wrong
one: the APK is a WebView, where the Web Push API does not exist, and the native
route is Firebase — an account, a project, and a Google dependency in something
that deliberately has none. The cloud stays the source of truth; the phone keeps
a cache with a clock.

**`/tick` is unauthenticated and must stay harmless.** No arguments, no output
but counts, and it does exactly what the server does by itself every thirty
seconds. It exists because a sleeping instance has no timers.

**Adding a column to `reminders` needs `_LATER_COLUMNS` in `store.py`.**
`CREATE TABLE IF NOT EXISTS` does nothing to a table that already exists, so the
schema string and a live database drift apart silently — and the drift only
shows up on the deployed copy.

## Voice and vision (phase 06)

`core/ears.py` turns a recorded clip into words (Groq Whisper); `core/eyes.py`
turns a picture into a description (Gemini). Both are on the keys that already
run the brains — no new account.

**Neither answers the question it received.** `/listen` returns the transcript
and `/look` returns a description; acting on either is a separate step, so what
was heard or seen can be shown before it is obeyed. A misheard "shut down the
PC" must be visible, not executed.

**Kept out of the brains on purpose.** A brain holds a running conversation with
the whole tool schema bound to it; a glance at an image or a few seconds of
audio is a single stateless call with no tools and no history. Binding them
together would drag every tool into every photo.

**Whisper hallucinates on silence** — trained on subtitled video, it fills a
quiet clip with "thank you", "the end", a credit line. `ears._is_hallucination`
drops a clip that is *only* one of those or only punctuation. Real one-word
answers (ok, so, yes, no) are deliberately left through: eating a real answer is
worse than fielding a stray one.

**Vision is comprehension, not recognition.** It reads what is in the frame; it
does not identify strangers, which needs a face database nobody has and would
not be built. `eyes.look` records the *description* in memory, never the image —
so "what did that error say" is answerable later without storing the picture.

**Speaking back uses the browser, listening does not.** `speechSynthesis` is the
half of the Web Speech API the Android WebView reliably has; `SpeechRecognition`
is not, which is why audio is recorded and sent to Whisper rather than
recognised on-device. A mic that worked in Chrome and not in the app would be
worse than one that behaves the same everywhere.

**Waking to your voice is `web/src/lib/listen.ts`, and it reverses a rule on
purpose.** `voice.ts` avoids `SpeechRecognition` because the Capacitor WebView
usually lacks it, and a mic that worked in the browser and not in the app would
be worse than one that behaved the same everywhere. That reasoning was right and
stopped applying: the app is an installed PWA in Chrome now. Tap-to-talk is
unchanged and is the fallback wherever the API is missing.

It also *has* to be the browser's recogniser. Always-on listening through
Whisper means uploading every utterance in the room — the free tier would be
gone by lunchtime, and most of what it paid for was somebody else's
conversation.

- **The matcher is `wakeword.ts`, which imports nothing.** That is what lets
  `tests/test_wakeword.mjs` compile it alone with tsc and check it in node — no
  browser, no test framework, no new dependency. 35 checks.
- **The failure mode is waking when it should not.** A missed wake word is
  mildly annoying; a false one takes a sentence said to somebody else and hands
  it to something that can open applications. English contains "service" and
  "harvest", both plausible and both offered by a recogniser that is unsure —
  four edits away, so a tolerance of **two** keeps them out while still catching
  jervis, javis, jarvus, harvis, darvis. The twelve words it must refuse are
  pinned in the test; widening the tolerance means going through that file.
- **The command is the rest of the same breath.** "Jarvis, what's on today" is
  one utterance. Waiting for the next one drops half of what anybody says.
- **Nothing is kept unless you woke it.** An utterance without the wake word is
  matched, discarded, and never leaves the browser. Only the shape of a *near
  miss* is kept — one word, in memory — so the tolerance can be widened from
  what a recogniser really produces for this voice rather than from a list
  somebody imagined.
- **`onend` must restart it.** Android ends the session after every utterance
  whatever `continuous` says. Without the restart the wake word works exactly
  once per page load, which is worse than not having it.
- **It is deaf while Jarvis speaks.** Left running it transcribes the reply, and
  a reply containing the word "Jarvis" wakes it again — a loop that is hard to
  get out of. The consequence is that voice barge-in does not work; tapping
  still cancels.
- **Off by default, and stopped when the tab is hidden.** A microphone that
  switches itself on because an app was opened is not a feature, and an
  always-on mic is the most expensive thing this app can do.

**Two native permissions gate this, and only a new APK carries them:**
`RECORD_AUDIO` for the mic and `CAMERA` for `capture="environment"`. Screens
update from the cloud; permissions live in the manifest. Adding either is one of
the rare times a reinstall is genuinely required.

## The phone as a device, not just a screen (phase 07)

`core/phone.py` opens things on the phone in your hand. It exists because "my
PC is off" had exactly one answer before, and that answer was no.

**The fallback rule: PC first, phone second, refuse last.** `_pc_then_phone` in
both `llm_tools` and `brain_free` tries the desktop, and hands the job to the
phone when there is no desktop. A big screen is usually what "open YouTube"
means, so the PC still wins when it is awake.

But this only applies where the phone has a real second answer. **Reading the
PC's CPU has none** — there is one PC, it is asleep, and inventing a number
would be worse than saying so. `test_server.py` section 5 pins both halves:
opening falls back, reading does not.

**Android will not let one app drive another, and nothing here pretends
otherwise.** No reading another app's screen, no tapping its buttons, no reading
notifications. What an app *can* do is hand something off — a URL, a number, a
map reference, a pre-filled message — and that is the whole module.

**People live in `core/memory/contacts.py`, not in the facts.** A number was a
sentence — "Rohan's dad's number is +8801…" — so "call dad" depended on a model
finding the right sentence among dozens and reading the digits out of it
correctly, every time, with no way to tell whether it had. A number is
structured data and belongs in a column.

The system prompt carries the **names only**, never the numbers: the model has
to know who exists so it can say "I have no number for Rifat" instead of
inventing one, and the tool fetches the number at the moment it dials. Shipping
a dozen numbers into every turn is both wasteful and the easiest way for one to
end up somewhere it should not be.

**`wa.me` refuses a local number.** It opens nothing at all for "01812999888" —
silently, which looks exactly like the app being broken — so `_international`
converts at the point of use. Only there: the dialler is happy with the local
form, and rewriting what Rohan typed would make it unrecognisable read back.
`VONDO_COUNTRY_CODE` is the same fact `VONDO_TZ` already carries, in the form a
phone number needs.

**Nothing is sent or dialled automatically.** `call` opens the dialler with the
number in it; `message` opens WhatsApp with the text typed. The last tap stays
with the person whose name is on it, because a misheard sentence that places a
call is not a mistake you can take back.

**The instruction rides on the reply.** The brain runs in the cloud and cannot
open anything, so a tool leaves a URL in `phone._pending` and `_answer` attaches
it to the reply frame — taken *inside* the brain lock, so it can only belong to
the turn that just finished. The client opens it with `window.open(url,
"_system")`, which is what makes Capacitor hand it to Android instead of loading
it in the WebView.

**No new plugin, so no new APK.** Capacitor already routes unknown schemes to
the OS. That was worth checking before adding a dependency.

## The brain chain

`factory.build()` assembles **every** brain that will start, tried in turn,
ending at the offline one. `groq -> gemini -> free` by default.

**A named brain goes first; it does not go alone.** `VONDO_BRAIN=groq` used to
build `groq+free` and silently drop Gemini — so a Groq outage, or a model
retired from under it, fell straight past a perfectly good second brain to the
rule-based one, which answers but cannot think. That reads as Jarvis having a
bad day rather than as a chain with a hole in it, which is why it went unnoticed
for so long.

**Availability is decided by trying, not by asking.** A key that is present but
wrong, a package that is missing, a model that was withdrawn — all of those look
fine to a config check and fail at the first question.

**The chain is built back to front** so the offline brain is everyone's last
resort rather than only the last one's.

Failure puts a brain on cooldown (5 min ordinary, 30 min for quota) so a dead
free tier is not re-paid on every question — see `brain_fallback.py`.

## Getting the data out (phase 09)

`core/memory/backup.py`. Until this existed there was no export and no second
copy anywhere: every conversation, the diary and everybody's phone number lived
in one hosted database, with `jarvis.history.jsonl` frozen at the migration as
the only fallback.

**Plain JSON, not a database dump.** It has to be readable in ten years by
something that is not this program, and readable by Rohan — he should be able
to open the file and see his own sentences.

**Restore merges and never deletes.** A restore that wipes the present to
recover the past is a worse accident than the one it is fixing. Rows are
matched on content, never on id: ids are assigned by whichever database wrote
them and mean nothing across a restore. Running it twice adds nothing.

**Devices and push subscriptions are deliberately excluded.** They are
credentials for specific browsers, useless anywhere else, and a backup is a
thing people email to themselves. `test_reminders.py` section 8c checks that
they are absent rather than trusting it.

## The week, looked back on (phase 10)

`core/weekly.py` answers "what has actually been happening", which is the
question you cannot answer for yourself — a week is exactly long enough to
misremember and short enough to feel certain about. `/weekly` serves it,
`web/src/hud/Weekly.tsx` shows it under the briefing, `my_week` is the tool.

**Every figure is counted, never estimated.** Tasks finished, tasks added, what
is still open, how much was said — all of it is `SELECT COUNT(*)` over rows that
already exist. That is what makes it safe to sit on the board beside the gauges,
which follow the same rule.

**The closing observation is arithmetic, not a model.** Six added against two
finished says the list is growing; anything overdue says do those first. Every
line it can produce is something the numbers beside it already show, so it can be
argued with. A model asked to comment on someone's week will eventually
congratulate them on a bad one, and a report that flatters is a report you stop
reading. It also means the whole thing works with every free tier exhausted,
which is the same reason `brief.py` is composed rather than generated.

**Topics are a word count over Rohan's own messages.** Never the replies:
counting both ranks the assistant's vocabulary, and "reminder" would come top of
every week. Counted once per message, so saying "NILM" six times in one sentence
is one mention. This is the whole of the "learn from my data" idea that is worth
having — the expensive part of an assistant should be the reasoning, never the
remembering.

**Weekly means weekly.** `is_new_week` compares ISO weeks in Rohan's timezone
rather than counting elapsed days, so it lands on the same day each week instead
of drifting an hour later every time. The seen-marker is per device, like the
briefing's: reading it on the phone must not silence it on the desktop.

**A quiet week says nothing at all**, rather than rendering a page of zeroes.
Same rule as the briefing and the board.

**The offline brain answers it too**, and matches tightly — `"what have I got on
this week"` is a question about the diary and must not be answered with a look
back. A rule-based brain's failure mode is a wrong answer delivered confidently.

## Papers and notes (phase 11)

`core/documents.py` reads a PDF or a text file, cuts it into passages and hands
them to `core/memory/vectors.py`. It exists because everything Jarvis knew came
out of a conversation, so the actual work — the papers, the drafts, the notes —
lived in folders it could not see, and the one thing a research assistant ought
to be good at was the one thing it could not do.

```
python tests/test_reminders.py    # section 12 covers this
```

**Passages, not documents, and that is the whole trick.** One vector for a
forty-page paper is a vector for nothing in particular: the average of the
abstract, the method and the references, close to every query and useful for
none. A paragraph has one subject, so its vector points somewhere.

**Split on paragraphs, then sentences, then give up.** A fixed character count
is easier and produces chunks that begin mid-clause, which embed as badly as
they read. Consecutive passages overlap by ~140 characters so a fact sitting on
a boundary is whole in at least one of them.

**`clean` must keep the blank lines.** It drops running heads, page numbers and
column fragments — furniture that matches nothing and dilutes the chunk it sits
in — and the first version dropped the paragraph breaks along with them, because
a blank line fails the same "is this a sentence" test. The result was one
unbroken wall of text and therefore one chunk per document, which is exactly the
thing the chunking exists to prevent. It looked like it worked.

**A scan must be refused out loud.** A scanned PDF is photographs of pages with
no text layer, so extraction returns nothing. Storing an empty document and
reporting success is the worst outcome available: the paper looks filed, and the
first search for it reads as the search being broken rather than the filing.

**Nothing is embedded on upload** — same rule as everything else — but `/documents`
calls `catch_up(force=True)` straight afterwards, because a paper you have just
handed over and cannot find yet reads as the filing having failed.

**Passages come after facts and before messages in each backfill batch.** A
document was put there deliberately and is useless until searchable; messages
accumulate on their own and one arriving a few minutes late is invisible.

**Batches are sized by characters, and the size is discovered.** `BATCH = 24`
conversation turns is a few thousand characters; 24 document passages is twenty
thousand, and the free embedding tier is metered on *content* — measured, a
single-word request succeeds in the same minute a seven-thousand-character one
is refused. So a refused batch is halved and retried rather than abandoned: a
refusal for being too large and a refusal for having nothing left look identical
from here, and treating the first as the second stalls the whole archive until
somebody notices. It stops halving at one row, because one passage cannot be
made smaller and further refusals buy nothing.

**Two floors, for two different costs of being wrong.** Automatic recall puts
what it finds into the prompt unbidden, so a marginal hit is noise nobody asked
for — that stays at `FLOOR`. An explicit `search_papers` is the opposite: it was
asked for, the answer names the document, and a near miss can be read and
dismissed in a second. `ASKED_FLOOR` is lower for that reason. **The passage
number is provisional** — it was set by argument, not by measurement, because
the embedding quota ran out before it could be measured on real passages. Measure
it before trusting it, the way `FLOOR` was.

**A search for one kind must narrow before ranking, not after.** Asking for the
best five of everything and keeping the passages returns nothing on a real
archive, where messages outnumber passages many times over: the good passage is
real, ranked eleventh, and never looked at. `vectors.search(kinds=...)`.

**The embedding quota is per-minute and it is real.** A burst of filing will
exhaust it, and `vectors.blocked()` says so in plain words which `/documents`
returns and the HUD prints. A backlog with no explanation reads as a fault; this
one fixes itself. A refused pass waits ten minutes rather than five — but not
`brain_fallback`'s thirty, because that cooldown is for a *daily* model quota and
this limit was observed recovering within a minute or two.

**`find.py` scores the whole passage and shows the part that matched.**
Truncating to `SNIP` before scoring was the same asymmetry the module exists to
prevent, pointing the other way: SQL matched the full passage, the scorer saw
the first 160 characters, and any hit whose match sat further in was found and
then silently discarded. With 900-character passages that was most of every one
of them.

**Forgetting takes the vectors too.** SQLite reuses `INTEGER PRIMARY KEY` values
after a delete, so a vector outliving its passage would eventually be matched
against a different document's text.

## Mail (phase 08)

`core/mail.py` reads Rohan's inboxes over IMAP. Standard library only —
`imaplib` and `email` — so no new dependency and no new account.

**IMAP with app passwords, not the Gmail API.** The official route is OAuth,
which for an app Google has not verified hands out refresh tokens that expire
every seven days. An assistant that stops working every Sunday is not one. An
app password never expires, is one string, and the same code reaches any
provider.

**Read-only is enforced, not intended.** `select(..., readonly=True)` and
`BODY.PEEK` on every fetch — PEEK being the form that does not set `\Seen`, so
deciding whether a message matters cannot mark it read. No `store`, `copy`,
`expunge` or `append` call exists in the module. The credential could do all of
those; the code cannot.

**Priority is rules, not a model.** Scoring is over headers — sent to you or to
a list, sender known from the facts, subject about a deadline, how old. That
makes it free to run all day and, more importantly, makes the reasoning
printable next to the result. `Message.why` carries it, and the HUD shows it: a
ranking whose reasoning you cannot see is one you re-check, at which point it
has saved nothing.

**Nothing is stored.** No body reaches the database. Mail is fetched, ranked,
shown and forgotten — the mail server is already the archive.

**One bad mailbox must not lose the rest.** Each account is fetched inside its
own try/except and a failure is logged and skipped, so a wrong password on the
second account does not hide the first.

**Timeouts matter more than they look.** IMAP over a poor connection can hang
for minutes and a turn cannot. `socket.setdefaulttimeout` is set around the
fetch and restored afterwards.

## What Jarvis costs when nobody is using it

"Lightweight" was a stated requirement and it is the easiest one to lose by
accident, so the rule is: **nothing runs while nothing is happening.**

- **A waiting reminder costs nothing.** The phone's own alarm clock holds it,
  exactly as it holds an alarm. Jarvis is not running, not polling, and holds no
  connection. This is the real reason local notifications beat push here, ahead
  of avoiding Firebase.
- **`allowWhileIdle` is why no exemption is needed.** It maps to
  `setExactAndAllowWhileIdle`, the API Android provides so an alarm fires during
  Doze without a battery-optimisation exemption. **Never tell Rohan to disable
  battery optimisation** — it trades real battery life for a problem that is
  almost always somewhere else. A diagnostic that suggests it is a bad
  diagnostic.
- **The reactor stops when the tab is hidden**, and so does the board's clock —
  a timer nobody can see is pure waste.
- **The websocket exists only while the app is open.** Nothing reconnects in the
  background.

## The HUD (phase 04)

`web/` is Vite + React + TypeScript, built to `web/dist` and served by the cloud
core at `/`. One origin, so no CORS and the token never crosses an origin.

**Home is the board, not the conversation.** `screens/Dashboard.tsx` — what is
coming up, the PC's gauges, what is remembered, which brain is answering.
Chat is `hud/ChatSheet.tsx`, a full-screen drawer behind the floating button;
settings is a second drawer behind the gear. The socket is held by `App.tsx`
above all three, so opening or closing a drawer never drops the connection or
loses the log.

**Nothing on the board is estimated.** A reading that has not arrived draws as a
dash, never as zero — zero is a reading and nothing is not, and an invented
figure rendered as a precise gauge makes the true numbers beside it
untrustworthy. If a panel would need data nothing collects, the panel does not
exist yet.

```
cd web && npm run build          # then the core serves it at /
cd web && npm run dev            # port 5173, proxies the API to :8000
python tests/test_hud.py         # 15 checks: built, served, assets resolve
start_hud.bat                    # its own window, no address bar
```

**The reactor runs outside React.** `hud/reactorEngine.ts` owns a canvas and one
`requestAnimationFrame` loop; `hud/Reactor.tsx` only owns the element's
lifetime. State and mic level reach the loop through a mutable ref, not props —
passing them as props would tear down and restart the animation every time
Jarvis started thinking, and the rings would snap back to zero.

Three rules the loop keeps, because "lightweight" was a stated requirement:
one canvas and one frame (not a frame per ring); nothing at all while the tab is
hidden; and idle motion slow enough to read as switched-on from the corner of
your eye without pulling it, since this may sit on a second monitor.

**Everything is a token in `theme.css`.** No hex values in components — that is
what makes the KAREN palette a second `[data-theme]` block rather than a rewrite.

**`reactorEngine.ts`, not `reactor.ts`.** It sat beside `Reactor.tsx` and the two
differed only in casing, which Windows resolves ambiguously and Linux resolves
differently — a bug that would only have appeared on Fly.

**The shell is sized from `visualViewport`, not `100%` or `100vh`.** Both of
those measure the *window*, and on Android the window does not shrink when the
keyboard opens — it is drawn over the top. `lib/viewport.ts` puts the real
height in `--app-height` and a `keyboard-up` class on `<html>`. Without it the
composer sits behind the keyboard: you tap the box and it disappears. Any
full-height layout added later must use the variable.

Keyboard detection compares against the tallest viewport ever seen, not against
`window.innerHeight`: the manifest asks for `adjustResize`, so the window
shrinks along with the viewport and the difference between them is always zero.

**Grid rows on a phone must be explicit.** Left on `auto`, a log grows with
every message until it pushes whatever is below it off the bottom of the screen.
`1fr auto` in `.chat-sheet` is what pins the composer.

**A count and a list do not share a panel.** Settings had the exchange count
and the remembered-facts list in one box, so the box grew with the list and
pushed notifications, the voice picker, the PC and the sign-out button off the
bottom of a phone. `hud/Remembered.tsx` is its own section, folded to three with
the total on the outside — the number is what you want at a glance, the
sentences only when you have come to change one.

**Every signed-in device can be revoked from the screen** (`hud/Devices.tsx`).
The endpoint existed from phase 02 and nothing called it, so each re-added PWA
left a live long-lived token that could only be killed in the database. It asks
twice in place rather than opening a dialog, and it will not revoke the device
you are holding — that is what Sign out is for. `revoked` is SQLite's integer,
not a boolean; typing it as one in TypeScript compiles and is wrong.

**Adding that button made the device NAMES a problem.** Every sign-in
registered as literally `"phone"` or `"desktop"`, which was harmless while the
list was read-only and dangerous the moment it had a button: three rows called
"phone" and no way to know which one you are signing out. Three answers, and the
third is the one that always works — new sign-ins carry browser and platform
(`deviceName` in `lib/store.ts`, deliberately coarse: more precision would not
help a person choose a row and is a fingerprint on a server), any device can be
renamed (`/devices/{id}/name`), and every row shows the day it signed in. Two
devices can share a name; they cannot share the moment they arrived.

**Watch the mount order in `app.py`.** `StaticFiles` is mounted at `/` and must
stay last; anywhere earlier it swallows `/chat` and `/health`. `test_hud.py`
checks exactly that.

**The Android app loads the HUD from the cloud, not from inside the APK.**
`capacitor.config.ts` sets `server.url`. A sideloaded APK has no update channel,
so a bundled copy of the HUD would freeze at build time and every screen change
would mean downloading and installing by hand. This makes `git push` the whole
release for the app as well as the server.

Consequences to keep in mind:
- the page's origin is the core, so **relative URLs are correct** and there is no
  CORS at all. `endpoint.ts` asks "did this page come out of the APK", not "is
  this the app" — the two stopped being the same question here.
- the origin is a real HTTPS one, so **the service worker runs in the app now**,
  which is what keeps it opening offline. It used to be skipped there.
- the bundled `dist` is still built and shipped: it is what `server.errorPath`
  shows (`offline.html`) when the cloud cannot be reached on a cold start.
- the splash is held until React mounts, because a launch now includes a network
  request. `launchAutoHide` stays **true** as the ceiling — with it off, a build
  whose JS failed to load would sit on the splash for ever.

**The service worker caches by allow-list, not by exceptions.** It was the other
way round and that was a latent bug: a list of API paths to skip silently caches
every endpoint added later. `/me` and `/agenda` arrived after it was written and
would have been served from cache for ever, so the board would show yesterday's
diary with no way to tell. Static names carry a build hash; everything else is
live data by default.

**Fonts come from Google Fonts today**, with real fallback stacks. Phase 05 must
self-host them, or an installed app with no signal loses its typography.

**Two traps in `core/memory`, both of which have already bitten:**

`core.memory.facts` resolves to a *function*, not the submodule — `__init__.py`
re-exports `facts = _facts_mod.facts`, which shadows the module of the same
name on the package. Inside the package `from core.memory import facts` still
gets the module (the rebind happens after), but from outside it does not. Reach
the module with `importlib.import_module("core.memory.facts")`.

The Turso client runs a background thread, so a **script** that opens a
connection and never closes it hangs at exit instead of finishing. Call
`conn.close()` in anything short-lived. The server is unaffected — it holds the
connection for its lifetime by design.

## Imports after the phase-00 move

| Was | Now |
|---|---|
| `import config` | `from core import config` |
| `import memory` / `confirm` / `reminders` / `actions` | `from core import ...` |
| `import llm_tools` | `from core.tools import llm_tools` |
| `from brain_groq import GroqBrain` | `from core.brains.brain_groq import GroqBrain` |

## Running it

```
python legacy/vondo.py        # v1 console assistant
start_jarvis.bat              # v1 window (pythonw, no console)
setup.bat                     # venv + requirements/legacy.txt
enable_autostart.bat          # regenerates the Startup .vbs
```

Autostart writes `%APPDATA%\...\Startup\Jarvis.vbs` with **absolute paths baked
in**. Move `legacy/jarvis_gui.py` and that file goes stale silently — rerun
`enable_autostart.bat` after any such move. It also reads `jarvis.state` first
and quits if Jarvis was powered off last time.

## Settled decisions — do not reopen

Cloud core on **Fly.io**; **web PWA** for desktop and Android; **device pairing**
with revocable per-device tokens; **SQLite** on a persistent volume; **browser
speech** with Groq Whisper as fallback; **Iron Man HUD** built on theme tokens.
Free tiers throughout, with Claude as a one-variable paid toggle.

The local Ollama model was deleted on 2026-08-26 — it had never actually been
installed, so `brain_ollama` was failing silently and the fallback chain was
stepping over it. The code stays; the model does not come back unless asked.

## Gotchas inherited from v1

- Groq's llama-3.3 sometimes malforms no-arg tool calls; `brain_groq.py` handles
  it with rollback + retry. Don't "simplify" that away.
- `memory.py` stores plain user/assistant text only, never tool-call scaffolding —
  providers shape tool calls incompatibly, and a trimmed history that orphans a
  tool result from its call gets rejected outright.
- `brain_fallback.py` puts a failed brain on a 30-minute cooldown. Without it,
  every question re-pays a dead brain's timeout (13s vs 0.8s).
- The mic is a DroidCam phone with a noise floor near 18, so `Voice.MIN_ENERGY`
  is floored at 120. STT uses `en-IN`.

# Red: what to do next

Updated 2026-11-13 (fifth plan). The first three plans are done, and most of the fourth: see "Done so
far", `git log` and progress.md. On 2026-11-13 the user changed Red's aim from a voice assistant to a
**companion for the laptop**. This plan follows from that.

Read this first, then AGENTS.md. Do the tasks in order. Each task lists the files and how to check it.
After finishing a task: run the tests, commit (several small commits), push to main, restart the hidden Red
(`python -m red stop` then `python -m red background`), and tick it off here.

**If your usage limit is near (90%), read "Usage limit" in the Rules first.**

## The goal

**Red is a companion for your Windows laptop, not a business assistant.** It's a friend with a
personality who lives on the PC. You talk to it (or type), and it talks back like a person: casual, warm
and funny, with opinions. It remembers you, does your work (apps, files, mail, code), grows through
plugins, and later sits on the desktop as a character you can see. The main job is a companion you can
talk to in between your work. Doing things is how it helps.

- **Personality first.** Never corporate, never "How can I assist you". Dry humour, reactions,
  opinions, short replies unless you want more.
- **It says hello, it doesn't brief you.** Red may greet you ("Morning!", "Hey, you're back").
  It does **not** read out meetings, mail or to-dos on its own, and it doesn't nag. It tells you
  about those only when you ask. The only reminders it speaks are ones you set yourself
  ("remind me at 5 to call Mom").
- **Any Windows PC:** from a laptop with no GPU to one with an 8 GB+ GPU (RTX 3050, 4050 and so on).
- **English only.**
- **Local and free:** the AI model, speech-to-text, voice, wake word, memory and screen reading all
  run on the PC with no account needed. The only exceptions are optional sign-ins the user chooses:
  Google for mail and calendar, and app plugins such as Spotify or other mail (B3).

Speed, measured from when you stop talking (the `Timing` lines in `red.log`):

| Request | Target |
|---|---|
| "open Edge", "volume up", "pause", "lock" | done in about 1–3 s |
| "play Believer" | playing in about 2–3 s |
| a question or chat | Red starts talking in about 1–2 s |
| a real job ("write me a script that…", "draft a mail to…") | something visible within 2 s (the chat window starts filling), then as long as the job needs |

**Not doing:**
- smart home
- other languages
- Mac or Linux
- cloud AI models
- big models that run partly on the CPU (gpt-oss-20b, Qwen3.5-35B-A3B), which are too slow
- morning briefings, meeting alerts, or anything Red says unasked apart from a greeting and the
  reminders you set
- a business or "professional assistant" tone

## Compared with others

The user compared Red with OpenJarvis (Stanford's open-source local-AI framework, Apache 2.0) on
2026-11-13. The rule: **take ideas, not code.** Write Red's own version of an idea; don't copy files.

| | Where they lead | Where Red wins |
|---|---|---|
| **OpenJarvis** | Long-term memory (a profile plus facts saved in the background), plugins ("skills", MCP), a chat window, a one-line installer, auto-start with restart on crash | No personality, no wake word, no PC control (just a raw `shell_exec`), no desktop character; it's a framework for developers, not a friend |
| **Desktop Mate** | Charm: a cute character on the desktop | No brains, no PC control |
| **Copilot / Siri** | Pre-installed, polished | Corporate tone, cloud |
| **Braina, VoiceAttack, PyGPT** | Plugins, macros, reliable triggers | Paid, rigid or a workbench; none of them is a companion |

Red's edge: **personality + memory + PC control + a face**, all local.

## Done so far

- **Plans 1–3** (2026-11-08 to 11-12): the voice loop, ~50 PC tools, fast path, streamed speech,
  Gmail and Calendar, voice match, several commands per sentence, Kokoro, "open YouTube", the right song,
  `notify_when_done`, the Red app wizard (`red/app/`), Red's own SearXNG. Details: progress.md 7.
- **Fourth plan** (2026-11-13):
  - Clean-up: stale handoff docs, worktrees and merged branches gone. `cache\voice-samples` and
    `cache\train_hey_red` kept.
  - Wake word steps 1–3: `red wake-test --record/--replay` (waiting for the user to record), "Wake
    skip:" lines for every guard, and "Hey Red, open YouTube" in one breath. The rest is task C1.
  - On whenever the PC is on: Ollama answers in **2.4–4.9 s instead of 19.7–21.6 s**
    (`OLLAMA_VULKAN=0` with NVIDIA, the GPU library remembered and pinned); `Startup:` lines show
    "Hey Red" live **9.4 s** after start and the model warm at **18.3 s**; the watchdog in `red hotkey`
    starts a crashed Red again (at most 3 times an hour). **Left: a reboot test by the user.**
  - Laugh clips removed and the laugh line dropped from `CHAT_SYSTEM`.

## Tasks, in order (fifth plan, 2026-11-13)

**Ship every commit to `main` on its own** (many small commits, each pushed right away).

### Two sessions at once (from 2026-11-13)

Two coding sessions run at the same time. Stay in your lane:

| | Session 1: wake word | Session 2: companion |
|---|---|---|
| Works in | `D:\RED\red`, on `main` | the worktree `D:\RED\worktrees\companion` (branch `companion`), pushing each commit to `main` |
| Tasks | finish anything left from the fourth plan, then **C1** now (not waiting for the installer) | **Phase A** (A0–A4), then **Phase B** (B1–B6), in order |
| Owns these files | `red/wakeword.py`, `wake_test.py`, `wake_corpus.py`, `voice_setup.py`, `listener.py`, `audio.py`, `stt.py`, `voice_match.py`, `background.py`, `startup.py`, `llm.py` and their tests | everything new it creates (`red/memory.py`, `greeter.py`, `chat_window.py`, `plugins.py`, `red/plugins/`, `red/secrets.py`…), plus `red/chat.py`, `smalltalk.py`, `speech.py`, `red/app/`, `red/tools/` and their tests |
| The hidden Red | the **only** one that stops and starts it | never stops or starts it, and never runs a live voice Red |
| Test temp folder | `D:\RED\cache\pytest-tmp` | `D:\RED\cache\pytest-tmp-companion` |

- **Shared files** (`red/__main__.py`, `red/config.py`, `.env.example`, `tests/conftest.py`, plan.md,
  progress.md, AGENTS.md, README.md): small additive edits only. Get the latest `main` right before
  editing one; commit and push right after.
- Each session ticks off only its own tasks in plan.md and writes only its own notes in progress.md.
- Before every push: session 1 runs `git pull --rebase`; session 2 runs `git fetch origin` then
  `git rebase origin/main`. Then test and push. **Never force-push.** On a conflict in a file the
  other session owns, keep their version and redo your change on top.
- Session 2's commits reach the hidden Red only when session 1 pulls and restarts it.
- C2, C3 and Phase D wait until both sessions are done.

### Phase A: the companion core

#### A0. Say what Red is now ✅ (2026-11-13)
Update the one-line descriptions: AGENTS.md ("a local, offline voice and action assistant" → a local
companion for Windows), the top of README.md, and progress.md 2 (Goals and scope). Also update AGENTS.md's
"The only account Red talks to is the user's own Google account" rule to match the accounts rule in
this file's Rules (plugins the user signs into). Nothing else changes.

#### A1. A personality, not a professional (old task 3 steps 2–3) ✅ (2026-11-13)
**Done:** the character prompt, the Personality box (General page, `config\personality.txt`) and
punctuation pauses. First sentence of a chat reply, real model: median 0.59 s new against 0.69 s old.
**Left for the user:** listen to `D:\RED\cache\samples-companion\a1-personality-1.wav` … `-5.wav` (the
words are in `a1-personality.txt`) and say what's too much or too little.
1. Rewrite `CHAT_SYSTEM` (`red/chat.py`): a concrete character (dry humour, opinions, reacts before
   answering, teases lightly, admits what it can't do). Add 4–6 short example exchanges that show
   taste. Give `ANSWER_SYSTEM` and tool replies a light touch too ("Done." is fine; "I have
   successfully completed your request" is not).
2. A **custom personality** text in the Red app (General page), added to the prompt, so the user can
   tune it. Persona presets (Witty, Calm, Minimal) come later.
3. Pauses from punctuation instead of a flat 0.12 s: comma ~0.15 s, sentence ~0.3 s, "..." or a dash
   ~0.5 s. Long sentences are cut at commas so the intonation resets.
- **Files:** `red/chat.py`, `red/smalltalk.py`, `red/tools/assistant.py`, `red/speech.py`,
  `red/app/pages.py`.
- **Check:** unit tests; 5 sample replies rendered to WAV for the user; first-word time unchanged.

#### A2. Long-term memory ✅ (2026-11-13)
**Done:** `red/memory.py` (profile, facts, the name, the idle learner), the `remember`, `what_you_know`
and `forget` tools, memory in the chat prompt, and the Memory page. Real model: all 14 test sentences
routed right; "my sister is Priya", a restart, then "what's my sister's name?" answered "your sister is
Priya"; chat first sentence 0.47 s with memory against 0.41 s without.
**Left for the user:** after session 1 restarts the hidden Red: say anything to Red; it asks once "what
should I call you?". Then try "my sister is …", restart, and "what's my sister's name?". Look at the
Memory page (`python -m red app`).
**Why:** today Red remembers 12 lines and then forgets (`MAX_TURNS` in `red/chat.py`). A companion
knows your name, your people, your projects and what you like.
1. `red/memory.py`: a short **profile** (`RED_HOME\memory\profile.md`: name, people, projects, likes)
   and a list of **facts** (`RED_HOME\memory\facts.jsonl`: text, when, from which chat). Never in git.
   **Red knows who you are and uses your name** (the user's choice, 2026-11-13). The name comes from
   the profile. Until it's there, Red asks once in the first chat ("What should I call you?"); "call
   me …" changes it. Use the name like a friend would: in greetings and now and then, not in every
   sentence.
2. Tools: `remember` ("remember my sister is Priya"), `what_you_know` ("what do you know about me?"),
   `forget` ("forget that"; destructive, so it asks once).
3. After a chat, a background worker asks the local model for new facts about the user, **only when
   Red is idle**, so it never slows a reply. Drop anything that looks like a password, a code, a card
   or an address the user didn't ask to keep.
4. The profile plus the 5 facts that best match the current sentence (simple word overlap first; no
   embeddings until that's measured as too weak) go into the chat prompt. Keep the fixed part of the
   prompt first so Ollama's prompt cache still works.
5. A **Memory** page in the Red app: see, edit and delete everything Red knows.
- **Files:** `red/memory.py` (new), `red/chat.py`, `red/tools/memory.py` (new), `red/app/pages.py`,
  `tests/test_memory.py`.
- **Check:** unit tests with `FakeLLM`; by voice, "my sister is Priya", restart Red, "what's my
  sister's name?"; first-word time for chat unchanged (±0.2 s).

#### A3. Hello, not briefings ✅ (2026-11-13)
**Done:** `red/greeter.py` (a hello at the start of the day and after 30+ minutes away, with the name;
lines vary and skip the last 8 used), `RED_CHATTINESS` (quiet, friendly, chatty) on the General page.
Quiet during a full-screen app, game or presentation (`SHQueryUserNotificationState`) and while Red is
busy (never queued). **Limit:** "a call" is checked through Windows' microphone consent store, which
records nothing for desktop apps on this PC, so a Discord or Zoom call isn't detected yet. A later step
could use the audio-session API.
**Left for the user:** a day of normal use: expect one hello at the start of the day and one after each
break of 30+ minutes, nothing else. Say if that's too much or too little.
1. Red greets you on the first sign-in or unlock of the day, and when you're back after 30+ minutes
   away (`GetLastInputInfo` for idle time), **with your name**: "Morning, <name>!", "Hey <name>, you're
   back." Vary the line and don't repeat yesterday's.
2. **Never** put meetings, mail, to-dos or news in a greeting.
3. A **Chattiness** setting: *Quiet* (only answers), *Friendly* (greetings; the default), *Chatty*
   (greetings plus an occasional one-liner, at most once an hour, such as "It's 2 am, you're still at
   it?"). Never while a full-screen app, a game or a call is up (the mic in use by another app).
- **Files:** `red/greeter.py` (new), `red/__main__.py`, `red/smalltalk.py`, `red/app/pages.py`,
  `.env.example` (`RED_CHATTINESS`).
- **Check:** unit tests with a fake clock and fake idle time; a day of normal use with no more than the
  expected greetings.

#### A4. The chat window ✅ (2026-11-13)
**Done:** `red/chat_window.py`: Ctrl+Alt+Space (`RED_CHAT_HOTKEY`, its own pynput hotkey, so
`listener.py` is untouched) or "open chat" (the `open_chat` tool). Typed and spoken turns share one
`Chat`. Code blocks have Copy and Save (Documents\Red Code; the dialog asks before replacing). Drafts
get a Send button that goes through the Executor's read-back. Milky glass, no edge line, square
corners (offscreen renders checked). Real model: 11 sentences routed right ("open chat" ×4, "let's
chat" stays conversation, WhatsApp, Discord, Telegram and Spotify stay `open_app`).
**Left for the user:** after session 1 restarts the hidden Red, press Ctrl+Alt+Space, type something,
then say "Hey Red, …" and check both turns are in the window. The real blur-behind can only be judged on
screen. Nothing creates mail drafts in the window yet (B3); with the overlay off or set to notify, there's
no window.
**Why:** a companion you can type to as well as talk to. Code, mail drafts and lists need a place to
be seen, and a missed "Hey Red" stops being a dead end.
1. A window opened by a hotkey (suggestion: Ctrl+Alt+Space) or by saying "open chat". It holds the
   conversation (typed and spoken, the same `Chat` memory) and tool results.
2. Code blocks with **Copy** and **Save** buttons; mail drafts with **Send** (still read back once).
3. The look follows the glow rules: frosted, milky glass, no rim line, no rounded-edge outline.
- **Files:** `red/chat_window.py` (new), `red/__main__.py`, `red/listener.py` (hotkey).
- **Check:** offscreen renders that you look at before saying it's done; typed and spoken turns land
  in one conversation.

### Phase B: plugins and doing your work

#### B1. Plugins ✅ (2026-11-13)
**Done:** `red/plugins.py`, a Plugins page (reads `plugin.toml` only, never imports), `python -m red
plugins list | on NAME | off NAME`, and `default_registry(plugins=…)`. Red's own plugins load straight
from `red/plugins/` (so updates reach them); setup copies them to `RED_HOME\plugins\_examples\` to read
(folders starting with `_` never load). A plugin that's broken, exits, ships `.pyd`/`.dll`, or clashes
on a tool name is skipped with the reason shown. An off plugin isn't imported at all. MCP stays later.
**Why:** the user wants Red to grow through many plugins.
1. A plugin is a folder `RED_HOME\plugins\<name>\` with `plugin.toml` (name, version, description,
   author, what it needs) and `tools.py` (plain `Tool` subclasses, the same format as `red/tools/`).
2. Red loads them at start. A plugin that fails to import is skipped and logged; it never stops Red.
3. A **Plugins** page in the Red app (on/off per plugin) and `python -m red plugins list`.
4. Safety: plugins are code the user installed. The model only picks a plugin tool and fills its
   schema-checked arguments; model text never reaches a shell. Pure Python only (Smart App Control).
5. Red's own plugins below ship in `red/plugins/` and are copied in by setup, so they're examples
   too.
6. Later: MCP support for local tool servers the user installs.
- **Files:** `red/plugins.py` (new), `red/tools/__init__.py`, `red/app/pages.py`, `red/__main__.py`,
  `tests/test_plugins.py`.
- **Check:** a test plugin loads; a broken one is skipped; on/off works.

#### B2. Write code ✅ (2026-11-13, steps 1–4; step 5 waits)
**Done:** the `code` plugin (`red/plugins/code/`): `write_code` streams into the chat window and says one
line; `explain_code` and `fix_code` read the clipboard or a named file (never changed). Save → Documents\Red
Code, then "Open in VS Code" (Code.exe with the saved path, no shell). Python is checked with
`compile()` only; Red never runs code. "Write me a poem" is answered in words, not code. Real model
(qwen3.5-4b), 10 requests: first code on screen **0.6–1.0 s**, done in **1.7–11.2 s**; **7 of 10
correct**, 3 with real bugs (progress.md has the table).
**Left:** (a) the user's own 10 requests. (b) Step 5, the coder-model spike: it needs a ~5 GB pull into
the Ollama the hidden Red uses, and swapping models makes the hidden Red reload. Do it when session 1 is
done and the user agrees to the download. Candidates to check: current Qwen coder tags that fit 8 GB, and
their licences.
**Why:** "write me a Python script that renames my photos by date" should just work.
1. A `write_code` tool: Red writes the code (streamed) into the chat window. It **never reads code
   aloud**; it says one line ("Here you go, it's in the chat window") and what the code does.
2. Copy to clipboard, save to a file (a Save dialog, `Documents\Red Code` by default, never overwriting
   without asking), and open the saved file in VS Code (through the allowlist).
3. "Explain this code" and "fix this" for the clipboard or a file you name.
4. **Red never runs the code it writes** (Rules: never run model text).
5. Model: Qwen3.5 4B is fine for scripts and snippets up to ~100 lines. Spike a coder model that fits
   an 8 GB GPU (check current Ollama tags and licences), loaded only for `write_code`. Measure quality
   on 10 real requests and the swap time; keep it only if it's clearly better.
- **Files:** `red/plugins/code/` (new), `red/chat_window.py`.
- **Check:** 10 requests from the user; results table in progress.md.

#### B3. App plugins: coding tools, Spotify, WhatsApp, Discord, mail
The user asked for these on 2026-11-13. Each is its own plugin and can be turned off. Each starts with
what works with no account, and adds a sign-in only where it's needed. Sign-in tokens are stored on the
PC, encrypted with Windows DPAPI (`CryptProtectData` through ctypes, a signed system API), in
`RED_HOME\config\`, never in git. An app's data goes only to that app and to the local model.

**B3 progress (2026-11-13):** `red/secrets.py` (DPAPI) ✅, `red/desk.py` (clipboard, keys, fronting) ✅,
and item 1 below (the `coding` plugin) ✅ built and tested with fakes; Spotify, WhatsApp, Discord and mail
are next. **Found on the way:** the router prompt (4,383 tokens) was already over `num_ctx=4096`, and the
plugins made it 5,204, which sent "check my repos" to `list_reminders`. `fit_context` (red/router.py) now
raises the context to fit (8192 today). Session 1: this changes the model load size, so the first start
after pulling reloads the model once (13 s measured); routing times stayed 0.7–1.4 s.
**Left for the user (item 1):** try "open Red in Qoder", "tell Qoder to fix …" (it reads the task back, then
opens Qoder and puts the task on the clipboard; it presses nothing in Qoder, which has no known chat
shortcut, so you paste), "what did it change?". Tell me each tool's chat shortcut to make it paste and
send by itself (`[coding.qoder] chat_key = "ctrl+l"` in allowlist.toml).

**Spotify (no account), WhatsApp and Discord ✅ built 2026-11-13** with fakes (`red/plugins/spotify|whatsapp|discord`).
Spotify: `spotify_search`, `whats_playing` (reads Spotify's window title instead of PowerShell: simpler, no
network). The Spotify Web API sign-in (play a named song, playlists, like) is **not built**: it needs the user
to register a developer app and Premium; ask first. WhatsApp: add `[phones]` to contacts.toml, then
"message Rahul on WhatsApp: running late" reads back, opens the chat filled in and presses Enter only with
WhatsApp in front. Discord: set `mute_key`, `deafen_key` and saved channels under `[discord]` in
allowlist.toml. **Left for the user:** try each once; the WhatsApp link behaviour on this PC is unchecked
(no live app was opened).

1. **Coding tools: VS Code, Qoder, Freebuff, Antigravity and other coding agents** (first; it goes with B2) ✅
   The user codes with several tools: VS Code, Qoder (an agentic IDE), Freebuff (Codebuff's free
   desktop coding agent), Google Antigravity (an agentic IDE) and others. Red sits between the user and them, like a friend at the desk.
   - **Know the tools.** A `[coding]` table in `allowlist.toml` names each tool and how to start it.
     Found on this PC (2026-11-13): VS Code (`code.cmd` on PATH), Qoder
     (`%LOCALAPPDATA%\Qoder\Qoder Launcher\Qoder Launcher.exe`), Freebuff
     (`%LOCALAPPDATA%\Programs\@codebufffreebuff-desktop\Freebuff.exe`), and Google's Antigravity in two
     installs: the IDE (`%LOCALAPPDATA%\Programs\Antigravity IDE\_\Antigravity IDE.exe`, with a
     command-line launcher `bin\antigravity-ide.cmd` that isn't on PATH, likely VS Code-style folder and
     `--goto` arguments; check) and the Antigravity app (`%LOCALAPPDATA%\Programs\antigravity\Antigravity.exe`).
     Qoder, Freebuff and the Antigravity app have no command on PATH. The first-run wizard finds the
     installed ones on other PCs.
   - **Open:** "open Red in Qoder", "open Freebuff", "open plan.md in VS Code at line 40". Project names
     come from `repos.toml` and files must exist; only those reach the tool's command line, never model
     text. Spike whether Qoder's launcher and Freebuff take a folder argument (Qoder is a VS Code fork).
   - **Hand a task to an agent:** "Hey Red, tell Qoder to fix the failing tests in Red." Red reads the
     task back once, opens the project in that tool, brings its window to the front, and puts the task
     in the agent's chat box (clipboard, then paste with the tool's chat shortcut). It presses Enter only
     on a clear yes. The task is the user's own words typed into the app as text, never run as a
     command. A command-line agent (Claude Code, Codex and the like, when installed) starts in a new
     terminal in the project, with the task given as one argument (no shell string). Spike each tool:
     which ones have a reliable chat shortcut or command line.
   - **"Tell me when it's done":** reuse `notify_when_done` (`red/tools/watch.py`) on that tool's
     window. The user asked for it, so speaking up when it's done is fine.
   - **"What did it change?":** a short spoken summary of what the agent changed (`git diff --stat` and
     new commit messages in that repo, read-only git), with the details in the chat window.
   - **VS Code extras:** a file at a line (`code --goto`), compare two files (`code --diff`), and code
     from `write_code` opening as a new file. Later, Red's own small extension (TypeScript), talking to
     Red on loopback with a token: insert at the cursor, "explain what I selected", "what's this error?"
     (the Problems list). Check whether it also loads in Qoder and Antigravity (both VS Code forks).
     Spike it before building.
2. **Spotify**
   - No account: open Spotify, play/pause/next/back (media keys, already there), "search Spotify for X"
     (a `spotify:search:` link), "what's playing?" (the Windows media session through PowerShell).
   - With sign-in (optional): "play Believer on Spotify", playlists, like this song. The Spotify Web
     API with PKCE (no secret). Check Spotify's current developer rules first: playback control needs
     Premium, and new developer apps have limits.
3. **WhatsApp** (WhatsApp Desktop)
   - "Message Rahul on WhatsApp: running late" opens the chat with the text filled in
     (`whatsapp://send?phone=…&text=…`), with numbers from `contacts.toml` (a new optional phone field;
     old files keep working). Red reads the message back, then presses Enter only on a clear yes and only
     with WhatsApp's window in front. Check that the link works on this PC first.
   - Open WhatsApp or a chat. **No reading messages:** WhatsApp has no API for personal accounts, and
     Red doesn't scrape apps.
4. **Discord**
   - Open Discord, open a server or channel (`discord://` links saved by name), mute/unmute and deafen
     (Red presses the keybinds the user sets in Discord).
   - **No reading or sending messages as the user.** Automating a user account breaks Discord's terms
     and can get the account banned. A bot in the user's own server can come later if wanted.
5. **Mail**
   - Gmail (already there): add "anything important in my inbox?" (the top few by sender and subject,
     in one breath) and drafts in your style (a few of your own sent mails as examples; the draft opens
     in the chat window; sending is still read back once).
   - Other mail (Outlook.com, Yahoo, college mail): IMAP and SMTP with an app password, using Python's
     own `imaplib` and `smtplib`, so check, read, reply and send work like Gmail.
6. **Others, after these** (the user picks the order): Telegram Desktop (`tg://` links), launching
   installed Steam games by name (`steam://` links), Notion, browser tabs, OneDrive.
- **Files:** `red/plugins/coding/`, `spotify/`, `whatsapp/`, `discord/`, `mail_imap/` (new);
  `red/tools/gmail.py`; `red/secrets.py` (new, DPAPI); `contacts.example.toml`.
- **Check:** unit tests with fakes for every plugin (no real app opens in a test); each one tried by
  the user.

#### B4. To-dos and "what did I do today?" ✅ (2026-11-13)
**Done:** the `todo` plugin: `todo` (add, list, done, clear; one tool to save router tokens) and
`day_recap` (command log, today's git commits, finished to-dos). The calendar part is not in the recap yet
(Google is optional). Real model routes all 6 sentences; "mark the slides done" falls back to the user's own
words. **Left for the user:** the recap of a real day, read aloud.
Only when asked, never spoken unasked (see the goal).
1. A local to-do list (`RED_HOME\memory\todo.json`): "add finish the slides", "what's left?", "mark the
   slides done", "clear done ones".
2. "What did I do today?": a short recap from `commands.jsonl`, git commits in `repos.toml`, finished
   to-dos and today's calendar.
- **Files:** `red/plugins/todo/` (new).
- **Check:** unit tests; the recap of a real day read to the user.

#### B5. More small plugins
Small, each its own plugin; build in this order and let the user reorder:
1. **Notes:** "note that…", "what did I note about X?" (markdown files in a folder you choose; works
   with an Obsidian vault).
2. **Read a document:** summarise or answer from a txt, md, pdf or docx you name (pure-Python
   readers: `pypdf`; docx through `zipfile` + `xml.etree`, not `lxml`).
3. **Clipboard:** "explain what I copied", "summarise this", "make it shorter".
4. **Windows:** snap left/right, minimise all, switch to an app, close the window in front (asks).
5. **Dictation:** "type this: …" into the window in front (your words, not the model's).
6. **System:** battery, Wi-Fi, Bluetooth and night light through signed Windows settings.
7. **Focus timer:** "25 minutes of focus" with a soft chime at the end.
8. **Fun:** 20 questions, would-you-rather, a quick quiz. A companion should be fun.
- **Check:** each plugin has unit tests and appears on the Plugins page.

#### B6. Jobs with several steps (work mode)
"Find last week's report, summarise it and mail it to Rahul." Red shows the plan in the chat window,
runs each step as a normal tool (confirmations as usual), has a Stop button, and has a step limit.
**Honest limit:** a 4B model is weak at long chains, so start with 2–4 steps and measure on 20 real
jobs before promising more.
- **Files:** `red/router.py`, `red/chat_window.py`, `red/executor.py`.

### Phase C: shipping (the wake word is fixed here, with the installer)

The user chose to finish the wake word together with the installer, because voice-setup is part of the
first-run wizard.

#### C1. "Hey Red" wakes 95 times in 100 (rest of the old task 1)
**Progress (2026-11-13, session 1):** the user recorded the corpus. On `--replay`: "Hey Red" **16/30 →
25/30 (83%)**, with a command 5/10 → 9/10, 0 false wakes (steps 4 and 5 done; numbers per step in
progress.md 7.2). Step 6: beam 1 was faster but lost 2 hits, kept beam 5. **Next:** the user's 100
live tries; if still under 95%, step 7.
**Why:** in `red.log`, 1,936 wake checks and only 22 scored above 0. Whisper writes the user's "Hey Red"
as "Headed", "Heading", "Hit it", "Here Red" or "Hey". The mic is quiet (23% of peaks under 0.05).
`voice-setup` was never run. Steps 1–3 are done (see "Done so far"); the corpus tool waits for the
user's recording (`red wake-test --record`: "Hey Red" 30 times, "Hey Red, open YouTube" 10 times, 2
minutes of normal talk, in `RED_HOME\cache\wake-corpus\`, never in git). Target on `--replay`:
**≥ 95% hits, no false wakes on the talk.**

**User report, 2026-11-13 (passed on by session 2 for session 1):** after the latest wake-word changes the
user said "Red" / "Hey Red" again and Red still didn't notice. Check `red.log` "Wake skip:" lines from
that time.

**Finding from step 2:** a burst only ends after 0.3 s of quiet (PAUSE_AFTER), more than PAUSE_BEFORE
(0.25 s), so "no pause before" never fires. A "Hey Red" said less than 0.3 s after other speech merges
into it, and only the start of the merged burst is checked. Faint speech shows VAD 0.42–0.49 with peaks
of 0.02–0.03.
4. Personal spellings through `voice-setup` (`red/voice_setup.py`), part of the first-run wizard:
   "Headed" or "Hit it" wake for this user only.
5. Looser guards, each measured: look at merged bursts (the finding above), always check the first
   1.3 s of a long burst, VAD start ~0.35, loudness normalised before Whisper.
6. Wake checks on their own worker thread; `beam_size=1` if the corpus allows. (Lower priority: the mic
   keeps buffering while Whisper runs, so this costs delay, not missed words.)
7. Only if 4–6 miss 95%: retrain the openWakeWord model (`scripts/train_hey_red/`) with Kokoro's
   Indian-English voices and the user's clips, as a fast first stage that triggers a Whisper check.
- **Files:** `red/wakeword.py`, `red/wake_test.py`, `red/listener.py`, `red/voice_setup.py`,
  `red/__main__.py`, `tests/test_wakeword.py`.
- **Check:** replay numbers before and after each step in progress.md; then the user's 100 tries.

#### C2. A voice that really laughs and pauses (GPU), and a male voice (old task 4)
1. Spike first (`scripts/tts_bench.py`): local expressive TTS with laugh, sigh and pause tags
   (Chatterbox, Orpheus GGUF, Dia, Sesame CSM; check current versions and licences). On the user's GPU
   with the 4B model loaded: first audio ≤ ~1 s, VRAM, does a laugh sound real, licence, Smart App
   Control. Results table in progress.md; pick at most one.
2. The winner becomes an engine behind `make_speaker` (`red/tts_kokoro.py`); `RED_TTS=auto` uses it on
   a fitting GPU, else Kokoro, else Piper. Models pinned with SHA-256.
3. Male voice: a male/female choice with a Play sample button in the wizard and the Voice page. Kokoro
   has `am_michael`, `am_puck`, `bm_george` and more (samples in `cache\voice-samples`). The user picks
   by ear.

#### C3. One-click installer (old task 6)
`installer/build.ps1` bundles the embeddable Python, the pinned wheels and `red`; Inno Setup makes
`Red-Setup.exe` (per-user to `%LOCALAPPDATA%\Red`, no admin, `RED_HOME`, Start menu, startup entries,
uninstaller). Then the first-run wizard: hardware and model, downloads with checksums, mic and level
meter, voice-setup, voice choice, web search, optional Google sign-in, **plugins to turn on**, and
**your name and a few things about you** (seeds memory). `install.ps1` does the same in one line.
GitHub Releases with SHA-256 hashes; the README notes the "unknown publisher" warning.
- **Check:** a clean Windows Sandbox or VM with Smart App Control on: download to a working "Hey Red"
  with no command line; the uninstaller leaves nothing.

### Phase D: the face

#### D1. The glow (waiting for the user's design)
`red/overlay.py` `GlowWindow` stays as it is until the user shares the design. Then build it, render
every state offscreen, look, and update `tests/test_voice_feel.py`.

#### D2. The desktop companion (old task 7, now the face of Red)
An **original** 2D character (not a copy of Desktop Mate's or anyone's) in a transparent, click-through
PySide6 window: sleeps when idle, perks up at "Hey Red" or a greeting, thinks, talks with its mouth
moving to the TTS loudness. Click it to open the chat window; drag it anywhere; on/off in the Red app.
Show the user 2–3 sketches rendered offscreen before building.

**Needed from the user:** a reboot test (old task 2), listening to personality samples (A1), a day of
greetings (A3), 10 code requests (B2), trying each app plugin and signing in to Spotify if wanted
(B3), the wake corpus and 100 tries (C1), picking the male voice (C2),
the glow design (D1), picking the character sketch (D2).

### For the user to decide
- **Chattiness default:** Friendly (greetings only) is the plan's default. Chatty instead?
- **Decided 2026-11-13:** Red uses the user's name (A2, A3). Plugins wanted, with sign-ins where needed
  (B3): coding tools (VS Code, Qoder, Freebuff, Antigravity and other agents), Spotify, Discord, WhatsApp, mail.
- **Mascot shape:** the Rules forbid rounded edges and an outline on the glow. Does that apply to the
  character too?

## Speed plan: the first word in about a second (2026-11-11)

Still applies to quick commands and chat. Measure with the `Timing` lines in `red.log`
(red/__main__.py:672) before and after every step, and never ship a step without numbers.

Where the time goes (one command, from when you stop talking): listen → transcribe (Whisper) → route →
tool → speak. A question today is two full 4B generations in a row, plus a web search.

1. **Numbers first.** Real first-word times for "open Edge", "what is a black hole" (answer), "who made
   Siri" (look_up), "weather in Pune", and one chat line.
2. **Widen the fast path** (`red/fastpath.py`): "who is/was X", "when was X", "where is X", "how
   tall/big/far is X", "what does X mean", "how do I X" → straight to `answer`/`look_up`. Check against
   `commands.jsonl`: every sentence the fast path now answers must be one the model would have routed
   the same way.
3. **One model call for a question, not two:** when the fast path knows it's `answer` or `look_up`,
   skip the router call.
4. **Cut look_up's web wait:** budgets ~3 s and ~1.0 s instead of 6 s and 1.5 s
   (red/tools/sources.py:42–47).
5. **Cache the router prompt in Ollama:** nothing may vary the prefix between calls (red/llm.py:252);
   check that `num_ctx=4096` fits it.
6. **Route with a small model, answer with the big one**, only if 2–5 aren't enough.
7. **The first spoken word:** preload the Kokoro voice; check Ollama isn't unloading between the 240 s
   warm-ups.

Done when "open Edge" takes 1–3 s, a question or chat's first word 1–2 s, and "play Believer" 2–3 s.

## Shipping ($0 budget)

1. One-line installer: `irm https://raw.githubusercontent.com/AryanLanke/Red/main/install.ps1 | iex`.
2. `Red-Setup.exe` (Inno Setup). Without a code-signing certificate, Windows warns about an unknown
   publisher.
3. Free channels: GitHub Releases (SHA-256 hashes), a GitHub Pages site (`aryanlanke.github.io/Red`),
   `winget` (`winget install AryanLanke.Red`), itch.io, SourceForge.

## Later: more for the Red app

**Sections:**
- **Model:** the current model, a pick from `MODELS` with each one's `best_for` line, downloads, and the
  hardware recommendation.
- **Voice:** voices with a Play sample button, male and female, and speed.
- **Personality:** custom personality text, Chattiness, and later persona presets.
- **Memory:** everything Red knows about you, editable (A2).
- **Plugins:** on/off per plugin (B1).
- **Wake phrase and listening:** "Hey Red" with voice training, sensitivity, hotkeys, microphone, voice
  match on/off and re-recording.
- **Speech-to-text:** Whisper model (`base.en` / `small.en`) and device.
- **Browser:** `RED_BROWSER` and the search engine.
- **Web search:** on or off, with the privacy note, and whether SearXNG is running.
- **Accounts:** sign in and out of Google, Spotify and other mail.
- **General:** start with Windows (`red/startup.py`).

Also later: Ollama that reuses the cached prompt for Qwen3.5 (check each new Ollama release,
progress.md 5), so Qwen3.5 can be the model for PCs with no GPU too.

## Rules: what to do and what not to do

Do:
- Read the latest lines of `RED_HOME\logs\commands.jsonl` and `red.log` before changing behaviour. The
  user's real sentences are there.
- Test against the real local model (`RED_INTEGRATION=1`) whenever routing, prompts or the model change.
  Run the full unit suite with the shared venv:
  `$env:RED_HOME="D:\RED"; $env:QT_QPA_PLATFORM="offscreen"; D:\RED\.venv\Scripts\python.exe -m pytest --basetemp="D:\RED\cache\pytest-tmp"`.
- Measure speed before and after every speed change, with numbers from the `Timing` lines in `red.log`.
- For any visual change, render previews offscreen and look at them before telling the user it's done.
- Commit as several small commits and push to `main` (the user wants contributions), then restart the
  hidden Red so the user tests the new code.
- Use files for long scripts and commit messages. PowerShell and bash here-docs break on quotes.
- Keep confirmations for shutdown, restart, sleep, emptying the Recycle Bin, forgetting a memory, closing
  a window, and sending a mail or deleting a calendar event (the user chose a read-back for those two).
  Keep allowlists. Never run model text as a command, including code Red writes.
- Take ideas from other projects (OpenJarvis and others), not their code.

Don't:
- Don't ask permission or "Anything else?" for harmless actions.
- Don't use stock assistant lines ("I'm here to help", "How can I assist you") or a business tone.
- Don't speak meetings, mail, to-dos or news unasked. Greetings and the user's own reminders only.
- Don't read code aloud.
- Don't let Red claim things that aren't true (seeing images, music playing, a body, a page that didn't
  open).
- Don't send voice, screen, memory or the AI's work to any cloud service. Red is local-only. Public
  look-ups (Wikipedia, weather, news, YouTube search) are fine.
- Accounts: Red talks only to services the user signs into through Red (Google, and plugins such as
  Spotify or other mail), and sends each one only what that service needs. Tokens are encrypted with
  DPAPI and never go into git.
- Don't automate a user account where the service forbids it (Discord), and don't scrape apps
  (WhatsApp).
- Don't put the user's memory files, voice clips or wake corpus in git.
- Don't build for Mac, Linux or other languages.
- Don't install packages with unsigned native DLLs. Smart App Control blocks them (it blocked `winrt-*`).
  Use Windows PowerShell or signed system APIs instead.
- Don't run a hidden test copy of Red while the user is testing. Stop the background Red first, and
  restart it after.
- Don't bring back a rim or outline line on the glow, or rounded-corner edges. The user wants frosted,
  milky, liquid glass with no edge line.
- Don't use "Jarvis" anywhere in Red's text or defaults.

Usage limit (any coding agent: Claude, DeepSeek, Kimi or another):
- If your usage (a weekly or session limit, or any provider's quota) reaches **90%**, don't start anything
  new. Finish the smallest working part of the task you are on, run the unit tests, commit, **push to
  `main`**, and write a short hand-off note under that task in this file: what is done, what is left, and
  the exact next step. Then stop and tell the user.
- If you can't see your usage, commit and push after every task anyway, and after every hour of work.
- Never leave uncommitted work, a half-edited file, or a stopped hidden Red when you stop. Restart it.

Any agent:
- Read AGENTS.md first. This is Windows with PowerShell 5.1: no `&&` (use `;`), and the shared venv is
  `D:\RED\.venv` with `RED_HOME=D:\RED`.
- Don't write code through shell here-docs: they turn `\b` into a backspace and break quotes. Write files
  with your editor tool, and after any script edit search the changed files for control characters.
- Don't change `D:\RED\config\.env` without asking the user.

# Red: what to do next

Updated 2026-11-08 (late evening). The first plan's seven tasks are done (see "Done" below and git
history). This version comes from comparing Red with Hey Copilot (Windows), the Gemini-based Siri and
Gemini (which replaced Google Assistant), and from the user's voice test at 23:36–23:38
(log: RED_HOME\logs\commands.jsonl and red.log).

Read this first, then AGENTS.md. Do the tasks in order. Each task lists the files and how to check it.
After finishing a task: run the tests, commit (several small commits), push to main, restart the hidden Red
(`python -m red stop` then `python -m red background`), and tick it off here.

## The goal

A **Windows-only** voice assistant that competes with "Hey Siri", "OK Google" and "Hey Copilot". The
wake phrase is "Hey Red". Red must be **faster than doing it by hand** and must **finish the whole job**,
otherwise the user does it themselves.

- **Any Windows PC:** it runs on everything from a laptop with no GPU to one with an 8 GB+ GPU (RTX 3050,
  4050 and so on).
- **English only.**
- **Local and free:** the AI model, speech-to-text, voice, wake word and screen reading all run on the
  PC, with no account needed. The one exception is the optional Google sign-in for mail and calendar
  (task 6).

Speed targets, measured from when the user stops talking (the `Timing` lines in `red.log`):

| Request | Target |
|---|---|
| "open Edge", "volume up", "pause", "lock" | done in about 1–3 s |
| "play Believer" | playing in about 2–3 s |
| a question or chat | Red starts speaking in about 1–2 s |
| "give me a big summary" | starts in about 1–2 s, then talks as long as the answer needs |

Waiting 5 s or more before anything happens is a failure: the user could have done it by hand.

**Not doing:**
- smart home
- other languages
- Mac or Linux
- cloud AI models
- big models that run partly on the CPU (gpt-oss-20b, Qwen3.5-35B-A3B), which are too slow

## Done (first plan, 2026-11-08)

1. No permission questions for harmless things (`smalltalk.yes_intent()`, `confirm.is_clear_yes()`).
2. Do it, then go quiet (`VoiceApp._exchange`, `Tool.finish_later()`).
3. `play_online`: podcasts, videos and trailers on YouTube (`red/tools/youtube.py`).
4. Opened windows come to the front (`red/windows.py`).
5. `Timing` lines, the 0.8 s quick end of speech, the reply spoken while launching, and `base.en` on this
   PC (progress.md 7.2).
6. Answers that remember the conversation and go long when asked. When the router picks `none`, Red now
   speaks a real chat reply, and the router's placeholder is kept only as `router_reply` in the log.
7. Filler ("you know", "hmm") runs nothing (`smalltalk.is_filler()`).

## Tasks, in order

### 1. Fix "open YouTube": it showed an empty browser tab, not YouTube
**What happened (log, 23:37–23:38):**
- The user said "Open YouTube.", then "Red you just open chrome. I told you to open YouTube", then "Can
  you open YouTube for me from Chrome?".
- Routing was right all three times: `open_url` with `https://www.youtube.com`.
- But each time `red.windows` logged
  `Brought the existing window 'New tab - Personal - Microsoft Edge' (msedge.exe) to the front`.
  The user saw a blank tab.

**Why:**
- The Windows default browser on this PC is **Edge** (`UrlAssociations\https\UserChoice` = `MSEdgeHTM`),
  but the user uses **Chrome**. A Chrome window showing YouTube was open at the time.
- `OpenUrl` and `WebSearch` always use `webbrowser.open`, which means the Windows default browser. They
  have no way to pick a browser, so "from Chrome" is ignored.
- `Watcher` with `reuse=True` (`red/windows.py`) fronts *any* existing window of the browser after
  `REUSE_AFTER_SECONDS`, even one that isn't showing the page Red opened. Here it fronted a "New tab"
  window, whose title was still "New tab" 50 s later. Edge may have opened the page in another window or
  profile, or not at all.

**Fix:**
- **`RED_BROWSER` setting** (`chrome` by default; also `edge`, `firefox` or `default`):
  - Red launches that browser's exe, found through App Paths like `open_app` does, with the URL as one
    argument: `Popen([exe, url])`, no shell, URL already validated as http or https.
  - If the browser isn't installed, use the Windows default.
  - Add the setting to `Settings`, `.env.example` and README.
- **Optional `browser` argument** (enum: chrome, edge, firefox) on `open_url` and `web_search`, for
  "open YouTube from Chrome" or "search this in Edge". Update the tool descriptions so the router fills
  it.
- **Front the right window.** For browsers, wait up to about 5 s for a window whose title contains the
  site's name ("youtube"), or one whose title changed after the launch. Front that one. Never front a
  browser window whose title didn't change. If none shows up, log it and front nothing.
- **Find out why Edge stayed on "New tab".** Do this once by hand, with the user's OK and the hidden Red
  stopped. Write down what you find in progress.md.
- Don't change the user's Windows default browser.

**Files:** `red/tools/web.py`, `red/windows.py`, `red/tools/system.py` (App Paths lookup),
`red/config.py`, `.env.example`, README.

**Check:**
- Unit tests with a fake desktop whose window titles change after the launch, and with `FakePopen`
  checking the exact argument list.
- Real-model routing cases: "open YouTube", "open YouTube from Chrome", "search lofi in Edge".
- Manual check with the hidden Red: "open YouTube" shows YouTube in Chrome, in front.

### 2. No local music: every "play …" goes online
- The user doesn't want local music. Route every "play X" (songs, artists, podcasts, videos) to
  `play_online`, and take `play_music` out of the registry and the router rule.
- Pause, resume, next and previous keep working through the media keys, so they control YouTube in the
  browser.
- `play_online` opens in the `RED_BROWSER` browser and fronts the right window (task 1).
- **Files:** `red/tools/music.py`, `red/tools/youtube.py`, `red/tools/__init__.py`, `red/router.py`,
  README, `.env.example` (`RED_MUSIC_DIR` goes).
- **Check:** unit tests, plus real-model routing for "play Believer", "play some Arijit Singh" and "play
  a podcast about loneliness".

### 3. Switch the model from Qwen2.5 7B to Qwen3.5 4B
**Decision (user, 2026-11-08):** the default model changes from `qwen2.5-7b-instruct-q4_k_m`
(September 2024, 7.6B parameters, 4.7 GB) to **Qwen3.5 4B** (March 2026, 4B parameters, about 3 GB, free
under Apache 2.0).

Published scores are far higher:

| Test | Qwen2.5 7B | Qwen3.5 4B |
|---|---|---|
| instruction following (IFEval) | 71.2 | 89.8 |
| knowledge (MMLU-Redux) | 75.4 | 88.8 |
| harder knowledge (MMLU-Pro) | 56.3 | 79.1 |

Qwen3.5 4B is also smaller, so it should be faster, and it can read images. The Qwen3.5 numbers come from
an aggregator site (llm-stats) and were probably measured in thinking mode, so test before switching.

**Steps:**
1. Add `qwen3.5-4b` to `MODELS` in `red/llm.py`, with its Ollama tag and Hugging Face GGUF files pinned
   by SHA-256 like the others. Keep Qwen2.5 7B as an option.
2. Run it in non-thinking mode, because Red needs speed.
3. Add the routing misses from the log to the test set and the router prompt examples:
   - "Can you just read my screen? What's going on?" → `describe_screen` (it went to `none`)
   - the YouTube lines from task 1
   - the "play …" lines from task 2
4. Run the user's real sentences from `commands.jsonl` and every integration test through both models.
   Compare correct tool choice, answer quality and time to first word on this laptop (RTX 4050 6 GB,
   16 GB RAM, Ryzen 7 7735HS), with the GPU and CPU-only.
5. Make Qwen3.5 4B the default in `red/config.py` (`DEFAULT_MODEL`), `.env.example`, README and
   AGENTS.md. Ask the user before changing `RED_HOME\config\.env`.
6. Update the tests that name Qwen2.5 7B, and write the comparison in progress.md.

**Only if Qwen3.5 4B is clearly worse** at picking Red's tools: stay on 7B, and tell the user with the
numbers.

**Also add as options:**
- `qwen3.5-9b` (about 6.6 GB) for PCs with an 8 GB+ GPU.
- A ~2B model for PCs with no GPU.
- Check whether Qwen3.6 small models exist yet; if one beats Qwen3.5 4B, tell the user before switching.

**Hardware defaults.** `python -m red setup` detects the GPU's memory (`nvidia-smi` or DXGI) and the RAM
(`GlobalMemoryStatusEx`) and picks a starting model. The user can change it in settings (and later in the
settings app).

| PC | Model | Whisper |
|---|---|---|
| No GPU, 8 GB RAM | ~2B | `base.en` |
| No GPU, 16 GB RAM | Qwen3.5 4B | `base.en` |
| 4–6 GB GPU (RTX 3050/4050) | Qwen3.5 4B on the GPU | `base.en` (progress.md 7.2) |
| 8 GB+ GPU | Qwen3.5 9B | `small.en` on the GPU |

**Screen reading:** with Qwen3.5 4B, `describe_screen` sends the screenshot as well as the screen text,
so Red understands what it sees, not only the words.

### 4. Instant common commands
- **Why:** in the 23:37 test, routing took 1.3 s of the 2.65 s for "open YouTube". Common, clear commands
  don't need the model.
- **New `red/fastpath.py`, called first from `Router.route()`.** Patterns for:
  - "open X", "open X in/from Chrome"
  - "volume up/down/mute"
  - "pause", "resume", "next", "previous"
  - "lock", "what time is it", "take a screenshot"
  - "play X", "search X (on YouTube)"
- **Anything unclear goes to the model as now.** Results go through the same `Router.parse()` validation
  and the same confirmations as model calls.
- **Must work in well under 1 s with no GPU.**
- **Check:** unit tests, plus `Timing` lines before and after. Target: "open YouTube" done about 1.5 s
  after the user stops talking.

### 5. Speak while the model writes; interrupt Red
- **Why:** in the 23:37 test a chat reply took 6.6 s to speak and was finished 11 s after the user
  stopped.
- **Streaming:** use `"stream": true` from Ollama (`red/llm.py`), split the output into sentences, and
  send each finished sentence to Piper while the rest is written. Do this for `answer`, `look_up`, chat
  and `describe_screen`. Long answers start in about 1–2 s and then talk as long as they need.
- **Prompt caching:** keep each system prompt byte-for-byte identical between calls, and check that
  Ollama reuses the cached prompt so only the new sentence is processed.
- **Interrupt:** "Hey Red" while Red is talking stops the speech and starts listening.
- **Files:** `red/llm.py`, `red/tts.py`, `red/chat.py`, `red/tools/assistant.py`, `red/__main__.py`,
  `red/listener.py`.
- **Check:** `tests/test_voice_app.py` with fakes, plus `Timing` lines ("first word spoken" added).

### 6. Mail and calendar
**Ask the user first:** should Red read back once before **sending an email** or **deleting a calendar
event** ("Sending to Mom: I'll be late. Send?")? The proposal is yes for those two only, and no questions
for anything else. Build it the way they answer.

**Sign-in:**
- One optional, one-time `python -m red google-login` grants Gmail, Calendar and Contacts.
- The token goes in `RED_HOME\config\google-token.json`, which is never committed.
- Ask for the smallest scopes that work.
- Use pure-Python Google client packages pinned in `requirements.txt`, after checking that Smart App
  Control doesn't block them.

**Mail:**
- "any new mail?" (count, plus the senders and subjects of the newest few)
- "read my mail from Rahul" (summary)
- "reply saying I'll come tomorrow"
- "mail Mom that I'll be late"
- Keep `compose_mail` (the mailto: link) for users who don't sign in.

**Calendar:** "what's on my calendar tomorrow?", "add a meeting Friday at 3", "move my 5 pm to 6",
"cancel my 4 pm".

**Contacts:** names come from Google Contacts, then `contacts.toml`.

**Limits:**
- Nothing the model writes becomes a command.
- Recipients must resolve to a real contact or a valid address.
- Bound subject and body lengths like `compose_mail` does, and cap results and time.

**Rule change:** only mail and calendar text goes to the user's own Google account. Voice, screen and
the AI stay on the PC. Update README and AGENTS.md to say so.

**Files:** new `red/google_auth.py`, `red/tools/gmail.py`, `red/tools/calendar.py`, registered in
`red/tools/__init__.py`.

**Check:** unit tests with a fake Google client (no network), plus real-model routing. The user tests
the sign-in by hand.

### 7. Answer only the owner (voice match)
- `python -m red voice-setup` also records about 10 phrases from the owner and saves a voice profile in
  `RED_HOME\models\wakeword`.
- At each "Hey Red", Red compares the voice with the owner's using a small, pinned speaker-recognition
  ONNX model on `onnxruntime` (already installed, so Smart App Control has nothing new to block). It stays
  silent for anyone else. The hotkey always works.
- Settings: `RED_VOICE_MATCH=on|off` (off until tested) and `RED_VOICE_MATCH_THRESHOLD`.
- **Files:** `red/wakeword.py`, `red/listener.py`, `red/voice_setup.py`, new `red/voice_match.py`,
  `red/config.py`, `.env.example`.
- **Check:** unit tests with saved audio fixtures, never the microphone. Ask the user to test it with
  another person speaking.

### 8. Several things in one sentence
- "Open Chrome and search flights to Delhi", "mute and lock the PC", "check my mail and read today's
  calendar".
- The router returns up to about 4 tool calls. Each one is validated and confirmed like a single call,
  and they run in order.
- If a step fails, Red stops and says which one.

## Later: the Red Settings app

A small desktop app **only for changing Red's settings**: no chat window and no assistant inside it.

- **Launching:** from the Start menu, from the tray, or with `python -m red settings`.
- **Built with PySide6** (already used). It follows Red's look: frosted, milky glass with no outline line
  and no rounded-corner edges.
- **Saving:** it writes `RED_HOME\config\.env` through `Settings` and restarts the hidden Red when you
  press Save.

**Sections:**
- **Model**
  - the current model
  - pick from `MODELS`, each with a short "best for" line (fast, smart, no GPU)
  - download with progress and checksum
  - the hardware recommendation from task 3
- **Voice**
  - male and female Piper voices with a Play sample button
  - already downloaded: female `en_US-amy`, `en_US-lessac`, `en_GB-jenny_dioco`, `en_US-libritts_r`;
    male `en_US-joe`, `en_US-ryan`, `en_GB-alan`
  - speaking speed
- **Wake phrase and listening**
  - "Hey Red", "Yo Red", "Okay Red", "What's up Red", with voice training for each
  - sensitivity
  - hotkey
  - microphone
  - voice match on/off and re-recording
- **Speech-to-text:** Whisper model (`base.en` / `small.en`) and device.
- **Personality:** normal or opt-in casual (banter that swears back).
- **Browser:** `RED_BROWSER` and the search engine.
- **Accounts:** Google sign-in and sign-out.
- **General:** start with Windows (`red/startup.py`).

Also later:
- A one-click Windows installer, so users need no Python or venv. Without a code-signing certificate,
  Windows warns about an unknown publisher.
- A glow that reacts to the voice.
- "Hey Red, open Downloads" said in one breath.

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
- Keep confirmations for shutdown, restart, sleep, emptying the Recycle Bin, and whatever the user
  chooses in task 6. Keep allowlists. Never run model text as a command.

Don't:
- Don't ask permission or "Anything else?" for harmless actions.
- Don't use stock assistant lines ("I'm here to help", "How can I assist you").
- Don't let Red claim things that aren't true (seeing images, music playing, a body, a page that didn't
  open).
- Don't send voice, screen or the AI's work to any cloud service. Red is local-only. Public look-ups
  (Wikipedia, weather, news, YouTube search) are fine, and so is the user's own Google mail and calendar
  after they sign in (task 6).
- Don't build for Mac, Linux or other languages.
- Don't install packages with unsigned native DLLs. Smart App Control blocks them (it blocked `winrt-*`).
  Use Windows PowerShell or signed system APIs instead.
- Don't run a hidden test copy of Red while the user is testing. Stop the background Red first, and
  restart it after.
- Don't bring back a rim or outline line on the glow, or rounded-corner edges. The user wants frosted,
  milky, liquid glass with no edge line.
- Don't use "Jarvis" anywhere in Red's text or defaults.

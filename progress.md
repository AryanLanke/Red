# Red: progress and plan

This file is for developers and coding agents. [README.md](README.md) is for users. Read [AGENTS.md](AGENTS.md) for commands and how the code fits together.

Last updated: 2026-11-09.

---

## 1. Where things stand

| Area | Files | Status |
|---|---|---|
| Config and `RED_HOME` | `red/config.py` | ✅ Done (Day 1) |
| Pinned, checksum-verified downloads | `red/downloads.py` | ✅ Done (Day 1) |
| LLM backends (Ollama, llama.cpp, your own server) | `red/llm.py`, `red/process.py` | ✅ Done (Day 1) |
| Tool interface and registry | `red/tools/base.py`, `red/tools/__init__.py` | ✅ Done (Day 1) |
| Intent router (JSON-schema constrained) | `red/router.py` | ✅ Done (Day 1) |
| CLI: `setup`, `route`, `run`, voice loop, `--typed`, `--dry-run` | `red/__main__.py` | ✅ Done (Track D) |
| Actions: folder, app, URL, shutdown, restart, cancel | `red/tools/system.py`, `red/tools/web.py` | ✅ Done (Track A) |
| Confirmation, allowlist, command log, executor | `red/confirm.py`, `red/allowlist.py`, `red/known_folders.py`, `red/executor.py` | ✅ Done (Track A) |
| Speech to text, text to speech, hotkey, wake word | `red/audio.py`, `red/stt.py`, `red/tts.py`, `red/listener.py`, `red/voice_confirm.py` | ✅ Done (Track B). The "Hey Red" wake word is Track E |
| Floating overlay | `red/overlay.py` | ✅ Done (Track C) |
| The companion on screen (2D, peeking over the bottom edge) | `red/avatar/`, `scripts/avatar_render/` | ✅ First version 2026-11-13 (7.3.1). Waits on the user trying it on the real desktop |
| Repo sync tool | `red/tools/git_sync.py` | ✅ Done (Track C). The local music tool was removed on 2026-11-09 (7.4) |
| Wiring it all together: settings, setup, voice loop, docs | `red/__main__.py`, `red/config.py`, `README.md`, `AGENTS.md` | ✅ Done (Track D, section 8.13). The shared venv install and the v0.1.0 tag are still to do |

**Day 1 result:** typed commands like "open Downloads" and "shut down in 2 hours" produce the right JSON in under a second once the model is loaded. 38 unit tests and 8 real-model tests pass. Commits: `a44da78` (project setup), `ebae152` (Day 1 code), `727ac5f` and `ffe2ff1` (README).

---

## 2. Goals and scope

**The aim since 2026-11-13:** Red is a companion for your Windows laptop, not a business assistant. A friend with a personality (casual, warm, dry humour, opinions) who lives on the PC, remembers you and uses your name, does your work (apps, files, mail, code), grows through plugins, and later sits on the desktop as a character. It greets you but never briefs you: meetings, mail, to-dos and news only when you ask. Everything below is still true; it's how Red helps. See plan.md "The goal".

**The bigger goal (2026-11-08):** a voice assistant for Windows as good as "Hey Siri" and "OK Google", which Windows doesn't have. That means a wake word that reliably hears its owner, a pleasant, polished look, natural conversation (follow-ups, knowing when to stop), and a settings app instead of editing `.env`.

**The aim (2026-11-08):** an assistant for your own PC. You tell Red to do something and it does it, locally and safely.

| You say | What Red does | Where it is in the plan |
|---|---|---|
| "Shut down" | Shuts down, after a yes | v0.1, Track A (`shutdown`) |
| "Open YouTube" | Opens it in the browser | v0.1, Track A (`open_url`) |
| "Open PowerPoint" | Starts the app | ✅ Track F: `open_app` finds PowerPoint, Word, Excel, Outlook, OneNote, Teams, Chrome, Edge and more through the registry's App Paths when they're installed |
| "Find my resume" / "where is file X" | Finds the file or folder and offers to open it | ✅ Track F: `find_file` plus `open_found_file` ("open it"). Read-only name search of the known folders and allowlisted folders, with a 4-second limit and 5 results at most. Programs and scripts are never run: Red opens their folder instead |
| "Search the web for X" | Opens a web search in the browser | ✅ Track F: `web_search` on Google (or `RED_SEARCH_ENGINE`), YouTube, images, maps, news or Wikipedia. Reading results aloud comes later |
| "Compose a mail to X about Y" | Opens a new draft with the recipient, subject and body filled in | ✅ Track F: `compose_mail` through a `mailto:` link. Names come from `contacts.toml`, and Red never sends. Sending through Gmail stays with the Gmail work, and always asks first |
| "Lock my PC", "volume up", "pause", "open Bluetooth settings", "what time is it", "take a screenshot", "sleep", "empty the Recycle Bin" | Does it at once; sleep and emptying the Recycle Bin ask first | ✅ Track F: `lock_pc`, `volume`, media keys in `pause_music`, `resume_music`, `next_song` and `previous_track`, `open_settings`, `tell_status`, `take_screenshot`, `sleep_pc` and `empty_recycle_bin` |
| "Set a timer for 10 minutes", "remind me at 3 pm to call mom", "what reminders do I have", "cancel the timer" | Says it when it's due, even after a restart | ✅ Track G: `set_timer`, `set_reminder`, `list_reminders` and `cancel_reminder` on `red/scheduler.py`. Up to 7 days ahead; Track H wires the voice |
| "What is Hugging Face", "explain recursion" | Answers aloud in 2 to 4 sentences, offline | ✅ Track G: `answer`, a second call to the local model |
| "What's the weather in Pune", "latest news about India", "look up the James Webb telescope" | Fetches it online and says it; "I'm offline" with no network | ✅ Track G: `weather` (Open-Meteo), `news` (Google News headlines), `look_up` (Wikipedia, summarised by the local model) |
| "Play a podcast about loneliness", "play the Punisher trailer", "play lofi on YouTube" | Starts the first YouTube video in the browser and says its title | ✅ `play_online` (`red/tools/youtube.py`): reads the first `videoRenderer` from the public results page, no API key; opens the results page if that fails. Songs and artists go here too since 2026-11-09 (7.4) |
| Anything else | Says it can't do that yet | New abilities arrive as tools (section 4), and the plugin system (v0.4) makes adding them easy |

The safety model doesn't change as Red grows: every ability is a tool with a fixed schema, nothing the model says is run as a command, and destructive actions ask first.

**MVP (v0.1):**
- Wake word "Hey Red" plus a global shortcut to activate
- Floating overlay window that shows Red's status and reply
- Spoken replies (TTS)
- Commands: open a folder or app, open a URL, shut down or restart after a delay, play music from a local folder
- Repo sync check: compare local Git repos with GitHub and report what's unpushed or behind
- Confirmation step for any destructive action

**Later (not in the MVP):** Gmail read and mark actions, automated multi-step tasks, a plugin system, calendar, reminders and smart home.

**Out of scope:** trading or financial automation. Red never calls a cloud model.

---

## 3. Architecture

```
          +-------------------+
 "Hey Red"|  Wake word        |  openWakeWord (always on, local)      Track B
 shortcut ->  + hotkey        |  pynput                               Track B
          +--------+----------+
                   v
          +-------------------+
          |  Speech to text   |  faster-whisper (local)               Track B
          +--------+----------+
                   v
          +-------------------+
          |  Intent router    |  Local LLM via Red-managed Ollama     Day 1
          |  (picks a tool)   |  JSON-schema constrained: {tool, args}
          +--------+----------+
                   v
          +-------------------+
          |  Executor         |  confirm destructive -> run -> log    Track A
          |  + tool registry  |  system, web (A); music, git (C)
          +--------+----------+
                   v
          +-------------------+
          |  Reply            |  overlay (C) + TTS with Piper (B)
          +-------------------+
```

### Folder layout (✅ exists, ⏳ planned, with the track that owns it)

```
red/
├── README.md               # for users
├── progress.md             # this file
├── AGENTS.md, CLAUDE.md    # guidance for coding agents
├── .env.example
├── allowlist.example.toml  # ⏳ A
├── repos.example.toml      # ⏳ C
├── requirements.txt        # core deps; -r lines for the files below are added at integration
├── requirements-voice.txt  # ⏳ B
├── requirements-ui.txt     # ⏳ C
├── red/
│   ├── __main__.py         # ✅ entry point (A changes it during the tracks)
│   ├── config.py           # ✅ RED_HOME and settings
│   ├── downloads.py        # ✅ checksum-verified downloads
│   ├── llm.py              # ✅ LLM backends and clients
│   ├── process.py          # ✅ child servers that stop when Red stops
│   ├── router.py           # ✅ LLM intent to tool call
│   ├── confirm.py          # ⏳ A: yes/no confirmation
│   ├── allowlist.py        # ⏳ A: loads allowlist.toml
│   ├── known_folders.py    # ⏳ A: Windows Known Folder API
│   ├── executor.py         # ⏳ A: confirm, run, log one route
│   ├── audio.py            # ⏳ B: microphone recording
│   ├── stt.py              # ⏳ B: Whisper wrapper
│   ├── tts.py              # ⏳ B: Piper wrapper
│   ├── listener.py         # ⏳ B: hotkey and wake word
│   ├── voice_confirm.py    # ⏳ B: spoken yes/no
│   ├── voice_demo.py       # ⏳ B: try voice without the rest of Red
│   ├── overlay.py          # ⏳ C: floating status window
│   └── tools/
│       ├── base.py         # ✅ Tool interface
│       ├── system.py       # ✅ schemas, ⏳ A: actions
│       ├── web.py          # ✅ schema, ⏳ A: action
│       ├── music.py        # ⏳ C
│       └── git_sync.py     # ⏳ C
└── tests/
```

---

## 4. Tool interface and conventions

```python
class Tool:
    name: str            # "shutdown"
    description: str     # shown to the LLM so it knows when to use it
    args_schema: dict    # JSON schema for arguments
    destructive: bool    # if True, Red asks for confirmation first

    def run(self, **kwargs) -> str:
        """Do the action and return a short reply for the user."""
```

The router sends the model every tool's name, description and schema. The model must reply with JSON only, for example `{"tool": "shutdown", "args": {"minutes": 180}}`. Generation is constrained to that schema, and `Router.parse()` checks the JSON and the argument limits again before anything runs. `none` is the reserved "no tool fits" reply.

Conventions for every new tool:
- **Side effects are passed in through the constructor** with real defaults, for example `def __init__(self, runner=subprocess.run, startfile=os.startfile)`. Tests pass fakes, so no test opens a window, plays audio, or schedules a shutdown.
- **No text from the LLM is ever run as a command line.** Names are lookup keys into a known list (Windows' standard folders, the allowlist, the music library, the repo list).
- **Schema limits are the safety limits.** Put ranges and lengths in `args_schema` instead of only checking them in `run()`.
- **Replies are one or two short sentences**, because they are spoken aloud.
- **Descriptions are part of the prompt.** Rewording one can change how other commands route, so run the real-model tests after changing any.

---

## 5. Models

| Job | Model | Why |
|---|---|---|
| Intent routing and answers | Qwen3.5 4B (Q4_K_M, non-thinking) via Ollama by default since 2026-11-09; Qwen3.5 9B for 8 GB+ GPUs; Qwen2.5 3B with no GPU. Qwen2.5 7B is still an option | Free (Apache 2.0), private, offline; see "Qwen3.5 4B against Qwen2.5 7B" below |
| Speech to text | Whisper small via faster-whisper (float16 on GPU, int8 on CPU) | Fast and accurate; works on any machine through the CPU fallback |
| Wake word | openWakeWord: a pre-trained phrase for v0.1, a custom "Hey Red" model later | Free, open source, low CPU |
| Text to speech | Piper | Free, local, fast |

**Developer machine:** Windows 11, AMD Ryzen 7 7735HS, RTX 4050 laptop GPU (6 GB VRAM), 16 GB RAM, Python 3.11.9. With 6 GB of VRAM, the 7B model and Whisper on the GPU at the same time is tight, so tests run Whisper on the CPU.

**Data folder on this machine:** `RED_HOME = D:\RED`. The repo is `D:\RED\red`, the venv is `D:\RED\.venv`, and Ollama v0.40.11 with Qwen2.5 7B, Qwen3.5 4B, Qwen3.5 2B and Qwen2.5 3B is already downloaded. The full `RED_HOME` layout is in the README.

### Qwen3.5 4B against Qwen2.5 7B (2026-11-09, plan.md task 4, second plan)

Measured on this laptop (RTX 4050 6 GB, Ryzen 7 7735HS, 16 GB), Ollama 0.40.11, Q4_K_M, Qwen3.5 with thinking off (`"think": false`). The hidden Red was stopped while measuring.

**Picking Red's tools.** Every real-model integration case (149: `test_integration_llm`, `_c_tools`, `_f_tools`, `_g_tools`, `_play_online`, `_conversation`), twice each, after the prompt and description fixes below:

| | Qwen3.5 4B | Qwen2.5 7B |
|---|---|---|
| Correct, run 1 / run 2 | 148 / 148 (and it passes a case the 7B is expected to fail) | 149 / 149 |
| The miss | "Red you just open chrome. I told you to open YouTube": the right call followed by junk ("```json {..." repeated), so it didn't parse. Fixed afterwards in `Router.parse` (first JSON object wins); the suite then passes on the 4B too | none |
| Whole suite | 116 s | 179 s |

Before the fixes the 4B got 142 of 148: it sent "open YouTube" to `open_app`, answered "open it" and "mail Priya about lunch" with a question, and once said `which: "all"` for "cancel my reminder to call mom". Fixes that help any model: router examples for the log's misses ("Open YouTube.", "Can you just read my screen? What's going on?", "open the second one", a mail), `open_app` says websites aren't apps, `compose_mail` says to write a short subject and body instead of asking, a rule that a repeated or corrected request is a command, `cancel_reminder` never cancels everything unless you said all, and "open it" tests now carry the find_file conversation they always follow.

**The user's 47 logged sentences** (`commands.jsonl`, no conversation context): the same tool for 38. Of the 9 that differ, the 4B is better on "What are you doing right now?" (the 7B read the screen), reasonable on "I'll tell you to turn off my laptop after 3 hours, will you do that?" (asks instead of scheduling), worse on "What's the latest iPhone?" (`answer` instead of `look_up`), and the rest are answer-versus-look_up or follow-ups that need the conversation.

**Speed on the GPU:**

| | Qwen3.5 4B | Qwen2.5 7B |
|---|---|---|
| Route one of the 47 sentences | median 0.76 s, max 1.17 s | median 1.30 s, max 2.08 s |
| Short answer ("explain recursion") | 0.94 s | 1.68 s |
| Long answer (the Punisher "in detail") | 4.8 s | 9.9 s |
| Chat reply | about 0.9 to 1.0 s | about 1.8 to 2.6 s |
| `describe_screen` with a new screenshot each time (OCR 0.7 s + model) | 2.3 s | text only |

Answers: both fine on facts; the 4B gives a little more. On the detailed Punisher story both invented details (the 4B said Wilson Fisk killed Frank's family; the 7B invented a "Winter Soldier" second season), the 7B more. Time to first word is the answer time plus Piper until task 6 streams it.

**CPU only (`num_gpu` 0), 8 commands, all routed right by every model:**

| Model | Route median | Prompt re-read per call |
|---|---|---|
| Qwen2.5 3B | 1.38 s | 0.23 s (cached) |
| Qwen2.5 7B | 3.07 s | 0.46 s (cached) |
| Qwen3.5 2B | 3.34 s | 2.47 s |
| Qwen3.5 4B | 8.30 s | 6.05 s |

Ollama 0.40.11 doesn't reuse the cached system prompt for Qwen3.5 (its hybrid layers keep a state, not only a KV cache), so every command re-reads about 3,500 router tokens. On a GPU that costs little; on a CPU it breaks the 5 s limit. So `red/hardware.py` gives PCs with no GPU Qwen2.5 3B, not Qwen3.5 (the plan's table said Qwen3.5 2B or 4B). Revisit when Ollama caches Qwen3.5 prompts (task 6 looks at caching).

**Decision:** Qwen3.5 4B is the default (`DEFAULT_MODEL`, `.env.example`, README). It isn't clearly worse at picking tools (148 against 149, then equal after the parse fix) and is 40 to 50% faster on a GPU. Qwen3.6 has no small models yet (only 27B and 35B-A3B, April 2026), so nothing to switch to. Qwen3.5 9B is pinned for 8 GB+ GPUs but untested here (it doesn't fit a 6 GB card next to anything else).

**Other notes.**
- Qwen publishes no GGUF repo for Qwen3.5; the llama.cpp fallback uses Unsloth's (`unsloth/Qwen3.5-4B-GGUF` and friends), pinned by commit and SHA-256. That fallback is text only: no mmproj file is pinned, so `describe_screen` sends pictures only through Ollama.
- `describe_screen` sends a JPEG, at most 1024 px wide (about 50 KB), held in memory only, never saved. The first picture after the model loads takes about 10 s more (the vision part loading); after that it's about 1.6 s.
- Ollama keeps a model loaded with the options it was loaded with: after the CPU-only runs, later requests reused the CPU copies (0 MiB on the GPU in `/api/ps`) until they were unloaded. Anyone benchmarking with `num_gpu` 0 should unload afterwards (`keep_alive: 0`).

---

## 6. Five-day plan

| Day | Work | Status |
|---|---|---|
| 1 | Foundation: repo, config, LLM backends, tool interface, router | ✅ Done |
| 2 | Actions, confirmation, allowlist, command log | ⏳ Track A |
| 3 | Whisper, Piper, shortcut, spoken confirmation | ⏳ Track B |
| 4 | Wake word (B) and overlay (C) | ⏳ Tracks B and C |
| 5 | Music and repo sync (C), setup docs, end-to-end test, first release | ⏳ Track C, then integration |

**If time runs short:** cut the wake word and keep the shortcut. Cut the overlay and use a simple notification. Keep the shutdown, folder and repo sync features, since they're the most useful.

Days 2 to 5 now run as three parallel tracks (section 8) followed by one integration step.

---

## 7. Specs

### 7.1 Actions and confirmation (Track A)

| Tool | How it works | Safety |
|---|---|---|
| `open_folder` | Downloads, Documents, Desktop, Pictures, Music and Videos are found through the Windows Known Folder API (`SHGetKnownFolderPath`), so folders moved to OneDrive still work. Other folders come from the allowlist. Opens with `os.startfile`. | Only known or allowlisted folders. If Red can't match the name, it says so instead of guessing. |
| `open_app` | App names map to commands in the allowlist. Built-in defaults: Notepad, Calculator, File Explorer and Task Manager. | Only allowlisted apps. The model's text is only a lookup key, never a command line. Launch without a shell. |
| `open_url` | Opens in the default browser. | `http` and `https` only, already enforced by the schema. |
| `shutdown`, `restart` | `shutdown /s` or `/r` with `/t <seconds>`. Red says the exact time it will happen. | Destructive, so it asks first. The delay is capped at 24 hours. A new schedule replaces the old one (`shutdown /a` first). |
| `cancel_shutdown` | `shutdown /a`. | Runs at once with no confirmation. Says so if nothing was scheduled. |

**Confirmation:**
- Red repeats the action in plain words: `Shut down in 2 hours (at 11:40 PM)? [y/N]`
- Only a clear yes confirms: `y`, `yes`, or a yes inside a sentence ("yeah, go ahead", "sure, do it") with no no-word in it. "No", "don't", "stop" or "cancel" anywhere cancels, and so do unclear answers ("okay", "maybe") and no answer within 30 seconds. Harmless tools never ask, even for "can you ...?" (changed 2026-11-08 after the voice test).
- Typed confirmation comes first. The spoken version (Track B) plugs into the same `ask` function.

**Allowlist:** `RED_HOME\config\allowlist.toml`, copied from `allowlist.example.toml`:

```toml
[folders]
projects = 'D:\Projects'

[apps]
"vs code" = "code"
```

**Command log:** each action Red runs or cancels is one JSON line in `RED_HOME\logs\commands.jsonl`, with the time, the command text, the tool, its arguments, whether you confirmed, and the result.

**CLI:** `python -m red` runs actions for real. `python -m red --dry-run` keeps the Day 1 behaviour and only shows the tool calls.

#### Browsers and the "open YouTube" fix (2026-11-09, plan.md task 1, second plan)

**What went wrong at 23:37.** Routing was right (`open_url`, `https://www.youtube.com`), but Red brought an idle Edge window ("New tab - Personal") to the front each time, so the user saw a blank tab.

**Why Edge stayed on "New tab" (checked by hand on 2026-11-09, hidden Red stopped, with the user's OK).** Edge was never asked to open anything. On this PC the real default browser is **Chrome**:
- Newer Windows 11 builds keep the default in `HKCU\...\UrlAssociations\https\UserChoiceLatest\ProgId` (`ChromeHTML` here) and leave the old `...\https\UserChoice` key stale (`MSEdgeHTM` here). The shell's own answer (`AssocQueryStringW`, `ASSOCSTR_EXECUTABLE` for `https`) is `chrome.exe`.
- `webbrowser.open` goes through the shell, so YouTube opened as a tab in the Chrome window ("AryanLanke - Google Chrome" became "Untitled", then "YouTube - Google Chrome" after 0.6 s). That's why the user said "you just open chrome".
- `red.windows.default_browser_exe()` read only the stale `UserChoice` key, so the watcher looked for `msedge.exe` windows. With `reuse=True` it fronted the topmost Edge window after 1.2 s, the "New tab" window, which covered the Chrome window showing YouTube.
- Starting `msedge.exe https://www.youtube.com` directly works: a new window appears hidden as "Untitled - Personal - Microsoft Edge" and becomes visible as "YouTube - Personal - Microsoft Edge" after 1.4 s.

**What changed.**
- `default_browser_exe()` asks the shell first, then reads `UserChoiceLatest\ProgId`, then `UserChoice`.
- `RED_BROWSER` (`chrome` by default; `edge`, `firefox`, `default`): `red/browser.py` finds the browser through App Paths and starts it with `Popen([exe, url])`, no shell. Only plain http(s) addresses with no spaces, quotes, `<` or `>` reach its command line, so a URL can never become a switch like `--gpu-launcher`. If the browser isn't installed (or is a Store build), the Windows default opens the page.
- `open_url` and `web_search` take an optional `browser` (chrome, edge, firefox). The tool keeps the model's pick only if the user's own words name that browser (`browser.from_words`): Qwen2.5 7B adds `"browser": "chrome"` to a plain "Open YouTube.", and misses it for "Red you just open chrome. I told you to open YouTube".
- Fronting a browser window: it must be new or have had a different title at some point since the launch. One whose title names the site (`site_name("www.youtube.com")` is `youtube`) or the search words is fronted at once; a changed one without them after 2.5 s. A browser window whose title never changed is never fronted; if none qualifies in 5 s, Red logs it and fronts nothing.
- Router prompt: one rule, "a browser named in the command only fills the browser argument; it never changes the tool". An example line ("search the web for cheap flights in Edge") fixed one more search case but turned "find the folder called holiday photos" into `open_folder` (temperature 0, so it's repeatable), so it was left out.

**Checked.** Unit tests with a fake desktop whose titles change after the launch, and `FakePopen` checking `[chrome.exe, url]`. Real model: all 143 integration cases pass, including "open YouTube", "open YouTube from Chrome", the three 23:37 lines and "search lofi in Edge". By hand: `python -m red run "Open YouTube."` opened YouTube in Chrome and fronted "YouTube - Google Chrome" 0.6 s after launching.

### 7.2 Voice (Track B)

- Push-to-talk: a global hotkey (default `Ctrl+Alt+R`, set with `RED_HOTKEY`) starts recording. Recording stops after a short silence or a maximum length.
- Wake word: openWakeWord with a pre-trained phrase until a custom "Hey Red" model exists. Use the ONNX runtime, because tflite isn't available on Windows. The wake word pauses while Red is recording or speaking.
- Whisper small through faster-whisper. GPU float16 when CUDA works, otherwise CPU int8. The model loads on first use, falls back to the CPU on CUDA errors, and is stored under `RED_HOME\models\whisper`.
- Piper voice models live under `RED_HOME\models\piper`, pinned and checksum-verified with `red.downloads.download`.
- Spoken confirmation: Red speaks the question, records the answer, and passes the transcript to the same yes check as typed input.

#### Answers that remember the conversation (2026-11-08, plan.md task 6)

- The router sees the last 4 lines of the conversation (`Chat.history()`), in the user message only, so with no conversation routing is exactly as before. "What's that series about?" after talking about Punisher goes to `look_up` with "Punisher web series" instead of `none` asking for the name.
- `answer` and `look_up` get the conversation (`bind_context`) and the user's own words (`set_command`, called by the Executor): the router's `question` can be a paraphrase or even a reply it made up.
- Length follows the request (`assistant.wants_detail`): 2 to 4 sentences normally; "a big summary", "the whole story", "in detail" get 8 to 12 sentences with `max_tokens` 900. In detail `look_up` reads the article's Premise or Plot section (with its season subsections), not only the summary. Tools have a `max_reply` (the Executor used to cut every reply at 300 characters).
- `commands.jsonl` now records what Red said in chat (`result`), with the router's placeholder as `router_reply`.
- Replayed the 2026-11-08 22:21 to 22:24 conversation against the real model: "what's that web series about" now summarises The Punisher (TV series), "I want a big summary ... story thing" gets a 7-sentence story of both seasons (11.5 s), and "what's Punisher about" is about Frank Castle, not the comic character.
- Qwen2.5 7B isn't "untrained", but it's small: context and longer answers help most. A bigger model doesn't fit a 6 GB GPU at a usable speed.

#### Speed (2026-11-08, plan.md task 5)

Every command writes a `Timing` line to `red.log`: listen, transcribe, route, act (or chat), speak, and how long after you stopped talking the action ran and the reply ended.

- **End of speech:** after a 0.8 s pause (`RED_QUICK_END_SILENCE`) Red transcribes what it has. If `smalltalk.sounds_finished()` says it's a whole sentence, recording stops and that transcript is used, so nothing is transcribed twice. After "and", "um", "the" or a comma it waits the full `RED_END_SILENCE` (1.5 s).
- **Reply while launching:** tools hand slow follow-through (waiting for the window, bringing it to the front) to `Tool.finish_later()`, which runs while Red speaks.
- **Whisper base.en against small** (48 clips: 12 of Red's real commands from the log, read by 4 Piper voices; CPU int8, beam 5, VAD on). Not the owner's voice, so accuracy is only indicative:

  | Model | Word errors | Median time | Slowest |
  |---|---|---|---|
  | small | 8.7% | 1.36 s | 2.81 s |
  | base.en | 8.7% | 0.42 s | 0.45 s |
  | tiny.en | 9.9% | 0.23 s | 0.26 s |

  Most "errors" were `3pm` for "3 pm" and place names (Pune). `small` with beam 1 is no faster (1.31 s): the encoder is the cost. This PC now uses `base.en` (`RED_WHISPER_MODEL` in `D:\RED\config\.env`); the code default stays `small`. The wake check already uses `tiny.en` on the owner's real voice, and its transcripts in `red.log` are good.
- **Routing** with the model warm: 0.81 to 0.99 s for short commands (12.9k-character system prompt, cached by Ollama).
- **Budget for "open Edge"** after you stop talking: 0.8 s pause + 0.4 s transcribe + 0.85 s route + 0.06 s launch, about 2.1 s (it was about 3.7 s: 1.5 s pause + 1.3 s + 0.85 s). Check the `Timing` lines after the next voice test.

#### Follow-ups, names and honest answers (2026-11-09, plan.md task 2, second plan)

**a. After an answer, ask if they want more.** After `answer`, `look_up`, `weather`, `news` and `describe_screen` succeed, `VoiceApp._exchange` adds a short question ("Anything more you want to know about it?", the user's wording, then three variations taken in turn, so never the same twice in a row) and keeps listening for `RED_FOLLOW_UP_SECONDS`. No question when the answer already ends with "?", or when the tool failed. The conversation memory keeps the answer without the question. Actions still go quiet. "No", "that's it", "not really", "nope, that's all" or silence ends it (`smalltalk.is_goodbye` learned the last two).

**b. Hearing the names right.** The command transcriber gets faster-whisper `hotwords`: Hey Copilot, Hey Siri, Alexa, OK Google, Gemini, YouTube, Chrome, Edge, Red, then the allowlist's app names and `contacts.toml` names, capped at 250 characters (`stt.command_vocabulary`, `__main__.vocabulary`). Measured with 8 sentences full of these names, spoken by 6 Piper voices (amy, lessac, joe, ryan, alan, jenny_dioco), each clean and with noise about 12 dB below the voice (96 clips), `base.en` int8 on the CPU of this laptop:

| Whisper `base.en` | Names right | Time per clip |
|---|---|---|
| no vocabulary | 135 of 156 (87%) | same (0.45 to 0.9 s, varied with load) |
| `hotwords` | 151 of 156 (97%) | same |
| `initial_prompt` | 151 of 156 (97%) | same |

`hotwords` and `initial_prompt` scored the same, so Red uses `hotwords` (faster-whisper's option for this, already used by the wake word). The time differences between runs were noise from the hidden Red sharing the CPU, not the vocabulary. Without it Whisper wrote "HeyCiri", "Hay Theory", "Syria" and "serial" for Siri, and "Heiko Pilot", "Haco Pilot" and "Jim and I" for Copilot and Gemini. The 5 misses left were all "Heyco Pilot" from the British voices and Ryan, so `stt.fix_names` turns "Heyco/Heiko/Haco Pilot" into "Hey Copilot" (and leaves "the co-pilot landed" alone). The script was a scratch file; to repeat it, synthesize with `red.tts._load_piper`, resample to 16 kHz, and call `WhisperModel.transcribe` with the same options as `Transcriber._run`.

**c. The answer made things up.** Commit `7a2d87d` did cover the router's rewrite: the hidden Red was started at 23:31:29, after it, and `Answer.run` uses the user's words (`set_command`), so the router's made-up `question` ("Hey CD is a voice assistant for Windows and macOS...") is only in the log, not in the answer's prompt. The made-up facts came from the misheard names (b) plus an answer prompt that never said "don't guess". Changes:
- `ANSWER_SYSTEM` and `DETAIL_SYSTEM`: never guess; say plainly "I don't know Hey CD." and answer only what it knows. "What is Hey CD?" now gets exactly that.
- Router rule: products, apps, AI assistants or gadgets that may be new (2024 on), and "latest", "newest" or "compare" questions about products, go to `look_up`.
- `look_up` takes `others` (up to 2) for comparisons and reads each article (1,200 characters each). It finds articles better: an exact title from the title search, otherwise Wikipedia's full-text search ("latest iPhone" found Ladik Lake before, now "IPhone": "the iPhone 17 and iPhone 17e"). Wake phrases map to their articles ("Hey Copilot" to Microsoft Copilot, "OK Google" to Google Assistant), because the search found Google Assistant and Google Search for them. The summary prompt says never to add facts that aren't in the text.
- Replayed the 23:41 line with the names heard right: `look_up` with topic "Hey Copilot" and others "Hey Siri", "Ok Google", answered from the Microsoft Copilot, Siri and Google Assistant articles. One weakness left: it still repeated the user's own "Copilot is Windows-only" claim. With the names misheard ("Heiko Pilot", "Hey CD") it now says the articles don't cover them instead of inventing.

**Checked.** `tests/test_voice_app.py` (an answer asks and keeps listening; no repeat in a row; no second question; "no" ends it; actions still go quiet), `tests/test_stt.py` (hotwords reach Whisper, the Copilot fix-up), `tests/test_g_online.py` (title and full-text search, comparisons, wake phrases). Real model: all 145 integration cases pass, with the 23:41 comparison and "What is Hey CD?" added. The Everest case had a test bug (it checked `question` when `look_up` puts the name in `topic`), fixed.

#### Instant common commands (2026-11-09, plan.md task 5, second plan)

`red/fastpath.py` runs first in `Router.route()`. When the whole sentence (after "hey Red", "can you", "please", "for me" and the like are taken off) is one of a fixed set of forms, it returns the tool call itself; anything else goes to the model as before. The call goes through `Router.parse()` with the same schema checks, and the Executor asks the same confirmations, but no destructive tool is in the fast path at all (shutdown, restart, sleep and the Recycle Bin always go to the model).

- "open X" (also launch, start, go to, "open X in/from Chrome"): an allowlisted app, a known app (`apps.KNOWN_APPS`), a Windows or allowlisted folder, a site from a fixed list (YouTube, GitHub, Gmail, Netflix and so on) or something that looks like a domain ("github.com"). "Open YouTube in Edge" only works for sites. "Open it", "open my resume", "open Bluetooth settings" go to the model.
- volume up, down, mute, unmute, "set the volume to 30"; pause, resume, play (alone), next, previous, stop the music; lock; what time is it, the date, the battery; take a screenshot.
- "play X" and "put on X" (to `play_online`); "search youtube for X", "search X on YouTube", "google X", "search the web for X", with "in Edge". A search with "my", "file", "tell me", "and", or a question word goes to the model, so "search online for the mars rover and tell me about it" still becomes `look_up`.
- Names keep the user's capitals ("Opening Edge."); known folders get Windows' names ("Documents").
- Speed: about 0.03 ms a sentence. Measured with the real `VoiceApp` (Piper audio of "Open YouTube.", real `base.en` with the pause check, the real router and action, a silent speaker): done about 1.26 s after you stop talking with the fast path (0.8 s of quiet, 0.45 s pause check, 0.00 s route, 0.01 s act), about 2.5 s through Qwen3.5 4B, and 2.65 s in the 23:37 test with the 7B. The pause check's transcription (0.45 to 0.9 s on the CPU) is now the biggest part.
- Real model: all 149 integration cases pass through the fast path plus the model, in 64 s against 116 s for the model alone.

#### Speaking while the model writes, and cutting in (2026-11-09, plan.md task 6, second plan)

- **Streaming.** `OllamaClient.stream_json` and `OpenAICompatClient.stream_json` (Ollama NDJSON, or server-sent events) yield the reply as it's written. `red/speech.py` reads the `answer` or `reply` string out of the JSON as it arrives (`JsonFieldReader`, escapes split across pieces included) and stops at its closing quote, closing the connection so Ollama stops writing (that also cuts off Qwen3.5's occasional junk after the JSON). `sentences()` yields each sentence as soon as its end and a space have arrived, and keeps "Mr.", "Dr.", "U.S.", "e.g." and "8,848.86" whole. `SpeechStream` synthesizes the next sentence with Piper while the last one plays. Used by `answer`, `look_up` (it says "From Wikipedia:" first), `describe_screen` and chat, through the stream `VoiceApp` opens for each command. The schemas and system prompts are the same as before, and the tools still return the whole text, so the log, memory and typed mode don't change. After a streamed answer only the follow-up question is said.
- **First word**, measured through the real `VoiceApp` with Qwen3.5 4B on the GPU, real Piper and a silent player that takes as long as the audio (from the end of your words, not counting the end-of-speech pause):

| | Streaming | Before |
|---|---|---|
| "Tell me the whole story of the Punisher web series in detail" | first word at 2.17 s, then 62 s of story | 5.79 s |
| "explain recursion" | 1.43 s | 1.84 s |
| "I'm feeling lonely." (chat) | 1.81 s | 2.51 s |

  What's left is routing these through the model (0.8 to 1.2 s), the first sentence (0.3 to 0.6 s) and Piper for it. `Timing` lines in `red.log` now say "first word at".
- **Prompt caching.** Every system prompt is a constant (chat puts the time in the user message), and the router's conversation context goes in the user message too. Ollama's timings: Qwen2.5 7B reuses the cached router prompt (2,148 ms the first time, then 84 to 117 ms); Qwen3.5 4B re-reads its 3,500 tokens every time (336 ms, then about 200 ms each), the same limit as on the CPU (progress.md 5). On the GPU that's 0.2 s a command; nothing more can be done from Red's side with Ollama 0.40.11.
- **Cutting in.** While Red talks (a streamed answer, chat, or any spoken reply), `VoiceApp` calls `listener.allow_interrupt(True)`: the wake word listens again, and "Hey Red" or the hotkey calls `VoiceApp.interrupt()`, which cancels the `SpeechStream` and the speaker. Red then chimes and listens for the next command at once. During recording and confirmations the wake word stays off as before, and an interrupt never starts a second command. Tested with fakes; the user should try it by voice (it relies on the laptop microphone hearing "Hey Red" over Red's own voice).

#### Mail and calendar (2026-11-09, plan.md task 7, second plan)

**The user's choice:** read back once before sending an email or deleting a calendar event, and no questions for anything else. So `send_mail`, `reply_mail` and `calendar_cancel` are `destructive` ("Sending to Mom: I'll be late. Send?", "Deleting Dentist at 4 PM today. Delete?"); `check_mail`, `read_mail`, `calendar_events`, `calendar_add` and `calendar_move` just happen.

- **Sign-in** (`red/google_auth.py`): `python -m red google-login` runs Google's installed-app flow with PKCE and a one-time loopback address (`http://127.0.0.1:<port>/`), and saves the refresh token in `RED_HOME\config\google-token.json` (outside the repo; `.gitignore` also lists `google-token.json`, `google-client.json` and `client_secret*.json`). `google-logout` revokes and deletes it. The user needs their own Desktop OAuth client in `RED_HOME\config\google-client.json` (README says how); Red ships none. Scopes: `gmail.readonly`, `gmail.send`, `calendar.events`, `contacts.readonly`.
- **No Google packages.** The plan suggested the pure-Python Google client libraries, but `google-api-python-client` and `google-auth-oauthlib` bring about 15 dependencies, some with compiled parts (`charset-normalizer`, `protobuf`'s upb) that Smart App Control could block. The REST APIs are plain HTTPS and JSON, so Red uses urllib only: nothing new to install or block. `GoogleApi.request` only accepts `https://gmail.googleapis.com/`, `https://www.googleapis.com/calendar/` and `https://people.googleapis.com/` addresses, with an 8 s timeout and a 2 MB cap.
- **Mail** (`red/tools/gmail.py`): "any new mail?" reads the inbox's unread count and the newest three senders and subjects (the reply is built from Google's data). "read my mail from Rahul" finds the newest match (the contact's address, else the name, inside quotes in the Gmail search) and the local model summarises its text (quoted earlier mail dropped, 4,000 characters at most). "reply saying ..." answers the mail just read, in its thread (`In-Reply-To`, `References`, `threadId`). "mail Mom that ..." sends a new one. Recipients come from Google Contacts (cached for an hour), then `contacts.toml`, or a valid address; anything else fails in `prepare()` before Red asks. Subjects lose line breaks, so no header can be added. `compose_mail` (the mailto: draft) stays, and "draft an email" still goes to it.
- **Calendar** (`red/tools/calendar.py`): the model fills only checked values (day: today, tomorrow, a weekday or YYYY-MM-DD; time: 24-hour HH:MM). "move my 5 pm to 6" keeps the event's length; when the model leaves out the event's time, the tool takes it from the user's words (`spoken_times`). Event ids from Google must look like ids before they go into an address. Two events at the same time: Red asks which.
- **Executor**: a destructive tool's optional `prepare(**args)` runs before the confirmation, so "mail Priya" with no address for Priya says so instead of asking "Send?".
- **The tools appear only after signing in**: `default_registry()` adds them when the token file exists, so the router prompt (and routing) for everyone else is unchanged.
- **Checked:** `tests/test_google.py` with a fake API: the sign-in over a real loopback request and a fake token server, token refresh, only Google addresses, mail counts, the Gmail search staying two quoted phrases, header injection, a send and a calendar delete only on "yes", unknown recipients refused before asking. Real model (`tests/test_integration_google.py`, Qwen3.5 4B): all 10 commands from the plan route right ("any new mail?", "read my mail from Rahul", "reply saying I'll come tomorrow" after reading, "mail Mom that I'll be late", the four calendar lines, and "draft an email" to `compose_mail`). The user tests the real sign-in by hand.

#### Answer only the owner: voice match (2026-11-09, plan.md task 8, second plan)

- **Model:** CAM++ from 3D-Speaker (`3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx`, 29.6 MB, from the k2-fsa/sherpa-onnx speaker-recognition release), pinned by SHA-256 and downloaded into `RED_HOME\models\wakeword`. It runs on onnxruntime, which Red already uses, so Smart App Control has nothing new to block. Input: 80-band log-mel features ("fbank"), mean over time removed (its metadata says `global-mean`); `voice_match.fbank()` computes them with numpy like Kaldi (25 ms frames every 10 ms, Povey window, pre-emphasis 0.97, mel 20 Hz to 8 kHz, float32-epsilon floor). Output: a 512-number embedding.
- **Setup:** `python -m red voice-setup` now records "Hey Red" 10 times (was 6). The same recordings teach the words (as before) and the voice: their average embedding is saved in `owner_voice.json` (numbers only, never audio), with a personal threshold: each recording against the average of the others (leave one out), the weakest minus 0.10, kept between 0.40 and 0.75.
- **At each "Hey Red":** `HeyRedDetector` checks the voice only for clips whose words already matched, so it costs nothing the rest of the time. Not the owner: score 0, logged as "Voice match: 0.31 (not you, ignored)". Too short to judge, or the model failing: let through. The hotkey never goes through it. Cutting in while Red talks uses the same detector, so only the owner can interrupt too.
- **Settings:** `RED_VOICE_MATCH=on|off` (off until the user has tried it with another person), `RED_VOICE_MATCH_THRESHOLD` (empty: the personal threshold; else the user's value; the fallback is 0.60).
- **Measured** with Piper voices (owner: 10 enrolment clips at different speeds and noise; tests: 8 more with room noise; others: 5 other Piper voices and 30 LibriTTS-R speakers, 80 clips):

| Owner | Owner's clips | Others, average and highest | At 0.60 |
|---|---|---|---|
| en_US-joe | 0.61 to about 0.8 | 0.20, 0.43 | no owner clip refused, no other voice let in |
| en_US-amy | 0.73 to about 0.85 | 0.32, 0.74 | no owner clip refused, 6% of others let in |

  The others that came close to Amy were LibriTTS-R speakers, all made by one multi-speaker TTS model, so they're probably more alike than real people. Real microphones will score the owner lower than these clean clips, which is why voice-setup sets a personal threshold. The first version floored the log energies at float64's epsilon; silent frames then pulled the features about, and switching to Kaldi's float32 floor improved the separation (Joe's highest other voice went from 0.57 to 0.43).
- **Checked:** `tests/test_voice_match.py`: fbank shape, mean and loudness, the profile and threshold, settings, the detector asking only when the words matched, voice-setup saving the voice, and the real model on saved recordings (`tests/fixtures/voice/*.wav`, Piper clips, about 300 KB): both owner clips accepted, Ryan, Alan and a LibriTTS-R speaker refused (runs only if the model is already downloaded). **Still to do by the user:** voice-setup in their own voice, `RED_VOICE_MATCH=on`, and a try with another person saying "Hey Red".

#### Several things in one sentence (2026-11-09, plan.md task 9, second plan)

- **How:** not a new model output format (that would change every single-command route), but `split_commands()` in `red/router.py`: a sentence is cut where "and", "then", "and then" or a comma is followed by a command word (open, search, play, mute, lock, check, read, set, remind, ...), into at most 4 parts. `Router.route_many()` routes each part (fast path first, then the model) with the same schema checks. If any part comes back as chat (`none`), or there are more than 4 parts, the whole sentence is routed as one command, as before. "search for cats and dogs", "play rock and roll" and "search online for the mars rover and tell me about it" ("tell me" isn't a split word) stay whole.
- **Running:** `VoiceApp._run_steps` (and typed `run`) execute the parts in order through the Executor, so each destructive part asks its own question. The first failure or "no" stops the rest, and Red says which step ("Step 1, open Spotfy, didn't work: ... I stopped there.", "I didn't do step 2, shut down in 2 hours."). The replies are said together; windows that steps opened are brought to the front in order while Red speaks; each step is its own line in `commands.jsonl`.
- **Checked:** unit tests for the splitter, `route_many`, and running, stopping and confirming steps. Real model (Qwen3.5 4B): "Open Chrome and search flights to Delhi" (both by the fast path), "mute and lock the PC", "open my downloads folder and then play Believer", "set a timer for 5 minutes and remind me to call mom at 6 pm", and "check my mail and read today's calendar" (with the Google tools) all split right; the two sentences that must stay whole stay whole. All 166 real-model cases pass.

#### Waking reliably (2026-11-09, plan.md task 1, third plan)

- **Cause, from red.log of the voice test:** Whisper wrote "Hey Red Red Red Red Red Red Red" and "Hey Red, hey Red, hey Red" for a plain "Hey Red", and `match_score` gave 0 to anything over 4 words. A clip over 1.6 s ("Hey Red, open YouTube") was dropped before Whisper saw it, and a 3-word one scored 0.45, under the 0.5 threshold.
- **Fix** (`red/wakeword.py`): repeats are collapsed first (`collapse_repeats`); a burst of speech over 1.25 s is scored on its first two words only ("head" mode), and a burst over 1.6 s has its first 1.3 s checked once. The guards stay: a pause before, the phrase at the start. Cost: every long burst after a pause now costs one Whisper tiny.en run on 1.3 s of audio (about 0.3 s on two CPU threads), where before it cost none.
- **Piper through the real detector** (Silero VAD + tiny.en, 4 voices): "Hey Red", "Hey Red Red Red", "hey red hey red" and "Hey Red, open YouTube" all wake (1.00); "I saw a red car yesterday", "Tell me about the red planet" and "What is going on today" stay at 0.00. When the speaker pauses after "Hey Red" it counts as a short phrase and the command is a second burst.
- **`python -m red wake-test`** (`red/wake_test.py`) prints each check with its words, score, loudness (peak) and verdict for 30 s, and says if the microphone is quiet. Each check is also logged with its peak in red.log.
- **Not done:** the words said right after "Hey Red" in the same breath are not kept as the command; Red still beeps and listens again. That needs the detector to hand its audio to the recorder (`Listener` and `record_command`).
- **Still to do by the user:** try it by voice. I could only test with Piper voices, not your microphone or your accent.

#### "Hey Red" on the user's own voice (2026-11-13, plan.md C1, fifth plan)

- **Corpus** (`red wake-test --record`, `red/wake_corpus.py`): 30 takes of "Hey Red", 10 of "Hey Red, open YouTube" and 2 minutes of normal talk, in `RED_HOME\cache\wake-corpus` (never in git). `--replay` runs the real detector over it; each run appends to `logs\wake-replay.jsonl`.
- **What the misses were:** Whisper wrote the user's "Hey Red" as "Headed" (most often), "Headered", "Head in", "Hitter", "Here at…"; the user pauses between "Hey" and "Red", and a 0.3 s gap split it into two clips that each failed; some takes peaked at 0.01 and the VAD (needs 0.5) never started a clip.
- **Each step, measured** ("Hey Red" / with a command / false wakes in the talk):

| Step | Hey Red | + command | False |
|---|---|---|---|
| Before | 16/30 | 5/10 | 0 |
| Louder clips before Whisper (peak 0.3) alone | 18/30 | 5/10 | 0 |
| VAD start 0.35 alone | 16/30 | 6/10 | 0 |
| Clip ends after 0.5 s of quiet, not 0.3 s, alone | 20/30 | 5/10 | 0 |
| All three (committed) | 20/30 | 6/10 | 0 |
| + `--learn` ("headed", "here at" from the takes) | 23/30 | 9/10 | 0 |
| + a one- or two-word clip within 2 letters of a learned phrase, same first letter | **25/30 (83%)** | **9/10** | **0** |

- **Checked against red.log:** re-scoring all ~2,000 logged checks with the learned phrases wakes only the user's own tries. A looser close-match rule had also woken "The rest of us are scared to open" ("the rest" ≈ "here at"), hence the same-first-letter and whole-clip rules.
- **Beam 1 instead of 5** for the wake check: 0.49 s instead of 0.66 s per check, but 23/30 instead of 25/30. Kept beam 5.
- **Left:** two takes too quiet to make out (peak 0.03 and 0.01), one where "Hey" never registered, one heard as "Hello" (too common to accept). The numbers are on the same takes `--learn` learned from, so the user's live 100 tries are the real test.
- A one-breath wake now fires about 0.2 s later (the 0.5 s pause).

#### A personality, not a professional (2026-11-13, plan.md A1, fifth plan)

- `CHAT_SYSTEM` (`red/chat.py`) is a character: dry humour, opinions, reacts before answering, teases lightly, honest about limits, warm when it matters, with six example exchanges. It never offers what it can't do, and never brings up meetings, mail or to-dos unasked. `ANSWER_SYSTEM` answers "like a smart friend". Small talk lost its help-desk lines ("What's up?", "Anytime!").
- The user's own tuning: `RED_HOME\config\personality.txt` (the Red app, General page, up to 800 characters). `make_chat()` puts it after the fixed prompt, so Ollama's prompt cache still matches up to that point. A file, not a `.env` line, because it's free text.
- Pauses (`red/speech.py`): a comma 0.15 s, a sentence 0.3 s, "..." or a dash 0.5 s, counting Kokoro's own 0.12 s breath. A trail-off is its own piece, and a sentence over 90 characters is cut at commas (no pieces under 20 characters).
- Real model (qwen3.5-4b), 5 chat lines, first sentence written: **old prompt median 0.69 s (0.53–0.93), new 0.59 s (0.56–0.77)**. The longer prompt costs nothing measurable.
- The first draft copied an example line word for word and then offered to order a pizza. The examples are now marked "attitude only", and "never offer what you can't do" is a rule. A 4B model still sometimes sits on the fence when asked for an opinion ("tabs or spaces?").
- Samples for the user: `RED_HOME\cache\samples-companion\a1-personality-*.wav`.

#### Long-term memory (2026-11-13, plan.md A2, fifth plan)

- **Files, never in git** (`RED_HOME\memory\`, also in `.gitignore`): `profile.md` (a short profile; Red reads the name from its `Name:` line), `facts.jsonl` (one fact per line in the user's own voice, "My sister is Priya.", with when, the source (told, learned or app) and the sentence it came from), `state.json` (whether Red has asked the name), `pending.jsonl` (sentences waiting for the learner, so a restart loses nothing).
- **The name:** until the profile has one, Red asks once ever, at the end of a chat reply that doesn't already ask something: "By the way, what should I call you?". The answer ("Aryan", "it's Aryan", "I'm Aryan") or "call me Ari" at any time is caught before the router (`Chat.take_name`). "Hi" becomes "Morning, Aryan! What's up?"; the chat prompt says to use the name now and then, not in every sentence.
- **Tools:** `remember` (refuses passwords, codes and cards), `what_you_know` (a summary, or the model answers from memory only), `forget` (destructive: asks once; "that" is the newest fact, "everything" all facts, otherwise the best word match; it finds the fact before asking, so it never asks about something it doesn't remember).
- **Learning:** `Chat.reply` queues what the user said; the `Learner` thread asks the model once Red has been quiet for 20 s (`EXTRACT_SYSTEM`, at most 3 facts, about 0.8 s). Facts are put back in the user's voice (`first_person`: "Aryan is building … his project" became "I'm building … my project", so no guessed pronoun is ever kept). Learned facts never keep an address, email or phone number; nothing ever keeps a password, code, PIN, card, bank or ID number.
- **Prompt:** the profile goes after the fixed chat prompt and the personality (rarely changes, so the cache holds); the 5 facts sharing the most words with the sentence (and the last two lines) go at the top of the chat prompt. Word overlap only: no embeddings until that's measured as too weak.
- **Measured on the real model (qwen3.5-4b):** 14 sentences routed right (remember ×4 including a plain "my sister is Priya", what_you_know ×3, forget ×3, and chat, look_up, set_reminder and open_app untouched). The story "my sister is Priya", restart, "what's my sister's name?" answers "your sister is Priya". Chat first sentence: **0.47 s median with memory, 0.41 s without** (5 lines each).
- **Tests** never touch the user's memory: `tests/conftest.py` points `memory_dir` at the test's tmp folder and stops the learner thread from starting; tools without `bind_memory` refuse.
- Also from this run: without being told, the character said it "can't play tracks". `CHAT_SYSTEM` now lists what Red can do.

#### Hello, not briefings (2026-11-13, plan.md A3, fifth plan)

- `red/greeter.py` polls every 10 s from `VoiceApp.run` (voice and background mode, not typed). Away means 30 minutes with no keyboard or mouse input (`GetLastInputInfo`, so a locked PC counts). Back means input in the last 15 s.
- When: the day's first hello on Red's first check (sign-in or a start) or on coming back on a new day (the day turns at 4 AM). "Welcome back" after 30+ minutes away. Never at midnight while you keep working, and only once a day across restarts (`RED_HOME\memory\greetings.json` keeps the day and the last 8 lines, so yesterday's line doesn't repeat).
- Never queued: `VoiceApp.greet` tries the command lock without waiting; busy means no hello. Blocked (full screen, a game, a presentation) means no hello, and none later.
- Chatty adds a one-liner at most once an hour: late at night (midnight to 4 AM: "It's 2 AM, Aryan. You're still at it?") or after 2 hours at the PC without a 30-minute break.
- Tests use a fake clock and fake idle time: a simulated day (9 AM start, a coffee break, lunch, a 45-minute meeting, evening) gets exactly 1 hello and 2 welcome-backs. No line mentions meetings, mail, to-dos, news or reminders (a test checks every line).
- **Limit found:** the microphone consent store (`CapabilityAccessManager\ConsentStore\microphone`) has no usage recorded on this PC, desktop or packaged, so "another app is using the mic" (a call) always reads as no. The full-screen check works.

#### The chat window (2026-11-13, plan.md A4, fifth plan)

- `red/chat_window.py`: a frameless window on Qt's thread, reached from any thread through `ChatUI` (a bridge QObject moved to Qt's thread, signals in). It needs the Qt overlay (glow or card); with `RED_OVERLAY=off` or `notify` there's no window, and "open chat" says so.
- **One conversation:** typed messages run `typed_turn` on a worker thread (name capture, small talk, `route_many`, the Executor with its confirmations, `Chat.reply` for chat) under the voice loop's `_turn` lock, so a typed and a spoken turn never overlap. The reply is shown, not spoken. Spoken turns are mirrored from the voice loop's own prints (`You said:`, `Red:`, `Red (hello):`, `  Red asks:`, and 5-space detail lines); a test pins those prints in `red/__main__.py`.
- **Code:** fenced blocks (three backticks) become blocks with Copy (clipboard) and Save (a Save dialog in `Documents\Red Code`, which asks before replacing a file). Code keeps its lines (no wrap, sideways scroll) and is never run.
- **Drafts:** a `Line` with an action gets a Send button (one click), and `run_action` sends it through the Executor, so a destructive tool still reads back once.
- **Look:** milky glass (246, 246, 250 at 95%), a faint wash of the glow's colours across the top, no border, square corners (`DWMWCP_DONOTROUND`), and a blur-behind via `SetWindowCompositionAttribute` (best effort, signed user32). A test checks the outermost pixel equals the glass just inside (no rim).
- **Hotkey:** its own `pynput.GlobalHotKeys` (`RED_CHAT_HOTKEY`, default Ctrl+Alt+Space), so session 1's `listener.py` is unchanged. Esc or ✕ hides it.
- **Routing (real model):** "open chat", "open the chat window", "let me type to you", "show me the chat" → `open_chat`; "let's chat" and "let's talk" stay conversation; WhatsApp, Discord, Telegram, Spotify → `open_app`. The first description named WhatsApp as a "not this" example, and the model then refused to open WhatsApp at all. Don't name other apps in a tool description.

#### Plugins (2026-11-13, plan.md B1, fifth plan)

- A plugin is a folder: `plugin.toml` (`name` lower case, `version`, `description`, `author`, `needs`, optional `default_on = false`) and `tools.py` (Tool subclasses, or a `tools()` function that returns them). Classes starting with `_` are helpers, not tools.
- Where: `red/plugins/<name>/` (Red's own, loaded from the package so an update reaches them) and `RED_HOME\plugins\<name>\` (the user's, winning over a built-in of the same name). `red/plugins/` must never get an `__init__.py`: `red.plugins` is the loader module (a test checks).
- On or off: `RED_HOME\config\plugins.json` (`{"off": [...], "on": [...]}`), set from the Plugins page or `python -m red plugins on|off NAME`. Off means `tools.py` is never imported.
- Skipped, with the reason (Plugins page and `plugins list`): no or bad `plugin.toml`, no `tools.py`, an import error or `sys.exit()`, native code (`.pyd`, `.dll`, `.exe`, `.so`: Smart App Control), no tools, or every tool name already taken (Red's own tools always win).
- Safety doesn't change: the model picks a plugin tool and fills its schema-checked arguments, and the Executor confirms destructive ones. The Plugins page reads manifests only, so opening the settings app never runs plugin code.
- Tests never see the user's plugins (`tests/conftest.py` points `user_plugins_dir` and `state_path` at the test's tmp folder).

#### Writing code (2026-11-13, plan.md B2, fifth plan)

- The `code` plugin (`red/plugins/code/`, built in): `write_code`, `fix_code`, `explain_code`. The model answers `{"language", "summary", "code"}`; `JsonFieldReader("code")` streams the code into a chat-window bubble (`ChatUI.stream()`, redrawn every 0.12 s). The spoken reply is one line plus the summary, never code. Without a window the code is saved as a new file in `Documents\Red Code` (`red-code-2.py` rather than replacing).
- Never run: Python is only `compile()`d, to say honestly "it has a syntax error". Fix and explain read the clipboard (`user32` read-only) or a named file in Red Code, Documents, Desktop or Downloads (200 KB at most). A fix goes into the window; the file isn't touched.
- Routing (real model): "write me a python script…", "make a powershell script…" → `write_code`; "explain this code", "what does this code do" → `explain_code`; "fix this", "fix the code I copied, it crashes" → `fix_code`; mail stays `compose_mail`, "open VS Code" stays `open_app`. "Write me a poem" still routes to `write_code`, so the tool answers poems, stories, jokes and messages in words (`CREATIVE_SYSTEM`) unless the request names code.
- **10 requests, qwen3.5-4b** (first code = first code text in the window):

| Request | Lang | Lines | First code | Done | Verdict |
|---|---|---|---|---|---|
| rename photos by date taken | python | 54 | 1.0 s | 11.2 s | ✗ EXIF tag read wrong; renames into the current folder (asks first, at least) |
| is a number prime | python | 20 | 0.6 s | 3.1 s | ✓ |
| 10 biggest files in Downloads | powershell | 4 | 0.6 s | 1.7 s | ✗ stray `` `n `` escapes break the pipeline |
| count words in a file | python | 26 | 0.6 s | 4.5 s | ✓ |
| duplicate files by hash | python | 46 | 0.7 s | 7.6 s | ✓ |
| HTML button that shows the time | html | 29 | 0.7 s | 5.4 s | ✓ |
| CSV to JSON | python | 27 | 0.7 s | 5.4 s | ✓ (file names hard-coded) |
| to-do list class | python | 26 | 0.8 s | 4.7 s | ✓ |
| JS debounce | javascript | 7 | 0.8 s | 1.8 s | ✓ |
| back up a folder to a dated zip | python | 42 | 0.6 s | 7.8 s | ✗ works out the dated name, then writes backup.zip |

  7 of 10 right; every Python file parses. The misses are the longer, Windows-specific scripts, which is where a coder model should help (step 5, not done: it needs a ~5 GB download into the shared Ollama).

#### Coding tools, secrets and the router's context (2026-11-13, plan.md B3.1, fifth plan)

- `red/secrets.py`: DPAPI (`CryptProtectData` in crypt32 through ctypes, no UI, extra entropy) into `RED_HOME\config\secrets\<name>.bin`; a tampered file fails to decrypt; `secrets/` is in `.gitignore`. `red/desk.py`: clipboard write, key presses from a fixed combo (`ctrl+alt+i`), fronting an app's window, `launch(args)` (a list, never a shell) and `open_uri` for fixed schemes.
- The `coding` plugin: `open_in_coding_tool`, `tell_coding_agent` (destructive: the Executor reads the task back once), `what_did_it_change` (read-only `git status`, `diff --shortstat`, `log`). Tools found on this PC and wired in: VS Code (`Code.exe` from `code.cmd`), Qoder (its launcher's `state.ini` names the real `Qoder.exe`; the launcher itself is only an updater), Antigravity IDE (`--goto` like VS Code; its `antigravity-ide.cmd` just runs `cli.js` with Electron), the Antigravity app and Freebuff (no folder argument known, so they only open). More tools and chat shortcuts go in a `[coding.<name>]` table in `allowlist.toml`.
- Only repos.toml project names and files that exist inside them reach a command line (a test checks that `..`, absolute paths and unknown projects launch nothing). The task goes to the clipboard and into the agent's chat as text; Enter is pressed only if the tool's chat shortcut is known and its window is still in front. VS Code's `ctrl+alt+i` is set; Qoder, Antigravity and Freebuff have none yet, so Red says "paste it and hit Enter".
- **A real bug found by the new tool count:** the router's prompt was 4,383 tokens against `num_ctx=4096`, and Ollama cuts the start of an over-long prompt (the router's instructions). It went unnoticed because the cut is small. With the 6 plugin tools (5,204 tokens), "check my repos" and "is red pushed?" went to `list_reminders` or chat. `fit_context` (`red/router.py`) raises `num_ctx` in steps of 2,048 to fit the prompt plus headroom (8,192 for now). Chars per token measured at 3.6. Same sentences after: `check_repos`. First call after the change took 13.5 s (model reload); later calls 0.7–1.4 s, as before.
- Routing, real model (48 sentences across memory, chat, code and coding): all right after two description fixes. "open Freebuff/Antigravity/Qoder" went to `open_app` until the description said "always this, not open_app, for Qoder, Freebuff and Antigravity".
- Tool descriptions are the router's budget: each plugin adds about 130 tokens. Keep new ones short.

#### Spotify, WhatsApp, Discord (2026-11-13, plan.md B3.2-4)

- Spotify: `spotify_search` (`spotify:search:<URL-quoted query>`), `whats_playing` (the title of Spotify's window: "Artist - Song" while playing). "search Spotify for X" used to hit the fast path's web search, which now skips queries naming Spotify.
- WhatsApp: `open_whatsapp`, `whatsapp_message` (destructive, read back; numbers from a `[phones]` table in contacts.toml; `whatsapp://send?phone=..&text=..`, both quoted; Enter only with WhatsApp in front). No message reading.
- Discord: `open_discord` (only `discord://` links saved under `[discord.channels]`), `discord_voice` (your own keybinds from `[discord]`, only with Discord in front). No messages read or sent.
- Router, real model: 14 sentences right. The prompt grew again, so `fit_context` grew the context once more (one 16 s model reload, then 0.9–1.2 s). Each plugin tool costs ~130 prompt tokens; before adding many more, consider routing in two steps.

#### Answer at once, and like a person (2026-11-13, plan.md 0.3 lane 2 tasks 2 and 4, night 1)

- **Why the router took 4 to 32 s:** `OllamaClient.warm()` (the keep-warm ping every few minutes) loaded the model at Ollama's default 4,096 tokens; the router, at 8,192 since the plugins, reloaded it on the next command and read its whole 6,300-token prompt again. Before the plugins (prompt under 4,096) routes were 0.9-1.8 s. `warm()` now sends the client's own options (`num_ctx`), so the model stays loaded at one size.
- **Talk skips the router** (`red/gate.py`, `RED_CHAT_FIRST`, on by default). Plain word matching, under a millisecond: a sentence goes to the router when it has a command word, an app/site/folder name, the screen, music, a number, a question about facts, or "can you X"; and always right after a tool (an answer to "which song?"). Everything else goes straight to one streamed chat call. On the 142 logged commands: every tool command is still routed except 3 the router itself got wrong ("you know" -> answer, a misheard "distraction" -> play_online, headphone talk -> look_up); 67 of 95 talk sentences now skip it.
- **Numbers, real model** (qwen3.5:4b, the hidden Red's Ollama, first sentence ready after the transcript, 8 of the user's sentences): before (router + chat) median **1.71 s**, max 2.17 s; after (chat only) median **0.27 s**, max 0.42 s. On top of that, before the warm() fix, any command after a keep-warm ping paid a reload (the 32.3 s "Don't sleep, OK?").
- **Human replies:** the chat prompt said "Your day is life on this PC: waiting for them...", which is where "Just waiting by my terminal..." came from. Now: you have no day of your own, never describe what you're doing or where you are; answer "what's up" like a friend on the phone; react like a person when they're rude (no "you're the boss"); no written laughter; don't mention the day unless asked (the clock is only in the prompt when they talk about time). The examples are labelled as other people's chats (A/B): with "User:/Red:" the 4B model took them for this user's history ("thinking about your exam"). `chat.human()` drops a sentence that still narrates an invented life and takes out "haha" before it is spoken.
- `scripts/chat_eval.py` (20 of the user's sentences, real model): before **6 of 20** replies broke a rule (invented life: "waiting here at your desk, bored until you come back from lunch"); after, 40 replies: **0 invented life, 0 written laughter** as spoken (2 caught and dropped as written), 1 borderline "this morning" at 12:05; first sentence median 0.58 s, max 0.84 s.

### 7.3 Overlay (Track C)

- PySide6. Frameless, always on top, translucent, and doesn't take keyboard focus. Sits in the bottom-right corner of the primary screen.
- States: `idle`, `listening`, `thinking`, `confirm`, `speaking`, `error`, each with a short text. It hides itself a few seconds after returning to `idle`.
- Qt must own the main thread. Other threads update it through a thread-safe method (Qt signals).
- Fallback if PySide6 can't start: a Windows notification.

### 7.3.1 The companion (2026-11-13, the user's picks)

- **Looks:** VRoid Studio's sample models, downloaded by the user from VRoid Hub. The licence in each file allows every use, changes and redistribution, no credit needed. **Red = AvatarSample_C** (the man), **Remy = AvatarSample_A**, **Asha = AvatarSample_B** (name picked for the user's brief: mixed Indian / African American; Sanskrit "hope", Swahili "life"). The VRMs are in `RED_HOME\config\companion\avatar-{a,b,c}.vrm`, not in git.
- **2D, not 3D** (the user's choice): lighter on a laptop that already runs the LLM, Whisper and Kokoro. Frames are rendered from the VRM by `scripts/avatar_render` (three-vrm in headless Edge, pinned npm packages) into `RED_HOME\models\companion\<id>\`: 26 peek frames (idle, blink, 3 mouths, notice, listen, think, happy ×3, laugh ×2, sad ×2, cry, angry ×2, surprised, shy, wave ×3, sleep), the same 26 for each bottom corner (cornerR_*, cornerL_*: posed, not mirrored images), the same 26 hanging upside down from the top edge (top_*: the model rolled 180°, so hair falls past the head) and 5 body frames (3 dangling, enjoying it, dropping). Faces mix VRoid's own morphs past the stock presets. Every morph is cleared before each frame: three-vrm only resets the morphs its presets use, so others (Fcl_EYE_Joy) leaked into the next frame and closed its eyes.
- **Where it sits (the user: "most of the time in the corners"):** a bottom corner by default, leaning in from the side with the fingers curled round the side edge beside its face and the other arm on the bottom edge; or anywhere along the bottom edge, forearms on it, so only the upper body shows, "looking out of a window". Or hanging upside down from the top edge, bubble and marks below its head. Let go within 180 px of the top and it grabs the top edge (no fall); near a side, that corner; the right-click menu also moves it.
- **Little animations (the user: "when we pick them or hover around"):** hover: a hop toward you and a heart floating off; picked up: a springy stretch and surprise lines round the head; landing: a squash on the edge; woken from sleep: a startled shake. The timer runs fast only while one plays.
- **Any model:** `python scripts\avatar_render\add.py <file.vrm> <id> --name Bruno --voice am_fenrir` (from PowerShell) copies the VRM, prints its licence, renders and finishes it; every folder with a frames.json is a companion (`available_companions`), in the menu and as `RED_COMPANION=<id>`. VRoid models get the full faces; other VRMs fall back to the standard expressions (happy, sad, angry, surprised, blink, mouths).
- **Behaviour:** breathing (the picture stretches slightly), blinking, the mouth follows Kokoro's loudness, a speech bubble types out the first line of the reply, anime marks over the head (zzz, !, ?, a tear, an anger mark, a note), a wave for greetings, notice when woken, sleep after 5 minutes, hidden while a full-screen app is in front. Hover cheers it up, click opens the chat window, right-click moves it (left corner, edge, right corner), switches companion or hides it until Red talks. Dragging picks it up: the whole body dangles and swings under the cursor, a "whoa!" clip plays (made once per voice with Kokoro into `sounds\`, never over Red's own voice), and on release it falls back to the edge where you let go; the spot is saved in `RED_HOME\cache\companion.json`.
- **Not yet:** emotions come from a word guess on the reply (`emotion_from_text`) until speech carries emotion tags (plan §7); Red's voice is still `af_heart` (a woman's), so Red's "whoa!" is too; the companion's persona and wake name switching (lane 2).

### 7.4 Music (Track C)

**Removed on 2026-11-09 (plan.md task 3, second plan).** The user doesn't want local music, so every "play X" (songs, artists, podcasts, videos) goes to `play_online` on YouTube, in `RED_BROWSER`, and Red fronts the window whose title has "YouTube". `play_music`, `red/tools/music.py` (the folder library and the pygame-ce player), `RED_MUSIC_DIR`, pygame-ce in `requirements-ui.txt`, and the voice loop's "pause Red's own music while listening" are gone. Pause, resume, next, previous and stop are the media keys (`red/tools/quick.py`, same tool names, `stop_music` is the Media Stop key), so they control YouTube in the browser. "Play some music" or "play anything" searches for a popular songs mix. Smart App Control was already blocking pygame's DLLs on this PC, so the local player couldn't start here anyway. `cancel_reminder` now falls back to the user's words when the model's `which` is just "reminder" (the changed tool list made Qwen2.5 7B do that for "cancel my reminder to call mom"). Real model: all 148 integration cases pass, with "play Believer", "play some Arijit Singh" and "play a podcast about loneliness" going to `play_online`.

The original Track C spec, kept for history:
- Plays from a local folder: `RED_MUSIC_DIR`, or the user's Music folder by default. Spotify is not in v0.1.
- Tools: play (an optional song, artist or folder name, matched against file names; shuffle when none is given) and stop. Add pause or next only if they come cheaply.
- Playback continues after `run()` returns. Choose a backend that doesn't require installing VLC system-wide, and record the choice in 8.8.

### 7.5 Repo sync check (Track C)

For each repo listed in `RED_HOME\config\repos.toml` (copied from `repos.example.toml`):

1. `git fetch` to update remote information
2. `git status` to find uncommitted changes
3. `git log @{u}..HEAD` to find local commits not pushed yet
4. `git log HEAD..@{u}` to find remote commits you don't have locally

Red reports each repo as clean, ahead, behind, or dirty. It also reports a repo with no upstream branch, a detached HEAD, or a failed fetch (for example, missing credentials) instead of skipping it. It never pulls, pushes, or changes a repo. Run git with `GIT_TERMINAL_PROMPT=0` and a timeout so it can't hang on a credentials prompt. The spoken reply is a short summary, and the details go to the overlay and the log.

---

## 8. Parallel sessions plan (history)

Tracks A to H ran in parallel worktrees from 2026-11-07 to 2026-11-09 and are all merged into `main`.
Their briefs, file ownership, contracts and merge notes (old sections 8.1 to 8.19) were removed on
2026-11-13 to keep this file short. Read them with `git show 94c6cae:progress.md`.

## 9. Decisions

- **Local model runtime: Red-managed Ollama (for v0.1).** Red downloads Ollama's standalone zip (no installer, no tray app, no autostart), runs `ollama serve` only while Red runs, and passes the JSON schema as Ollama's `format` so tool calls are constrained.
- **Why not bundle llama.cpp's llama-server?** It was the first choice, but its Windows builds aren't code-signed, and Windows 11 Smart App Control (on by default on many new PCs) refuses to load them (exit code `0xC0E90002`). Ollama's binaries are signed by Ollama Inc. llama-server stays as a fallback (`RED_LLM_BACKEND=llama.cpp`) for PCs that allow it.
- **Bring your own server.** Set `RED_LLM_URL` to use LM Studio or any OpenAI-compatible server instead.
- **Skipped: llama-cpp-python.** Installing its CUDA build on Windows often means compiling with Visual Studio and the CUDA toolkit, which is too much to ask of users.
- **Skipped: Hugging Face Transformers.** Too much setup on Windows for short command routing.
- **One data folder (`RED_HOME`).** No hard-coded paths, so Red works on any machine.
- **Child processes in a kill-on-close Job Object,** so Ollama never outlives Red or keeps GPU memory after a crash.
- **No cloud models.** Red works offline and needs no subscription.
- **Parallel build (2026-11-08):** Days 2 to 5 are split into three tracks with separate worktrees, separate file ownership and fixed contracts, followed by one integration step.
- **Phase 2 (2026-11-08):** after Phase 1 merged early, the same sessions continue with integration (D), "Hey Red" (E) and more PC abilities (F) until 13:15. They're merged into `main` after that.
- **Wake phrase: "Hey Red".** "Jarvis" is only the user's description of the kind of assistant Red is.

---

## 10. Open questions, and the defaults used until you decide

| Question | Default for v0.1 |
|---|---|
| Music source: local folder or Spotify? | Local folder (`RED_MUSIC_DIR`, otherwise the Music folder) |
| Which repos should the sync check cover? | Whatever you list in `repos.toml`; with no list, Red says how to add one |
| Which folders and apps go on the allowlist? | Built-in known folders and the four default apps, plus whatever you add to `allowlist.toml` |
| Train a custom "Hey Red" wake word now, or use a pre-trained phrase? | **Decided (2026-11-08): "Hey Red" only, never "Hey Jarvis".** Track E builds it. The hotkey always works |
| Hotkey | `Ctrl+Alt+R` |

---

## 11. Safety rules

- Secrets live only in `RED_HOME\config\.env`. The repo has `.env.example` with placeholders.
- Red opens only known Windows folders and the folders and apps in `allowlist.toml`. It never runs a path or command the LLM suggests.
- Shutdown, restart, and anything that changes files ask first and repeat the action back, so a misheard number is caught.
- Delays are capped at 24 hours, a scheduled shutdown is always announced, and "cancel shutdown" works at any time.
- The repo sync check is read-only.
- Logs contain transcribed speech, stay under `RED_HOME\logs`, and are never committed.

---

## 12. Future plans

- **Next for the voice experience (asked for 2026-11-08):**
  - **A settings app (Red's own app):** a window to change everything without editing `.env`:
    - **Wake phrases you choose:** "Hey Red", "Yo Red", "Okay Red", "What's up Red" (any greeting + "Red"), switched on and off in the app.
    - **Voice training in the app:** the `voice-setup` flow (say the phrase several times, like "Hey Siri"), for every wake phrase you turn on.
    - **Voices:** several Piper voices to pick from, female and male.
    - **Personality:** a normal mode and an opt-in casual mode that talks the way you talk, including swearing back when you swear at it (friendly banter, only for its owner, off by default).
    - The glow, microphone, follow-ups and hotkey.
  - **Owner voice match:** answer only your voice, like "Hey Siri". Needs a speaker-embedding model; `voice-setup` already records the samples it would learn from.
  - **Glow reacting to your voice**, and "Hey Red, open Downloads" in one breath.
  - **A more natural conversation:** better replies to chat, and tone when the user is upset.
- **v0.2:** `find_file`, `web_search` and `compose_mail` (see the table in section 2), plus Gmail read and mark-as-read through the Gmail API, with confirmation for each batch.
- **v0.3:** Multi-step automations, such as "open my project, check the repo sync, and tell me what's unpushed", with a short plan shown before running.
- **v0.4:** A plugin system so others can add tools without editing core code, with tool discovery from a `tools/` folder.
- **v0.5:** Calendar, reminders and timers.
- **Packaging:** A Windows installer (PyInstaller or Nuitka) so users don't need Python.
- **Later:** Smart home control, a web dashboard for the command log, per-tool permission settings, and a custom "Hey Red" wake word.

Each version ships with tests for its new tools and an updated safety section.

---

## 13. Open-source checklist

- [x] MIT license
- [x] `.env.example` with placeholder values
- [x] `.gitignore` covering `.env`, models and audio files
- [x] Tests for the router's JSON validation
- [x] README written for users, with the developer plan moved here
- [ ] README install steps that take under 30 minutes, checked on a clean machine (integration step)
- [ ] Safety section complete for every v0.1 tool (integration step)

---

## 14. Windows notes for developers

- **Shutdown:** `shutdown /s /t <seconds>`, `/r` for restart, and `shutdown /a` to cancel. `shutdown /a` fails with error 1116 when nothing is scheduled.
- **Opening apps and folders:** `os.startfile(path)` opens folders, files and registered apps.
- **Default browser:** ask the shell (`AssocQueryStringW` with `ASSOCF_IS_PROTOCOL`, `ASSOCSTR_EXECUTABLE`, `"https"`). Newer Windows 11 builds keep the choice in `UrlAssociations\https\UserChoiceLatest\ProgId`; the old `UserChoice` key can be stale.
- **Ollama** uses an NVIDIA GPU automatically when drivers are current. Its logs are in `RED_HOME\logs\ollama.log`.
- **Smart App Control** blocks unsigned programs and DLLs. Exit code `0xC0E90002` means it blocked something.
- **faster-whisper on the GPU** needs cuBLAS and cuDNN through pip (`nvidia-cublas-cu12`, `nvidia-cudnn-cu12`).
- **Global shortcut:** `pynput` works on Windows. Some antivirus tools flag keyboard hooks.
- **openWakeWord:** use the ONNX inference framework, because tflite runtime has no Windows wheels.
- **Autostart:** a shortcut in `shell:startup`, or Task Scheduler at login.
- **Qt:** tests run with `QT_QPA_PLATFORM=offscreen`, and the GUI must run on the main thread.

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
| Repo sync tool | `red/tools/git_sync.py` | ✅ Done (Track C). The local music tool was removed on 2026-11-09 (7.4) |
| Wiring it all together: settings, setup, voice loop, docs | `red/__main__.py`, `red/config.py`, `README.md`, `AGENTS.md` | ✅ Done (Track D, section 8.13). The shared venv install and the v0.1.0 tag are still to do |

**Day 1 result:** typed commands like "open Downloads" and "shut down in 2 hours" produce the right JSON in under a second once the model is loaded. 38 unit tests and 8 real-model tests pass. Commits: `a44da78` (project setup), `ebae152` (Day 1 code), `727ac5f` and `ffe2ff1` (README).

---

## 2. Goals and scope

**The bigger goal (2026-11-08):** a voice assistant for Windows as good as "Hey Siri" and "OK Google", which Windows doesn't have. That means a wake word that reliably hears its owner, a pleasant, polished look, natural conversation (follow-ups, knowing when to stop), and a settings app instead of editing `.env`.

**The aim:** a Jarvis for your own PC. You tell Red to do something and it does it, locally and safely.

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

### 7.3 Overlay (Track C)

- PySide6. Frameless, always on top, translucent, and doesn't take keyboard focus. Sits in the bottom-right corner of the primary screen.
- States: `idle`, `listening`, `thinking`, `confirm`, `speaking`, `error`, each with a short text. It hides itself a few seconds after returning to `idle`.
- Qt must own the main thread. Other threads update it through a thread-safe method (Qt signals).
- Fallback if PySide6 can't start: a Windows notification.

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

## 8. Parallel sessions plan

Three Claude Code sessions build Tracks A, B and C at the same time. Each session gets its own prompt (8.10), which names its track, and works in its own git worktree and branch. Then one integration session merges the three branches (8.9).

### 8.1 Before starting the sessions

1. Commit `progress.md`, `AGENTS.md`, `CLAUDE.md` and the updated `README.md` to `main`. Worktrees start from the last commit, so uncommitted files won't be in them.
2. Open all three sessions in `D:\RED` (the parent folder), not `D:\RED\red`, so the worktrees under `D:\RED\worktrees\` are inside each session's working folder.
3. Paste the Track A, B and C prompts from 8.10 into the three sessions, one prompt per session.

### 8.2 Tracks, worktrees and branches

| Track | Worktree | Branch | Work |
|---|---|---|---|
| A | `D:\RED\worktrees\a` | `track-a-actions` | Day 2: actions, confirmation, allowlist, command log, executor |
| B | `D:\RED\worktrees\b` | `track-b-voice` | Days 3 and 4: recording, Whisper, Piper, hotkey, wake word, spoken confirmation |
| C | `D:\RED\worktrees\c` | `track-c-ui-tools` | Days 4 and 5: overlay, music tool, repo sync tool |

Each session creates its own worktree, for example:

```powershell
git -C D:\RED\red worktree add D:\RED\worktrees\a -b track-a-actions
```

If the worktree already exists, it's from an earlier run of the same track, so continue in it. If git reports a lock error (another session was creating its worktree at the same moment), retry.

### 8.3 Rules for every session

- Work only inside your own worktree. Don't edit `D:\RED\red` (the `main` checkout) or another track's worktree. Don't merge, rebase onto other tracks, or push.
- Commit to your own branch whenever useful. Use clear messages that start with `Track A:` (or `B:` or `C:`).
- Edit only the files your track owns (8.4). If you need a change in a file you don't own, write it under "Integration notes" in your section of this file instead.
- In `progress.md`, edit only your own track's section (8.6, 8.7 or 8.8).
- Each track uses its own pytest temp folder, because pytest empties `--basetemp` on every run: `--basetemp="D:\RED\cache\pytest-tmp-a"` (or `-b`, `-c`).
- Python environments: A uses the shared `D:\RED\.venv` and installs nothing new. B and C each create a venv inside their worktree, `py -3.11 -m venv .venv`, install `requirements-dev.txt` plus their own requirements file, and set `$env:PIP_CACHE_DIR = "D:\RED\cache\pip"`. Don't install anything into `D:\RED\.venv`.
- Set `$env:RED_HOME = "D:\RED"` in every shell. Models and binaries are shared there, so never delete anything under `D:\RED\bin`, `D:\RED\models` or `D:\RED\cache` that you didn't create.
- New settings: don't edit `config.py` or `.env.example` (Track A owns them). `load_settings()` has already loaded `config\.env` into the environment, so read new `RED_*` variables with `os.environ` inside your own module, with defaults. List each one in your Integration notes; the integration step moves them into `Settings`.
- Real model: only one Ollama should hold the model on a 6 GB GPU. Before any real-model test, check `http://127.0.0.1:11434/api/version`. If nothing answers, start one shared Ollama in the background and leave it running. Red's `connect()` then uses it instead of starting its own:
  ```powershell
  $env:OLLAMA_HOST = "127.0.0.1:11434"; $env:OLLAMA_MODELS = "D:\RED\models\ollama"; $env:USERPROFILE = "D:\RED\cache\ollama-home"
  & D:\RED\bin\ollama\v0.40.11\ollama.exe serve
  ```
- No real side effects: never schedule a real shutdown or restart, and don't leave windows, music or recordings running. Anything that needs a human (microphone, speakers, a real shutdown notice) goes in your "Manual checks for the user" list.
- Pin every new dependency to an exact version that has a Windows wheel for Python 3.11, and check it installs before pinning it. Pin downloaded models to a revision and SHA-256, as `red/llm.py` does.
- Ask the user only when you're blocked on a decision that's theirs. Otherwise use the defaults in section 10 and record what you decided.

### 8.4 File ownership

| Owner | Files |
|---|---|
| A | `red/__main__.py`, `red/config.py`, `.env.example`, `red/tools/base.py`, `red/tools/system.py`, `red/tools/web.py`, new `red/confirm.py`, `red/allowlist.py`, `red/known_folders.py`, `red/executor.py`, `allowlist.example.toml`, `tests/test_integration_llm.py`, new tests for these |
| B | new `red/audio.py`, `red/stt.py`, `red/tts.py`, `red/listener.py`, `red/voice_confirm.py`, `red/voice_demo.py`, `requirements-voice.txt`, new tests for these |
| C | `red/tools/__init__.py`, new `red/overlay.py`, `red/tools/music.py`, `red/tools/git_sync.py`, `repos.example.toml`, `requirements-ui.txt`, new tests for these (including a separate real-model test file for the new tools) |
| Integration only | `README.md`, `AGENTS.md`, `CLAUDE.md`, `requirements.txt`, `requirements-dev.txt`, `pyproject.toml`, `red/router.py`, `red/llm.py`, `red/process.py`, `red/downloads.py`, existing tests not listed above |

Any session may import the read-only modules (`config`, `downloads`, `llm`, `process`, `router`, `tools.base`), but it must not change them unless it owns them.

### 8.5 Contracts between tracks

Build to these signatures so the integration step only has to connect them. Small changes are fine; record any differences in your Integration notes.

**A provides:**

```python
# red/confirm.py
Ask = Callable[[str, float], str | None]   # (question, timeout seconds) -> answer, or None on timeout
def typed_ask(question: str, timeout: float) -> str | None: ...
def is_yes(answer: str | None) -> bool: ...          # only "y"/"yes", case and trailing punctuation ignored
def confirm(question: str, ask: Ask = typed_ask, timeout: float = 30.0) -> bool: ...

# red/tools/base.py: new optional method on Tool, used for the confirmation text
def describe(self, **kwargs) -> str: ...             # "Shut down in 2 hours (at 11:40 PM)"

# red/executor.py
class Executor:
    def __init__(self, registry, ask: Ask = typed_ask, log_path: Path | None = None): ...
    def execute(self, command: str, route: Route) -> str: ...   # reply text; "none" returns its reply

# red/known_folders.py
def known_folder(name: str) -> Path | None: ...      # "downloads", "music", ...
```

**B provides:**

```python
# red/audio.py
def record_command(max_seconds: float = 8.0, silence_seconds: float = 0.8) -> "numpy.ndarray": ...  # 16 kHz mono float32

# red/stt.py
class Transcriber:
    def __init__(self, model_dir: Path, model: str = "small", device: str = "auto"): ...
    def transcribe(self, audio) -> str: ...

# red/tts.py
class Speaker:
    def __init__(self, voice_dir: Path, voice: str | None = None): ...
    def say(self, text: str, block: bool = True) -> None: ...
    def stop(self) -> None: ...

# red/listener.py
class Listener:
    def __init__(self, on_trigger: Callable[[str], None], hotkey: str = "<ctrl>+<alt>+r",
                 wakeword: str | None = None): ...   # on_trigger("hotkey" | "wakeword"), from a background thread
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def pause(self) -> None: ...                     # while recording or speaking
    def resume(self) -> None: ...

# red/voice_confirm.py
def spoken_ask(speaker, transcriber) -> Callable[[str, float], str | None]: ...  # matches confirm.Ask
```

**C provides:**

```python
# red/overlay.py
STATES = ("idle", "listening", "thinking", "confirm", "speaking", "error")
class Overlay:
    def set_state(self, state: str, text: str = "") -> None: ...   # safe to call from any thread
def run_with_overlay(worker: Callable[[Overlay], None]) -> int: ...  # Qt owns the main thread; worker runs in a thread

# red/tools/music.py, red/tools/git_sync.py: Tool subclasses, registered in default_registry()
```

### 8.6 Track A: actions and confirmation

Spec: 7.1. Done when every tool works from typed input, every destructive action asks first, cancelling always works, and all tests pass.

- [x] `known_folders.py`: Known Folder API through ctypes
- [x] `allowlist.py` and `allowlist.example.toml`: load with `tomllib`; a missing file means only the built-in defaults
- [x] `open_folder`, `open_app`, `open_url` actions, with side effects passed in through the constructor
- [x] `shutdown`, `restart`, `cancel_shutdown`, plus `describe()` with the exact time
- [x] `confirm.py`: typed, 30-second timeout, `is_yes`
- [x] `executor.py`: confirm, run, write to `commands.jsonl`; errors become a short reply and a log line, never a crash
- [x] `__main__.py`: run actions by default; `--dry-run` keeps the Day 1 behaviour
- [x] Unit tests with fakes; real-model tests still pass (150 unit tests pass; 13 real-model tests pass with `RED_INTEGRATION=1`)
- [x] Section updated, committed on `track-a-actions`

Decisions:
- **Allowlist is reloaded on every command,** so edits to `allowlist.toml` apply without restarting Red. Entries there win over built-ins with the same name. Values are a program (string) or `[program, arg, ...]` (list). `%VARS%` and `~` are expanded in allowlist values only, never in LLM text. Folder paths must be absolute. A broken file gives a warning at startup and a short error reply when used; it never crashes Red.
- **Folder lookup order:** allowlist, then the six known folders, with aliases (`download`, `docs`, `photos`, `movies`, ...) and filler words dropped ("my documents folder" -> documents). A full path from the model is only accepted if it equals a known or allowlisted folder. The target must be a directory (`is_dir()`), so a file or a program can never reach `os.startfile`. The `open_folder` description (including "or a full path") is unchanged to keep routing stable.
- **Apps:** the program is resolved with `shutil.which` and started with `subprocess.Popen(list, shell=False)`. `.cmd`/`.bat` launchers get `CREATE_NO_WINDOW` (no console flash for VS Code's `code.cmd`); other programs get `CREATE_NEW_CONSOLE`. If Windows says the program needs elevation (WinError 740, which is likely for Task Manager), Red falls back to `os.startfile` on that same allowlisted program.
- **Shutdown:** Red runs `%SystemRoot%\System32\shutdown.exe` by full path, with `/a` first (its result is ignored), then `/s` or `/r` `/t <seconds>`, with a 15 s timeout and no window. `minutes = 0` means now. `run()` checks the 0 to 1440 range again. Note: Windows implies `/f` when `/t > 0`, so open apps are closed without asking. The README safety section should say so at integration.
- **Time wording:** `describe()` gives "Shut down in 2 hours (at 11:40 PM)", "in 1 hour and 30 minutes", "(at 1:00 AM tomorrow)", "Shut down now". The reply after scheduling repeats the time and says how to cancel.
- **`is_yes`** strips surrounding whitespace and punctuation on both sides, so "Yes.", " y " and "Yes?" confirm; "yeah", "yes please" and "sure" don't.
- **Typed input:** on a Windows console, `typed_ask` reads keys with `msvcrt` until Enter or the timeout. It discards keys typed before the question (type-ahead can't confirm), and Ctrl+C at the prompt means no. Piped stdin has no timeout; end of input means no answer. An `ask` that raises cancels.
- **Command log** records every outcome: `status` is `ok`, `cancelled`, `error` or `none`. Fields: `time` (local ISO with offset), `command`, `tool`, `args`, `status`, `confirmed` (true/false, or null when nothing was asked), `result`, plus `answer` on a cancel and `error` (exception type and text) for unexpected failures. `Executor(log_path=None)` writes no log. If the log can't be written, the error goes to `red.log` and the command still runs.
- **CLI:** `--dry-run` is a top-level flag. `route` always only shows the call. There's a new `run "<command>"` that runs one command. `setup` copies `allowlist.example.toml` to `RED_HOME\config\allowlist.toml` if that file is missing.
- No new dependencies and no new `RED_*` settings.

Integration notes:
- Contract differences from 8.5: `Executor.__init__` takes an extra `confirm_timeout: float = 30.0`. `log_path=None` means no log (the CLI passes `settings.command_log_path`).
- New in `tools/base.py`: `ToolError`. Raise it for failures whose message is fit to say to the user; the Executor speaks it as the reply. Any other exception becomes "Sorry, <tool> failed: ..." and is logged. Track C tools can use `ToolError`, but nothing breaks if they don't. `Tool.describe()` has a generic default, so C's tools only need it if they are destructive.
- New `Settings` properties: `allowlist_path`, `command_log_path`.
- The Executor passes `ask` the question without `[y/N]`, for example "Shut down in 2 hours (at 11:40 PM)?"; `typed_ask` adds `[y/N]` itself. `spoken_ask` should speak the question as given. To show the `confirm` overlay state, wrap `ask` before passing it to `Executor`.
- The tools in `default_registry()` need no constructor arguments: `OpenFolder` and `OpenApp` load `red_home()\config\allowlist.toml` themselves, so Track C's `tools/__init__.py` needs no change for Track A.
- For the music tool's default folder: `red.known_folders.known_folder("music")` returns a `Path` or `None`.
- Tests share fakes in `tests/fakes.py` (`FakeRunner`, `FakeStartfile`, `FakePopen`, `FakeAsk`). `tests/test_integration_llm.py` now imports it.

Manual checks for the user:
- Schedule a shutdown in 60 minutes, see the Windows notice, type "cancel the shutdown", and check that it's gone.
- In a real PowerShell window, run `python -m red`, type "restart in 10 minutes" and don't answer. After 30 seconds Red should say "No answer, so I cancelled it.", and no Windows notice should appear. Then try again and answer `n`: it's cancelled too.
- With nothing scheduled, type "cancel the shutdown". Red should say "Nothing was scheduled". This checks that `shutdown /a` returns 1116 on your machine.
- "open Downloads", "open Documents" and "open Pictures" open Explorer in the right folders, including the OneDrive ones.
- "open notepad", "open calculator", "open file explorer" and "open task manager" each start. Task Manager may show a UAC prompt; check that it opens.
- "open youtube" opens your default browser.
- Run `python -m red setup` (or copy `allowlist.example.toml` to `D:\RED\config\allowlist.toml`), set `projects` to a real folder, then check "open projects" and "open vs code".
- Check `D:\RED\logs\commands.jsonl` has one line for each command you ran.

### 8.7 Track B: voice

Spec: 7.2. Done when `python -m red.voice_demo` works: press the hotkey or say the wake word, speak, see the transcript, and hear it read back; spoken yes/no works; unit tests pass without a microphone.

- [x] `requirements-voice.txt`, pinned and verified on Windows with Python 3.11
- [x] `audio.py`: recording that stops on silence
- [x] `stt.py`: Whisper loaded on first use, GPU with CPU int8 fallback, models under `RED_HOME\models\whisper`
- [x] `tts.py`: Piper with a pinned, checksum-verified voice under `RED_HOME\models\piper`
- [x] `listener.py`: global hotkey and pre-trained wake word, with pause and resume
- [x] `voice_confirm.py`: `spoken_ask`
- [x] `voice_demo.py`
- [x] Unit tests with fake audio, fake models and a fake keyboard
- [x] Section updated, committed on `track-b-voice`

**Result (2026-11-08):** 88 new unit tests pass with no microphone, speakers, keyboard hook or real model (126 passed in total, with the real-model tests skipped). The new real-model file `tests/test_voice_models.py` (`RED_INTEGRATION=1`) also passes, 7 tests in about 20 s. It feeds Piper's speech into Whisper on the CPU (int8) and into the wake word detector: every phrase comes back word for word, and "Hey Jarvis" fires while a normal command doesn't. A short command takes about 2 s to transcribe on the CPU. The real hotkey hook starts and stops, and the real microphone opens on MME and WASAPI. Everything that needs your voice or ears is under "Manual checks".

Decisions:
- **Wake word: `hey_jarvis`**, openWakeWord v0.5.1's ONNX model. It's the most reliable of the pre-trained phrases, and it passed the real-model test. `hey_mycroft`, `hey_rhasspy` and `alexa` are pinned too. A path to a custom `.onnx` file also works, ready for a future "Hey Red" model. Following section 10, the hotkey always works.
- **Piper voice: `en_US-lessac-medium`**, from `rhasspy/piper-voices` at commit `e7229f7`. It's a clear US English voice at medium quality, 63 MB. A voice that isn't pinned can be used by putting its `.onnx` and `.onnx.json` files in `models\piper`.
- **Whisper `small`**, from `Systran/faster-whisper-small` at commit `536b066`. Each file is pinned and fetched with `red.downloads.download` into `models\whisper\small`. Red doesn't use the huggingface_hub cache, so every file is checksum-verified like the LLM. Settings: language `en`, beam size 5, faster-whisper's built-in Silero VAD filter on, no conditioning on previous text.
- **GPU check at load:** CUDA libraries load lazily, so `load()` runs a 1-second warm-up on the GPU. A missing cuBLAS or running out of VRAM then falls back to the CPU at startup, not during your first command. An error during a later transcription also falls back and retries once. After a fallback, Whisper stays on the CPU for the rest of the session.
- **Audio library: `sounddevice`**, for both recording and playback. It bundles PortAudio, so nothing extra needs installing. It asks the device for 16 kHz mono, and if the device refuses (WASAPI does), it records at the device's own rate and resamples.
- **Silence detection: energy-based, with no extra dependency.** The noise floor is measured over the first 0.25 s, ignoring the exact-zero blocks a microphone sends while it starts up, and capped at 0.02. Speech means 3× the noise floor and at least 0.008 RMS, sustained for 90 ms, so a click doesn't count. 0.3 s of audio before the speech starts is kept. If nobody speaks, `record_command` returns an empty array and nothing is sent to Whisper, because Whisper tends to invent words for silence.
- **Threading:** `on_trigger` runs on the listener's own worker thread, one trigger at a time. A trigger that arrives while one is being handled is dropped, so a double press doesn't start two recordings. While a trigger is being handled, the wake word is paused automatically and its microphone stream is closed. `pause()` and `resume()` nest, and the hotkey keeps working while the wake word is paused.
- **Spoken question:** a trailing `[y/N]` or `(y/n)` is removed and "Say yes to confirm." is added. You get `timeout` seconds to start answering, then up to 4 s to finish. Silence or an empty transcript returns `None`. The transcript is returned as heard, so `confirm.is_yes` makes the yes/no decision.
- **A short beep** (`audio.chime()`) plays before recording so you know when to speak. It finishes before the microphone opens, so it's never recorded.
- **What `requirements-voice.txt` pins:** the direct dependencies plus the compiled dependencies under them (ctranslate2, av, tokenizers, onnxruntime, scipy, scikit-learn). It doesn't include NVIDIA GPU libraries (see the integration notes). Checked in a fresh venv with `--only-binary=:all:` and `pip check`.

Integration notes:
- **Install the voice requirements into the shared venv.** The new tests import numpy and the voice packages, so the integration step needs `pip install -r requirements-voice.txt` in `D:\RED\.venv`, plus `-r requirements-voice.txt` in `requirements.txt`. Otherwise the voice tests fail to import there.
- **New settings for `Settings` and `.env.example`.** All are read by `VoiceConfig.from_env()` in `red/voice_demo.py`, except `RED_MIC_DEVICE`, which `audio.default_input_device()` reads:
  - `RED_HOTKEY`: default `Ctrl+Alt+R`. Accepts `Ctrl+Alt+R` or pynput's `<ctrl>+<alt>+r`; `off` disables it.
  - `RED_WAKEWORD`: default `hey_jarvis`. Also `hey_mycroft`, `hey_rhasspy`, `alexa`, a path to an `.onnx` model, or `off`.
  - `RED_WAKEWORD_THRESHOLD`: default `0.5`.
  - `RED_WHISPER_MODEL`: default `small`, the only pinned model.
  - `RED_WHISPER_DEVICE`: `auto`, `cuda` or `cpu`; default `auto`.
  - `RED_PIPER_VOICE`: default `en_US-lessac-medium`.
  - `RED_MIC_DEVICE`: an input device index or part of its name. Empty means the Windows default.
- **`python -m red setup`** should also fetch the voice models, about 550 MB: `Transcriber.download()`, `Speaker.download()` and `listener.download_wakeword(models\wakeword, wakeword)`. `python -m red.voice_demo --setup` does the same today. On this machine they're already downloaded and verified under `D:\RED\models\{whisper,piper,wakeword}`.
- **Differences from the 8.5 contracts.** Everything is additive; the contracted names and positional signatures are unchanged.
  - `record_command(...)` takes extra keyword-only arguments `start_timeout`, `mic` (any context manager with `read()`) and `stop_event`. It returns an empty array when nothing was said.
  - `Transcriber(...)` takes extra keyword arguments `language`, `beam_size`, `model_factory` and `cuda_check`, and adds `download()`, `load()`, `.device` and `.compute_type`. Call `load()` at startup so the first command isn't slow.
  - `Speaker(...)` takes extra keyword arguments `voice_loader` and `player`, and adds `download()`, `load()`, `synthesize()` and `.speaking`.
  - `Listener(...)`: `hotkey` may be `None`. It takes extra keyword arguments `model_dir` (default `RED_HOME\models\wakeword`), `threshold`, `hotkey_factory`, `mic_factory` and `detector_factory`, and adds `paused_while()`, a context manager. `start()` raises if the wake word model can't load.
  - `spoken_ask(speaker, transcriber, *, record=..., listener=None)`.
- **Swap the stand-in yes check.** Replace `voice_demo._is_yes` with `confirm.is_yes`. In the `Executor`, use `spoken_ask(speaker, transcriber)`. When it runs inside the trigger handler, the wake word is already paused.
- **Overlay states in the trigger handler:** `listening` before `chime()` and `record_command()`, `thinking` around transcribe and route, `confirm` around `spoken_ask`, and `speaking` around `Speaker.say`. Anything Red says outside a trigger handler, such as a future reminder, should go inside `with listener.paused_while():`.
- **`PinnedFiles`** (a pinned URL prefix plus files with SHA-256s) lives in `red/audio.py` because Track B couldn't add a module. It could move into `red/downloads.py`.
- **GPU Whisper on this machine:** `cublas64_12.dll` isn't on PATH; the only copy is in Ollama's `lib\ollama\cuda_v12` folder. So `auto` currently falls back to the CPU at load, with a warning. ctranslate2 already bundles cuDNN 9. To enable the GPU, install `nvidia-cublas-cu12`; `stt.add_nvidia_dll_dirs()` puts its `bin` folder on PATH for Red's process automatically. I didn't pin it in `requirements-voice.txt` because it's several hundred MB and only helps NVIDIA users.
  - **Question for the user:** add an optional `requirements-gpu.txt`? Default: no, CPU int8. Also, with 6 GB of VRAM shared with the 7B model, `RED_WHISPER_DEVICE=cpu` may be the better default even with the GPU libraries installed.
- **Question for the user:** train a custom "Hey Red" wake word now? Default (section 10): keep `hey_jarvis` for v0.1. A custom model drops in as `RED_WAKEWORD=D:\RED\models\wakeword\hey_red.onnx`.
- **Test helpers:** `tests/voice_fakes.py` holds the shared fakes (microphone, Whisper, Piper voice, player, hotkeys, detector). `tests/test_voice_models.py` needs the voice models downloaded.

Manual checks for the user (in PowerShell, from `D:\RED\worktrees\b`; after integration, use `D:\RED\red` and the shared venv):

```powershell
cd D:\RED\worktrees\b
$env:RED_HOME = "D:\RED"
.\.venv\Scripts\Activate.ps1
python -m red.voice_demo --setup      # already done; only re-checks the files
```

1. **Speakers:** `python -m red.voice_demo --say "Hello, I am Red."`. You should hear a clear voice say it once.
2. **Microphone level:** `python -m red.voice_demo --levels`. Talk normally for a few seconds, then stay quiet. Speech should read above about 0.02 and silence below 0.008. If your speech stays under 0.01, note it: the speech threshold needs lowering. If the wrong microphone is used, set `$env:RED_MIC_DEVICE` to part of the right device's name.
3. **Hotkey:** `python -m red.voice_demo --no-wakeword`. Wait for `Ready.`, then click into another window, for example your browser.
   - Press Ctrl+Alt+R. You hear a beep. Say "open my downloads folder".
   - Recording should stop by itself about a second after you finish. Within a few seconds the terminal shows `You said: 'Open my downloads folder.'` and Red reads it back.
   - Press Ctrl+Alt+R and say nothing. After 8 s it prints `(heard nothing)` and says "I didn't hear anything."
   - Press Ctrl+Alt+R twice quickly. Only one recording should start.
4. **Wake word:** `python -m red.voice_demo`. Say "Hey Jarvis", wait for the beep, then say a command. You should get the transcript and the read-back.
   - It shouldn't trigger on itself while it's reading back.
   - Leave it running for a few minutes of normal talk or a video. It shouldn't trigger by itself.
   - If it misses "Hey Jarvis" or fires too often, try `$env:RED_WAKEWORD_THRESHOLD = "0.35"` (more sensitive) or `"0.65"` (less sensitive) and report the value that works.
5. **Spoken yes/no:** `python -m red.voice_demo --confirm --no-wakeword`. After each read-back, Red asks "Do you want to confirm? Say yes to confirm."
   - Say "yes". It prints `-> confirmed`.
   - Next time, say "no". It prints `-> cancelled`.
   - Next time, stay silent. After 30 s it prints `Answer: None -> cancelled`.
6. **Quitting:** press Ctrl+C. It prints `Bye.` and returns to the prompt. Task Manager should show no leftover `python.exe` from the demo.
7. **GPU fallback (optional; run it while the shared Ollama isn't holding the model):** `python -m red.voice_demo --device cuda --no-wakeword`. On this machine, expect a warning that Whisper couldn't start on the GPU, then `on cpu (int8)`, and the demo still works. With `nvidia-cublas-cu12` installed, it should say `on cuda (float16)` instead.
8. **Antivirus:** check that no antivirus warning about the keyboard hook appeared while the demo ran.

### 8.8 Track C: overlay, music, repo sync

Specs: 7.3, 7.4 and 7.5. Done when `python -m red.overlay` shows every state, the music and repo-sync tools work from `Tool.run()` and route correctly with the real model, and all tests pass (overlay tests use `QT_QPA_PLATFORM=offscreen`).

- [x] `requirements-ui.txt`, pinned and verified
- [x] `overlay.py` with a demo under `__main__`, plus the notification fallback
- [x] `tools/music.py`: library scan, name matching, play and stop, injectable player
- [x] `tools/git_sync.py` and `repos.example.toml`: all statuses from 7.5, read-only, with timeouts, using an injectable git runner in tests
- [x] Registered in `default_registry()`; real-model routing tests for the new tools in their own test file
- [x] Check that the new tool descriptions don't break routing for the existing tools
- [x] Section updated, committed on `track-c-ui-tools`

Result (2026-11-08): 178 unit tests pass and 37 are skipped (`QT_QPA_PLATFORM=offscreen`, `--basetemp="D:\RED\cache\pytest-tmp-c"`). With `RED_INTEGRATION=1` and the shared Ollama, all 37 real-model tests pass: 29 in `tests/test_integration_c_tools.py` and the 8 existing ones in `tests/test_integration_llm.py`, with every Track C tool registered. `python -m red.overlay` runs on the real display, shows every state, and exits by itself.

Decisions:
- **Qt package: `PySide6-Essentials==6.11.3`**, not full `PySide6`. It has QtCore, QtGui and QtWidgets, which is all the overlay needs: about 77 MB instead of more than 400 MB. 6.11.3 is the latest patch of the previous minor version; 6.12.0 had only just come out.
- **Music backend: `pygame-ce==2.5.8`** (SDL_mixer 2.8.2), playing in-process on a daemon thread. It plays mp3, ogg, opus, flac and wav, and needs no VLC. **It doesn't play m4a, aac or wma.** Files in those formats aren't listed, and a file that won't load is skipped. Rejected options:
  - `python-vlc` needs VLC installed system-wide.
  - Qt Multimedia isn't in Essentials and needs a running Qt event loop, so typed mode would break.
  - Windows Media Player COM needs pywin32 and a message pump.
- **Music tools:** `play_music` (optional `query`), `stop_music`, `pause_music`, `resume_music` and `next_song`. Pause and next were cheap with pygame. All five share one player, created on the first play, so building the registry never opens the audio device.
- **Song matching** uses only file and folder names under the music folder, so the query is never treated as a path. Accents, punctuation and words like "the", "songs" or "by" are ignored. Ranking, best first:
  1. A song title or folder name that equals the query
  2. Songs whose path contains every word of the query
  3. Close matches for misheard words (difflib, 0.8)

  A single match plays that song. Several matches are shuffled. The scan stops at 20,000 files and skips hidden folders.
- **The model fills optional args with placeholders** like `"null"`, `"none"`, `"all"`, `"shuffled"` or `"some music"` instead of leaving them out. Each property now has a description that offers `"all"`, which the model then uses reliably. `wants_everything()` in `music.py` and `means_all_repos()` in `git_sync.py` treat every placeholder as "all".
- **Overlay:**
  - 360 px wide, rounded and dark, with a coloured dot for each state. It sits in the bottom-right of the primary screen's available area, so it stays above the taskbar.
  - It is click-through (`WindowTransparentForInput`) as well as non-focusing.
  - It hides 3 seconds after `idle`. `idle` with text shows briefly and then hides.
  - Text is plain text, never rich text, and is cut at 600 characters.
  - `set_state` emits a queued Qt signal, so it is safe from any thread, and it raises `ValueError` for an unknown state.
  - `run_with_overlay` returns 0 when the worker finishes, 1 if it raised (and shows an error state), and 130 on Ctrl+C.
- **Notification fallback:** a Windows toast through `powershell.exe -EncodedCommand` with a fixed script. The title and text travel in environment variables and are added as XML text nodes, so nothing the user or the model says is parsed as script or markup. It shows only `confirm`, `speaking` and `error`, so `listening` and `thinking` don't spam toasts. The demo has `--fallback` to try it. `ConsoleOverlay` is also available for typed mode.
- **Repo sync (read-only):**
  - Git runs with `GIT_TERMINAL_PROMPT=0`, `GCM_INTERACTIVE=never`, `GIT_ASKPASS=echo`, `GIT_OPTIONAL_LOCKS=0` (so `status` doesn't rewrite the index), `credential.interactive=never`, and no gc or maintenance. stdin is closed and no console window appears.
  - Fetch uses `--no-tags --no-write-fetch-head` and only runs when there's an upstream branch.
  - Timeouts are 15 seconds for local commands and 45 seconds for fetch. On a timeout, Red ends git's whole process tree with `taskkill /T`.
  - Up to 4 repos are checked in parallel.
  - Each repo gets one state: `clean`, `ahead`, `behind`, `diverged`, `dirty`, `detached`, `no_upstream`, `fetch_failed`, `missing`, `not_a_repo` or `error`. Dirty wins over ahead or behind, but the spoken reply names every problem.
  - A failed fetch still reports ahead and behind from the last fetch.
  - Tests check that only `rev-parse`, `symbolic-ref`, `fetch`, `status` and `log` ever run (`READ_ONLY_COMMANDS`). They also check that HEAD, refs, the index and the files are unchanged afterwards.
- **`repos.toml` format:** `[repos]` with `name = 'folder'` entries. `%VARS%` and `~` are expanded, and relative paths are relative to the file. The optional `repo` argument is only a lookup key, ignoring case, spaces and dashes. An unknown name gets "I don't have a repo called X", followed by the list of repos.
- **Spoken repo reply:** names at most 3 repos that need attention, for example "2 of 4 repos need attention: red has 2 unpushed commits; notes has uncommitted changes."

Integration notes:
- Add `-r requirements-ui.txt` to `requirements.txt`. Don't install the old `pygame` next to `pygame-ce`, because both use the `pygame` import name.
- **New setting:** `RED_MUSIC_DIR`, read in `red/tools/music.py: music_dir()`. Move it into `Settings`.
- **Music default folder:** in `music_dir()`, replace `Path.home() / "Music"` with `known_folders.known_folder("music")`, keeping the old path as a fallback. There's a comment at that line.
- **repos.toml path:** `git_sync.repos_file()` uses `red_home() / "config" / "repos.toml"`. It could use `Settings.config_dir` instead.
- **Repo details for the overlay and the log:** after `run()`, `CheckRepos` sets `last_details` (one line per repo) and `last_results` (a list of `RepoStatus`). The Executor or `__main__` should:
  - show the reply plus `last_details` in the overlay's `speaking` state
  - add `last_details` to the `commands.jsonl` line, for example as a `details` field

  A generic way to do this: `getattr(registry.get(route.tool), "last_details", "")`. Commit subjects are also logged at INFO by the `red.tools.git_sync` logger.
- A repo check can take up to about 45 seconds when a remote is slow. Set the overlay to `thinking` ("Checking your repos…") before running `check_repos`.
- **Overlay wiring:** call `run_with_overlay(worker)` from the main thread in `__main__`, and run the whole listen, route, confirm, run, speak loop inside `worker(overlay)`. Use `overlay.set_state(...)` at each step. Call `confirm` before showing the confirmation question. Typed mode can skip Qt and use `ConsoleOverlay`, or no overlay at all.
- **Music and the microphone:** pause music while Red records or speaks, so Whisper doesn't transcribe the song. For example: `p = music.default_player()`, and if `p.current and not p.paused`, call `p.pause()` on trigger and `p.resume()` afterwards.
- If Track A adds optional arguments, they may hit the placeholder problem described under Decisions.
- `tests/test_integration_c_tools.py` repeats the commands from `tests/test_integration_llm.py` and adds 3 more ("open my music folder", "stop the shutdown", "open github"). Args are compared case-insensitively. The original file gives `"Downloads"` in exact case, which the model still matches.
- README and AGENTS.md need: `repos.toml` setup, `RED_MUSIC_DIR`, the supported music formats (no m4a, aac or wma), and `python -m red.overlay`.
- Possible later work, not needed for v0.1:
  - Qt can abort the process (`qFatal`) instead of raising when there's no display at all, for example in a service session. The fallback covers import errors and a missing screen, but not that case.
  - Music tags (ID3) aren't read; matching uses file and folder names only.

Manual checks for the user (run in `D:\RED\worktrees\c` with `.\.venv\Scripts\python.exe`, after `$env:RED_HOME = "D:\RED"`):
- **Overlay:** run `python -m red.overlay`. Check that:
  - a dark card appears in the bottom-right corner, above the taskbar, and goes through Listening, Thinking, Confirm, Red (twice) and Problem
  - it never takes focus from the window you're typing in, and clicks pass through it
  - it hides about 3 seconds after the last state, and the program exits by itself

  Also try it on a high-DPI or second monitor.
- **Notification fallback:** run `python -m red.overlay --fallback`. Check that 4 Windows notifications appear (Confirm, Red, Red, Problem).
- **Music, which plays sound:** set `$env:RED_MUSIC_DIR` to a folder of mp3 or flac files, or leave it unset to use your Music folder. Then run:
  `python -c "import time; from red.tools.music import *; p=PlayMusic(); print(p.run()); time.sleep(8); print(PauseMusic().run()); time.sleep(2); print(ResumeMusic().run()); time.sleep(4); print(NextSong().run()); time.sleep(6); print(StopMusic().run())"`

  Check that you hear music, a pause, the song resuming, a different song, and then silence. Try `p.run(query="<an artist folder name>")` too.
- **Repo sync on your real repos (read-only):** copy `repos.example.toml` to `D:\RED\config\repos.toml` and list a few repos, ideally one with unpushed commits and one with uncommitted changes. Then run:
  `python -c "from red.tools.git_sync import CheckRepos; t=CheckRepos(); print(t.run()); print(t.last_details)"`

  Check that the statuses are right and that `git status` in each repo looks the same afterwards. Add one private repo whose credentials have expired or been removed. Check that it reports "couldn't fetch" within about 45 seconds and that no login window or prompt appears.

### 8.9 Integration (one session, after A, B and C are done)

1. Merge `track-a-actions`, then `track-c-ui-tools`, then `track-b-voice` into a new `integration` branch from `main`. Resolve `progress.md` conflicts by keeping every track's section.
2. Act on every track's Integration notes. Move new `RED_*` settings into `Settings` and `.env.example`, and add `-r requirements-voice.txt` and `-r requirements-ui.txt` to `requirements.txt`.
3. Wire the full loop in `__main__.py`: trigger (hotkey or wake word) → record → transcribe → route → confirm (spoken, with typed as fallback) → run → overlay and speech. Keep typed mode and `--dry-run`.
4. Use `known_folders` in the music tool's default folder, and use `spoken_ask` in the `Executor`.
5. Update `README.md` for users, `AGENTS.md`, and this file's status table.
6. Run every test, including the real-model ones, and give the user the merged list of manual checks.
7. Ask the user before merging into `main`, removing the worktrees (`git worktree remove`), or tagging `v0.1.0`. Exception: for the 2026-11-08 overnight run, the user approved merging A, C and B into `main` without asking (with `--no-ff`, pushed after each merge, and any merge with an unclear conflict or a real test failure undone and left out). Removing worktrees and tagging still need asking.

### 8.10 Prompts for the three sessions

Paste one prompt into each session.

**Session 1: Track A**

```text
You are the Track A session (actions and confirmation) of three Claude Code sessions building Red in parallel. Tracks B (voice) and C (overlay, music, repo sync) are running at the same time in other sessions, so stay strictly inside your own files.

Before doing anything else, read D:\RED\red\progress.md (all of it, especially sections 7.1 and 8) and D:\RED\red\AGENTS.md.

1. Create your worktree: git -C D:\RED\red worktree add D:\RED\worktrees\a -b track-a-actions
   If it already exists, it's from an earlier Track A run, so continue in it. If git reports a lock error, retry.
2. Work only in D:\RED\worktrees\a. Follow every rule in progress.md section 8.3, edit only the files Track A owns (8.4), and build what "A provides" in the contracts (8.5) with those exact names and signatures.
3. Do the Track A checklist (8.6) to spec 7.1 and meet its "Done when".
   - Use the shared D:\RED\.venv and install nothing new.
   - Run tests with --basetemp="D:\RED\cache\pytest-tmp-a".
   - For real-model tests, use the shared Ollama on 127.0.0.1:11434 as described in 8.3.
   - Never schedule a real shutdown or restart, and never open real windows in tests. Use fakes passed in through constructors.
4. Commit to track-a-actions as often as you like, with messages that start with "Track A:". Don't push, merge, or touch main or the other worktrees.
5. Ask me only when you're blocked on a decision that's mine. Otherwise use the defaults in progress.md section 10 and record your choices.
6. When you finish: make sure all tests pass, update only section 8.6 of progress.md (checkboxes, Decisions, Integration notes, Manual checks for the user), commit, and tell me what's done, anything left, and the checks I need to do by hand.
```

**Session 2: Track B**

```text
You are the Track B session (voice) of three Claude Code sessions building Red in parallel. Tracks A (actions and confirmation) and C (overlay, music, repo sync) are running at the same time in other sessions, so stay strictly inside your own files.

Before doing anything else, read D:\RED\red\progress.md (all of it, especially sections 7.2 and 8) and D:\RED\red\AGENTS.md.

1. Create your worktree: git -C D:\RED\red worktree add D:\RED\worktrees\b -b track-b-voice
   If it already exists, it's from an earlier Track B run, so continue in it. If git reports a lock error, retry.
2. Work only in D:\RED\worktrees\b. Follow every rule in progress.md section 8.3, edit only the files Track B owns (8.4), and build what "B provides" in the contracts (8.5) with those exact names and signatures. Track A's confirm.py won't exist in your branch, so make spoken_ask match the Ask signature in 8.5 without importing it.
3. Do the Track B checklist (8.7) to spec 7.2 and meet its "Done when".
   - Create your own venv in the worktree (py -3.11 -m venv .venv) with PIP_CACHE_DIR=D:\RED\cache\pip. Never install into D:\RED\.venv.
   - Pin every package in requirements-voice.txt after checking it installs on Windows with Python 3.11.
   - Run tests with --basetemp="D:\RED\cache\pytest-tmp-b".
   - Unit tests must not need a microphone, speakers or a real keyboard hook. Use fake audio, fake models and a fake keyboard.
   - Run Whisper on the CPU (int8) when testing, because Track A or C may have the 7B model on the GPU.
   - Put models only under D:\RED\models\whisper, D:\RED\models\piper and D:\RED\models\wakeword.
   - Anything that needs my voice or ears goes in "Manual checks for the user", with exact steps for python -m red.voice_demo.
4. Commit to track-b-voice as often as you like, with messages that start with "Track B:". Don't push, merge, or touch main or the other worktrees.
5. Ask me only when you're blocked on a decision that's mine. Otherwise use the defaults in progress.md section 10 and record your choices.
6. When you finish: make sure all tests pass, update only section 8.7 of progress.md (checkboxes, Decisions, Integration notes, Manual checks for the user), commit, and tell me what's done, anything left, and the checks I need to do by hand.
```

**Session 3: Track C**

```text
You are the Track C session (overlay, music, repo sync) of three Claude Code sessions building Red in parallel. Tracks A (actions and confirmation) and B (voice) are running at the same time in other sessions, so stay strictly inside your own files.

Before doing anything else, read D:\RED\red\progress.md (all of it, especially sections 7.3, 7.4, 7.5 and 8) and D:\RED\red\AGENTS.md.

1. Create your worktree: git -C D:\RED\red worktree add D:\RED\worktrees\c -b track-c-ui-tools
   If it already exists, it's from an earlier Track C run, so continue in it. If git reports a lock error, retry.
2. Work only in D:\RED\worktrees\c. Follow every rule in progress.md section 8.3, edit only the files Track C owns (8.4), and build what "C provides" in the contracts (8.5). Track A's known_folders.py won't exist in your branch, so use a simple Music-folder default and note the swap in your Integration notes.
3. Do the Track C checklist (8.8) to specs 7.3, 7.4 and 7.5 and meet its "Done when".
   - Create your own venv in the worktree (py -3.11 -m venv .venv) with PIP_CACHE_DIR=D:\RED\cache\pip. Never install into D:\RED\.venv.
   - Pin every package in requirements-ui.txt after checking it installs on Windows with Python 3.11.
   - Run tests with --basetemp="D:\RED\cache\pytest-tmp-c" and overlay tests with QT_QPA_PLATFORM=offscreen.
   - Test the repo sync tool against temporary repos you create, never against my real repos, and never pull, push or change a repo.
   - Don't leave music playing or windows open.
   - For real-model routing tests, use the shared Ollama on 127.0.0.1:11434 as described in 8.3, and check that the existing tools still route correctly with your new tools registered.
4. Commit to track-c-ui-tools as often as you like, with messages that start with "Track C:". Don't push, merge, or touch main or the other worktrees.
5. Ask me only when you're blocked on a decision that's mine. Otherwise use the defaults in progress.md section 10 and record your choices.
6. When you finish: make sure all tests pass, update only section 8.8 of progress.md (checkboxes, Decisions, Integration notes, Manual checks for the user), commit, and tell me what's done, anything left, and the checks I need to do by hand.
```

### 8.11 Phase 1 result (2026-11-08, about 10:45)

Tracks A, B and C finished early and were merged into `main` with `--no-ff`, in the order A, C, B, and pushed after each merge (head `e2f5b29`):
- after A: 150 tests pass
- after C: 290 pass in the UI venv
- after B: 351 pass in the voice venv

No conflicts. The voice tests can't be collected in the UI venv, and the shared venv lacks both sets of packages. Fixing that is the first job of Track D.

### 8.12 Phase 2: three new tracks, until the 13:15 stop

The same three sessions continue. Each one starts a **new branch from the merged `main`** in its **existing worktree**. Every rule in 8.3 still applies, with the changes below. Work through your checklist in order. Push after each item. At 13:15, stop new work, finish the current step, update your section, commit and push. Then send a one-line report to the planning session `red-a7`.

| Track | Session (Phase 1 track) | Worktree | Branch | Work |
|---|---|---|---|---|
| D | `red-c3` (A) | `D:\RED\worktrees\a` | `track-d-integration` | Make Red one app: the full voice loop in `python -m red`, settings, setup, docs (the old 8.9 steps 2 to 6) |
| E | `red-10` (B) | `D:\RED\worktrees\b` | `track-e-hey-red` | Wake phrase "Hey Red": a working detector today, then a trained model |
| F | `red-62` (C) | `D:\RED\worktrees\c` | `track-f-jarvis-tools` | More everyday PC abilities (the "Jarvis" list in section 2, and more) |

Start each track with:

```powershell
git -C D:\RED\worktrees\<a|b|c> fetch origin
git -C D:\RED\worktrees\<a|b|c> switch -c <branch> origin/main
```

**Naming:** Red's name and wake phrase is **"Hey Red"**. "Jarvis" is only the user's shorthand for the kind of assistant Red should be. It must not appear as a wake word, default, prompt or user-facing text.

**Changes to 8.3:**
- Track D is now the only track that installs into the shared `D:\RED\.venv`, with `pip install -r requirements.txt` once that file includes the voice and UI requirements. E and F keep using their worktree venvs.
- pytest temp folders: `pytest-tmp-d`, `-e`, `-f`.
- The GPU is shared with the 7B model. Track E may train on the GPU, but must fall back to the CPU (or smaller batches) on out-of-memory errors, and must never stop Ollama.

**File ownership in Phase 2:**

| Owner | Files |
|---|---|
| D | `red/__main__.py`, `red/config.py`, `.env.example`, `requirements.txt`, `pyproject.toml`, `red/executor.py`, `red/confirm.py`, `red/overlay.py`, `red/tools/music.py` and `red/tools/git_sync.py` (only the integration-note changes), `README.md`, `AGENTS.md`, new tests for the main loop |
| E | `red/listener.py`, `red/voice_demo.py`, `red/audio.py`, `red/stt.py`, `red/tts.py`, `red/voice_confirm.py`, `requirements-voice.txt`, new `red/wakeword.py` (or similar), new `scripts/train_hey_red/`, new `requirements-train.txt`, the voice tests |
| F | `red/tools/__init__.py`, `red/tools/system.py`, `red/tools/web.py`, `red/tools/base.py`, `red/router.py`, `red/llm.py`, new `red/tools/*.py`, `requirements-ui.txt`, the routing tests (`tests/test_integration_*.py`, `tests/test_router.py`), new tool tests |
| Nobody (only the final merge) | `CLAUDE.md`, `red/downloads.py`, `red/process.py`, `red/allowlist.py`, `red/known_folders.py`, other sections of this file |

**Contracts:** keep every Phase 1 signature in 8.5, plus the additions in the Integration notes. D calls `Listener(..., wakeword=settings.wakeword)` and `default_registry()`, and must not depend on anything E or F add. If the wake word can't start, D keeps going with the hotkey only and says so once. E keeps the `Listener` API and makes `"hey_red"` a valid `wakeword` value. F's tools need no constructor arguments in `default_registry()`, and use `ToolError` for messages meant for the user.

### 8.13 Track D: integration

Done when, on this machine, `python -m red`:
- waits for Ctrl+Alt+R (and the wake word when it's available)
- shows the overlay
- listens, routes, asks "yes?" aloud for anything destructive, acts, and answers aloud

It also needs a typed mode, `--dry-run` still working, `python -m red setup` fetching everything, and every test passing in the shared venv.

- [ ] Shared venv complete. **Partly done:** `requirements.txt` now has `-r requirements-voice.txt` and `-r requirements-ui.txt`. **Not installed:** Claude Code's permission check blocked `pip install` into `D:\RED\.venv` (see Integration notes), so the user needs to run one command.
- [x] Every new `RED_*` setting moved into `Settings` and `.env.example`, with `RED_WAKEWORD` defaulting to `hey_red` and `RED_WHISPER_DEVICE` defaulting to `cpu`
- [x] `python -m red setup` also downloads the voice models
- [x] Voice loop in `__main__.py` with `run_with_overlay`. Overlay states and music pausing as described in Track B's and C's integration notes, and `spoken_ask` in the `Executor` with typed fallback
- [x] Modes: voice (default), `--typed`, `--dry-run`, `route` (and `run`). Hotkey only if the wake word fails to start
- [x] `music_dir()` uses `known_folder("music")`; `repos_file()` uses `Settings`; `last_details` goes into the overlay and `commands.jsonl`
- [x] README for users (how to talk to Red, `allowlist.toml`, `repos.toml`, music, voice settings, "Hey Red") and AGENTS.md (new commands and layout). Status table in section 1 updated
- [x] Manual checks merged into one list for the user (below)

**Result (2026-11-08, about 11:10):**
- Unit tests:
  - Shared venv, without the 7 voice test files it can't import yet: 296 passed, 44 skipped.
  - Track B's venv, every test file: 384 passed, 51 skipped.
  - Track C's venv, with `QT_QPA_PLATFORM=offscreen`: 323 passed, 42 skipped.
- Real models: 42 routing tests (`test_integration_llm.py` and `test_integration_c_tools.py`) and 7 voice-model tests pass.
- A real start of `python -m red` (Track B's venv, so no PySide6 and notifications instead of the overlay): it connected to the shared Ollama, loaded Whisper on the CPU (int8), reported once that "Hey Red" isn't available yet, and waited for Ctrl+Alt+R.

Decisions:
- **The voice loop is `VoiceApp` in `red/__main__.py`.** Every part is passed in: a `Voice` bundle (transcriber, speaker, record, chime, listener factory, `spoken_ask` factory), the overlay, the music player, and the typed fallback. `load_voice()` builds the real parts with lazy imports, so typed mode, `route`, `run` and the core tests don't need numpy or Qt. Without the voice packages, `python -m red` exits with code 2 and suggests `pip install -r requirements.txt` or `--typed`.
- **Modes:** voice is the default. `--typed` runs typed commands, and `--dry-run` only shows them; the two flags exclude each other. `run "<command>"` respects `--dry-run`, and `route` always only shows.
- **Wake word fallback:** if the `Listener` raises while it's built or started (an unknown name like `hey_red` before Track E lands, a missing model, or no microphone), Red rebuilds it with the hotkey only. It says so once, in the console and in the overlay's ready text. The error details go to `red.log` only, because B's error message lists the other openWakeWord names, including the one that must not appear. If the hotkey is off too, Red stops with a clear message.
- **Overlay sequence per command:**
  1. `listening` ("Listening...")
  2. `thinking`, then `thinking` again with the transcript in quotes (plus "Checking your repos..." for `check_repos`)
  3. `confirm` with the question
  4. `speaking` with the reply, plus `last_details` on the next lines
  5. `idle` with the reply, so it stays readable for 3 s before hiding

  At startup, Red shows `idle` with "Red is ready. Press Ctrl+Alt+R or say "Hey Red", then speak." Details are shown, not spoken.
- **Confirmation in voice mode:** `with_fallback(spoken, typed_ask)`. The typed console prompt is used only if the spoken ask raises, for example on a microphone error. A spoken timeout counts as an answer and cancels, so you never wait 30 s twice.
- **Music pausing** uses the new `music.active_player()`, which never creates a player. Music that's playing is paused for the whole command and resumed afterwards, except after a music command (`play_music`, `stop_music`, `pause_music`, `resume_music`, `next_song`).
- **One failing command never stops Red.** Any exception in `handle()` shows `error`, says "Sorry, something went wrong.", and Red keeps listening. Silence gives "I didn't hear anything."; an empty transcript gives "Sorry, I didn't catch that."; a routing error gives "Sorry, I didn't understand that."
- **Settings:**
  - `RED_HOTKEY` and `RED_WAKEWORD` accept `off`, `none`, `0`, `no`, `false` or `disabled`. An empty value means the default.
  - `RED_WAKEWORD_THRESHOLD` must be between 0 and 1. `RED_WHISPER_DEVICE` must be `auto`, `cuda` or `cpu`.
  - `RED_MUSIC_DIR` expands `%VARS%` and `~`.
  - `Settings` has a new `repos_path` property.
  - `config.py` holds the voice defaults as plain strings, so it never imports the voice modules.
- **`setup`** also copies `repos.example.toml` to `config\repos.toml` if it's missing. It stops a Red-started Ollama before the voice downloads. If the wake word can't be fetched yet, Red prints a message and setup still succeeds. Without the voice packages, setup exits with code 1.
- **Quitting:** Ctrl+C stops the listener and the speaker, prints "Bye." and exits with code 0. Ollama is stopped in `main()`'s `finally`.

Integration notes:
- **The shared venv still needs the voice and UI packages.** Claude Code's auto-mode permission check denied `pip install -r requirements-dev.txt` into `D:\RED\.venv`, and Track A's original prompt also said to install nothing there. I didn't try another way. Another session shouldn't do it either: this is the user's decision. After merging, the user should run:
  ```powershell
  $env:PIP_CACHE_DIR = "D:\RED\cache\pip"
  D:\RED\.venv\Scripts\python.exe -m pip install --only-binary=:all: -r D:\RED\red\requirements-dev.txt
  D:\RED\.venv\Scripts\python.exe -m pip check
  ```
  Then run the full suite there with `QT_QPA_PLATFORM=offscreen`.
- **Track E:**
  - D calls `Listener(handle, settings.hotkey, settings.wakeword, model_dir=models\wakeword, threshold=settings.wakeword_threshold)`. Once `"hey_red"` is valid there, nothing in D needs to change.
  - `setup` calls `listener.download_wakeword(models\wakeword, "hey_red")`. It should fetch whatever "Hey Red" needs, or return without error.
  - `voice_demo.VoiceConfig` could now read `load_settings()` instead of the environment. Its default is still `hey_jarvis` until E changes it.
- **Track F:**
  - Any tool can set a `last_details` string. The Executor logs it, and the voice loop shows it in the overlay.
  - Tools that control Windows media keys aren't in `MUSIC_TOOLS`, so after them Red resumes its own player. Add their names to `MUSIC_TOOLS` in `__main__.py` if that's wrong.
- **Merge order D, F, E:** D touches `music.py` and `git_sync.py` only in `music_dir()`, `active_player()` and `repos_file()`. Its test files are new: `tests/test_voice_app.py` and `tests/test_settings_voice.py`. `tests/test_main.py` changed so that the typed loop uses `--typed`.

Manual checks for the user (all of Phase 1 plus Track D, in one list). First install the packages (the Integration notes above), then in PowerShell:

```powershell
cd D:\RED\red
$env:RED_HOME = "D:\RED"
D:\RED\.venv\Scripts\Activate.ps1
python -m red setup
```

**Red as a whole (Track D)**
1. Run `python -m red`. A dark card appears in the bottom-right corner, above the taskbar, saying Red is ready, and the console prints `Ready. Press Ctrl+Alt+R or say "Hey Red", then speak.` If "Hey Red" isn't merged yet, you see one line saying only the hotkey works.
2. Press Ctrl+Alt+R. You hear a beep. Say "open my downloads folder". The card goes through Listening, Thinking (with your words), and the reply. Explorer opens Downloads, and Red says "Opening Downloads."
3. Press Ctrl+Alt+R and say "shut down in 60 minutes". Red asks aloud with the exact time, and the card shows the question. Say "no": Red says "Cancelled." and no Windows notice appears.
4. Do it again and say "yes". The Windows shutdown notice appears. Then press Ctrl+Alt+R and say "cancel the shutdown". Red confirms it's cancelled.
5. Press Ctrl+Alt+R and stay silent. Red says "I didn't hear anything."
6. Play music ("play some music"), then press Ctrl+Alt+R and give any other command. The music pauses while Red listens and talks, then resumes. "stop the music" stops it, and it doesn't come back.
7. Set up `D:\RED\config\repos.toml` and say "check my repos". The card shows one line per repo, Red speaks a short summary, and `D:\RED\logs\commands.jsonl` has a `details` field.
8. Once Track E is merged, say "Hey Red", then a command. It should work like the hotkey.
9. `python -m red --typed` runs typed commands. `python -m red --dry-run` only shows the tool calls.
10. Press Ctrl+C. Red prints "Bye.", and Task Manager shows no leftover `python.exe` or a Red-started `ollama.exe`.

**Actions and confirmation (Track A)**

11. In `python -m red --typed`, type "restart in 10 minutes" and don't answer. After 30 s you see "No answer, so I cancelled it.", and no Windows notice appears.
12. With nothing scheduled, "cancel the shutdown" says "Nothing was scheduled". This checks that `shutdown /a` returns 1116 on your PC.
13. "open Documents" and "open Pictures" open the OneDrive folders. "open notepad", "open calculator", "open file explorer" and "open task manager" each start; Task Manager may show a UAC prompt. "open youtube" opens your default browser.
14. In `D:\RED\config\allowlist.toml`, set `projects` to a real folder, and check "open projects" and "open vs code".

**Voice (Track B)**

15. Speakers: `python -m red.voice_demo --say "Hello, I am Red."` is spoken clearly, once.
16. Microphone: `python -m red.voice_demo --levels`. Speech should read above about 0.02 and silence below 0.008. If the wrong microphone is used, set `RED_MIC_DEVICE` to part of its name.
17. The hotkey only starts one recording on a quick double press. Recording stops about a second after you finish speaking.
18. Spoken yes/no: "yes" confirms; "no" and silence (after 30 s) cancel.
19. Optional: `python -m red.voice_demo --device cuda --no-wakeword` falls back to the CPU with a warning, unless `nvidia-cublas-cu12` is installed.
20. No antivirus warning about the keyboard hook.

**Overlay, music, repo sync (Track C)**

21. `python -m red.overlay`: the card goes through every state, never takes focus, lets clicks through, hides after about 3 s, and the program exits. Also try a high-DPI or second monitor.
22. `python -m red.overlay --fallback`: 4 Windows notifications appear.
23. Music: play, pause, resume, next song and stop all work on your Music folder (mp3, ogg, opus, flac or wav; not m4a).
24. Repo sync on your real repos is read-only. `git status` looks the same afterwards. A repo with expired credentials reports "couldn't fetch" within about 45 s, with no login prompt.

### 8.14 Track E: "Hey Red"

Done when saying "Hey Red" triggers Red with the default settings, a normal conversation or video doesn't trigger it, "Hey Jarvis" is gone from defaults, docs and tests, and the tests pass.

- [x] **A "Hey Red" detector that works today, without training.** For example: voice-activity gating plus a small pinned Whisper model (such as `tiny.en` or `base.en`) on short clips, matching "hey red" and close variants ("hey, red", "hay red"). Use the existing `Listener` detector interface. Measure CPU use while idle and while people are talking, and keep it low
- [x] `RED_WAKEWORD=hey_red` is the default. `RED_WAKEWORD_THRESHOLD` (or a sensible equivalent) tunes it. Remove `hey_jarvis` as a default and from docs. Other openWakeWord names and `.onnx` paths can stay as options
- [x] `voice_demo.py`: use `"Hey Red"` everywhere, and replace `_is_yes` with `red.confirm.is_yes`, which now exists on `main`
- [x] Real-model tests: Piper saying "Hey Red" (several voices and speeds) triggers it; a set of ordinary sentences, including ones with "red" in them ("I read the red book"), doesn't
- [x] **A custom openWakeWord "hey_red" model,** if it's feasible on this machine before 13:15. Put the scripts in `scripts/train_hey_red/` and the training deps in `requirements-train.txt`. Generate synthetic speech with Piper voices, add noise, and train. Compare false accepts and misses against the detector above, and make whichever is better the default. If training isn't feasible (Windows-only tooling, time, or data size), write down exactly why and what it would take
- [x] Manual checks for the user, with exact commands

**Result (2026-11-08):** "Hey Red" works with the default settings, and no Jarvis remains in Track E's code, demo or tests.
- **Built-in detector** (`red/wakeword.py`): Silero VAD feeds short, isolated bursts of speech to a pinned Whisper `tiny.en` model on the CPU.
  - With Piper speech it triggered on every "Hey Red": 78 of 78, across 13 voices and speeds from 0.8× to 1.3×.
  - It ignored ordinary speech, including "I read the red book", "Hey, Fred" and "Hey, ready?".
  - CPU use is about 1% of one core in a quiet room. During continuous conversation it's about 20% of one core, because Whisper only runs on short, isolated bursts.
- **Trained openWakeWord model:** 6,000 positives and 26,000 negatives, generated on this machine in about 20 minutes. On voices it never heard, it got 29/36 hits and 10/102 close-call false accepts, against 36/36 and 0/102 for the built-in detector. So the built-in detector stays the default.
- **Tests:** 386 unit tests pass with real models skipped. With `RED_INTEGRATION=1`, the 38 real-model voice tests pass, all on the CPU.
- **Late finish:** the training run's completion notice reached this session after 13:15, so the step was finished at about 17:30 and nothing new was started after it.

Decisions:
- **How the detector works.** Silero VAD (`silero_vad_v6.onnx`, bundled with faster-whisper) runs on every 32 ms. Whisper is only asked about a burst of speech that meets all three conditions:
  - it lasts 0.35–1.6 s
  - at least 0.25 s of quiet comes before it
  - 0.3 s of quiet comes after it

  Long speech is never transcribed. This is what keeps CPU use low in conversations and videos. The cost is that you have to say "Hey Red" on its own, pause, and give the command after the beep. "Hey Red, open Downloads" in one breath doesn't trigger.
- **Whisper `tiny.en`** (`Systran/faster-whisper-tiny.en` at `0d3d19a`, 75 MB) with `hotwords="Hey Red"`, beam size 1, 2 CPU threads, and a 12-token cap. It takes about 0.3 s per check. Without the hotword bias it misheard about 1 in 12 phrases ("He read", "Hey, Fred"); with it, 60/60 were right. `base.en` was just as accurate but twice as slow. Faster-whisper's `chunk_length` gives no speed-up, because CTranslate2 always encodes a 30-second window.
- **The score `RED_WAKEWORD_THRESHOLD` applies to,** default 0.5:
  - "hey red" scores 1.0
  - "heyred" scores 0.9
  - "hi red" scores 0.7
  - "hey read" scores 0.6
  - any extra words score 0.45, which is below the default

  The extra-words rule is there because the hotword bias can turn "a red light" into "Hey Red Light". The phrase must start the clip, so "they said red" never matches. "a" is not accepted as "hey". Raise the threshold to 0.65 to accept only clear "hey red" or "heyred".
- **Known confusion:** "Hey, Ed" can sound exactly like "Hey Red", and nothing at the transcript level can tell them apart.
- **`hey_jarvis` is removed** from the pinned wake words. `hey_mycroft`, `hey_rhasspy`, `alexa` and `.onnx` paths remain as options. Its model file from Phase 1 is still in `D:\RED\models\wakeword`, unused.
- **Six more Piper voices are pinned:** amy, ryan, joe, alan, jenny_dioco, and libritts_r, which has 904 speakers. They're for tests and training, and also work as `RED_PIPER_VOICE` values.
- **Training approach:** reduced, on Windows, with no datasets. Synthetic Piper clips are augmented and turned into openWakeWord embeddings, then openWakeWord's standard small classifier head is trained with CPU PyTorch. The ONNX graph is written directly. Why it's weaker, and what a better model would take (real negative speech such as the ~17 GB ACAV100M features, real room recordings, recordings of you), is in `scripts/train_hey_red/README.md`. The GPU wasn't used: the head trains in under a minute on the CPU, and that left the GPU to Ollama.

Integration notes:
- **Nothing to change in Track D's code.** `Listener(..., wakeword="hey_red")` and `download_wakeword(models\wakeword, "hey_red")` now work, and `python -m red setup` will fetch Whisper `tiny.en`, 75 MB, into `models\whisper\tiny.en`. Until E is merged, `main` falls back to hotkey only, as designed.
- **Tell users to pause** after "Hey Red", in the README "how to talk to Red" section. `README.md` is Track D's file, so I haven't changed it.
- **New Transcriber keyword arguments:** `vad_filter`, `hotwords`, `max_new_tokens`. New in `listener`: `make_detector()`, now the default `detector_factory`, and `HEY_RED`. New module: `red/wakeword.py`.
- **New files:** `requirements-train.txt` (torch 2.15.0 CPU, onnx 1.23.2) and `scripts/train_hey_red/`. Neither is needed to run Red. `tests/test_train_hey_red.py` skips its ONNX test where torch isn't installed.
- **Idea for later:** a two-stage detector. The trained model, at a low threshold, would decide which clips Whisper checks. That would bring CPU use during conversation down towards the trained model's 3% while keeping Whisper's accuracy.

Manual checks for the user (from `D:\RED\worktrees\b`; after the merge, from `D:\RED\red` with the shared venv):

```powershell
$env:RED_HOME = "D:\RED"
.\.venv\Scripts\Activate.ps1
python -m red.voice_demo --setup
python -m red.voice_demo
```

1. **Trigger:** wait for `Ready. Press Ctrl+Alt+R or say "Hey Red"...`. Say "Hey Red" on its own and pause. You should hear the beep within about a second; then say a command. Try it 10 times at normal, quiet and fast speech, and from across the room. Note how many work.
2. **Phrase and command in one breath:** "Hey Red, open Downloads" said without a pause should not trigger. That's the known trade-off described above.
3. **No false triggers:** leave it running for 10 minutes while you talk normally, including sentences like "I read the red book" and "hey, ready?", and play a YouTube video or podcast. Count any false beeps.
4. **CPU:** with the demo running, watch `python.exe` in Task Manager. It should use about 1% or less in a quiet room, and stay below about 10% of total CPU while a video plays.
5. **Tuning:** if it misses you, set `$env:RED_WAKEWORD_THRESHOLD = "0.4"`. If it fires falsely, set it to `"0.65"`. Restart the demo and report the value that works.
6. **Trained model (optional):** `$env:RED_WAKEWORD = "D:\RED\models\wakeword\hey_red_v0.1.onnx"`, then `python -m red.voice_demo`. Compare it with check 1. Expect more misses and false triggers. To get the default back, run `Remove-Item Env:RED_WAKEWORD`.
7. **In the full app, after the merge:** `python -m red`. Saying "Hey Red" should show the overlay and start listening, as the hotkey does.

### 8.15 Track F: everyday PC abilities

Done when each new tool works from `Tool.run()` with fakes, routes correctly with the real model (in its own `tests/test_integration_f_tools.py`), the existing commands still route correctly, and all tests pass. Do them in this order and push after each:

- [x] **Office apps:** "open PowerPoint / Word / Excel / Outlook" as built-in apps when installed. Find them through App Paths in the registry, not by guessing paths
- [x] **`web_search`:** "search the web for X" opens a search in the default browser, using a fixed URL template with the query properly encoded
- [x] **`find_file`:** "find my resume", "where is X". Searches known and allowlisted folders, or the Windows Search index, by name. Read-only, with a time limit and a cap on results. It replies with the best match and offers to open it
- [x] **`compose_mail`:** "compose a mail to X about Y" opens a new draft through a `mailto:` link, with the recipient, subject and body properly encoded. It never sends
- [x] **Quick system actions:**
  - lock the PC
  - volume up, down and mute
  - media play/pause and next
  - open a Windows Settings page from a fixed list of `ms-settings:` pages
  - tell the time, date and battery level
  - take a screenshot into Pictures

  Sleep and empty Recycle Bin are destructive, so they need `destructive = True` and `describe()`
- [x] **Router at scale:** with about 20 tools, check the prompt still fits `num_ctx`, and that routing accuracy and speed stay good. Tune descriptions, the prompt or `num_ctx` if needed, and record the before and after numbers
- [x] Update the "Jarvis" table in section 2 (the status column)

Result (2026-11-08, finished about 11:30, branch `track-f-jarvis-tools`, pushed after each item):
- 496 unit tests pass and 92 are skipped, run in the worktree venv with the UI and voice requirements installed and `QT_QPA_PLATFORM=offscreen`.
- With `RED_INTEGRATION=1`, all 85 real-model tests pass: 43 in the new `tests/test_integration_f_tools.py`, 29 in `tests/test_integration_c_tools.py` and 13 in `tests/test_integration_llm.py`.

**Router numbers** (Qwen2.5 7B Q4_K_M, `num_ctx` 4096, temperature 0, the same 71 commands, measured with Ollama's `prompt_eval_count`; timings are noisy because Tracks D and E shared the GPU):

| Registry | Tools | Prompt tokens | Correct | Median | p90 |
|---|---|---|---|---|---|
| Before: Phase 1 (only its 28 commands) | 12 | 924 | 28/28 | 1.13 s | 1.37 s |
| All tools, untuned | 24 | 1,946 | 69/71 | 1.21 s | 1.68 s |
| All tools, tuned (final) | 24 | 2,090 | 71/71 | 0.80 s | 1.08 s |
| Phase 1 tools with the final prompt | 12 | 1,023 | 28/28 | 0.73 s | 0.83 s |

The prompt uses about half of `num_ctx` 4096, so `num_ctx` stays at 4096 (no extra VRAM). Before and after tuning, the model was given the 24-tool JSON schema as Ollama's `format`; the schema isn't counted in the prompt tokens.

Decisions:
- **Office and other well-known apps:** `red/tools/apps.py` maps a fixed list of spoken names to App Paths keys, for example PowerPoint, "ppt" and "power point" to `powerpnt.exe`. The list also covers Word, Excel, Outlook (falling back to the new `olk.exe`), OneNote, Access, Publisher, Teams, Chrome, Edge, Firefox, VS Code, Paint, Snipping Tool, Terminal, VLC, Windows Media Player and WinRAR.
  - Red reads HKCU, then HKLM in both registry views, and the file must exist.
  - Lookup order in `open_app`: allowlist, then the built-in apps, then App Paths.
  - Store apps (under `WindowsApps`) are started by their App Paths name through the shell, because they can't be started by path. Everything else is started by full path.
  - A known app that isn't installed gets "X doesn't seem to be installed." `apps.py` has its own name normalizer, because importing `allowlist.normalize_app` causes a circular import.
- **`web_search`:** fixed URL templates. The query goes through `quote_plus`, and `site` is a closed enum (`web`, `youtube`, `images`, `maps`, `news`, `wikipedia`). The web engine is `RED_SEARCH_ENGINE` (`google`, `bing` or `duckduckgo`), default Google; anything else falls back to Google.
- **`find_file`:**
  - Breadth-first name search of Desktop, Documents, Downloads, Pictures, Videos and Music (in that order), then the allowlist's folders.
  - Skips hidden and system folders and big tool folders (`node_modules`, `.git`, `.venv`, `AppData`, `dist`, ...).
  - Stops after 4 seconds or 300,000 entries, and keeps the best 5.
  - Ranking, best first: exact name, every word, every word inside the name, close (misheard) match. Ties go to files over folders, then newer over older.
  - On this PC, a full search of the known folders took 1.5 s over 13,000 entries.
  - **The Windows Search index wasn't used:** it needs pywin32 or ADO through COM, and the folder walk is fast enough.
  - `open_found_file` ("open it", "open the second one") opens a match from the last search. Programs, scripts and shortcuts (`.exe`, `.bat`, `.ps1`, `.py`, `.lnk`, ...) are never opened: Red opens their folder and says so.
- **`compose_mail`:**
  - Builds an RFC 6068 `mailto:` link with every part percent-encoded and CRLF line breaks, and opens it with `os.startfile`. It never sends, and Red has no access to any mail account.
  - Only strictly valid addresses go into the link. Names ("mom", "Alex Kim") become addresses only through `RED_HOME\config\contacts.toml`, under `[contacts]`. An unknown name leaves the recipient empty, and the reply says so.
  - The body is cut at 1,500 characters, because long `mailto:` links can fail to open.
- **Quick actions** (`red/tools/quick.py`):
  - Volume and media use the global keys through `keybd_event`. Up and down move 2% per press; the default step is 10%.
  - "Set to N%" presses volume down 50 times, then up N/2 times.
  - Mute and unmute are made reliable by pressing up then down first (any volume key unmutes), then mute if needed.
  - `pause_music`, `resume_music` and `next_song` are now media-aware subclasses with the same names. They use Red's own player when it has a song, and otherwise the play/pause or next media key, so they also work for Spotify or a YouTube tab. This avoids a second, competing set of pause and next tools. `previous_track` is media-key only.
  - `open_settings` takes a closed enum of 26 `ms-settings:` pages.
  - `tell_status` answers time, date or battery; battery comes from `GetSystemPowerStatus`.
  - `take_screenshot` presses Windows+Print Screen, so Windows saves the full screen, at the right DPI and on every monitor, to Pictures\Screenshots. Red waits up to 3 seconds for the new file and says its name. This avoids writing a DPI-aware capture without Pillow.
  - `lock_pc` uses `LockWorkStation` and isn't destructive.
  - `sleep_pc` (`SetSuspendState(False, False, False)`) and `empty_recycle_bin` (`SHEmptyRecycleBinW`, after a read-only `SHQueryRecycleBinW`) are destructive, with `describe()`, for example "Permanently delete 3 items (5.0 MB) from the Recycle Bin".
- **Router tuning:**
  - Two misroutes fixed by descriptions: "skip this song" going to `previous_track`, and "check for windows updates" going to `open_app`.
  - Three new prompt rules:
    1. A word with no request in it, like "banana", is unclear: use `none`. Without this rule, "banana" went to `web_search`.
    2. General questions go to `web_search`. Without it, "what is the meaning of life" went to `tell_status`.
    3. Pick the most specific tool (`web_search` over `open_url`, `open_settings` over `open_app`).
  - **Known quirk:** "show me pictures of X" usually goes to `open_url` with a Google Images URL the model builds itself, instead of `web_search` with `site: images`. The same page opens and the URL is still checked as http(s), so the test accepts either. Four wordings of the descriptions didn't change it.
- **Fixed during tuning:** `open_url`'s description now says to use `web_search` for searches.

Integration notes:
- **New settings:** `RED_SEARCH_ENGINE`, read in `red/tools/web.py: web_engine()` (default `google`). New config file: `RED_HOME\config\contacts.toml` (`[contacts]` with `name = "address"`), read in `red/tools/mail.py: contacts_file()`. Move them into `Settings` and document them in the README, perhaps with a `contacts.example.toml`. `find_file` uses `known_folders` and the allowlist directly.
- `FindFile` sets `last_details` (one line per match, with full paths), like `CheckRepos`. Show it in the overlay and the log in the same way.
- `default_registry()` now has 24 tools. Every constructor has defaults, and building the registry has no side effects.
- `pause_music`, `resume_music` and `next_song` in `default_registry()` are now the `quick.PauseMedia`, `ResumeMedia` and `NextMedia` subclasses. Track D's music-pausing during recording should keep calling `music.default_player()` directly. It must **not** call these tools, because with Red's player idle they press the media keys.
- `Volume`, the media keys and `take_screenshot` act on the real desktop, so they belong in the manual checks, not in automated tests.
- `router.py` changed only in `SYSTEM_PROMPT` (three new rule lines); `Router` itself is unchanged.
- **Venv:** the worktree venv has `requirements-dev.txt`, `requirements-ui.txt` and `requirements-voice.txt`, and the whole suite runs there. Track D's shared venv needs the same three files.

Manual checks for the user (in `D:\RED\worktrees\c`, `.\.venv\Scripts\python.exe`, `$env:RED_HOME = "D:\RED"`). Each one runs a single tool, for example:
`python -c "from red.tools import default_registry as r; print(r().get('volume').run(action='up'))"`

- **Office:** `get('open_app').run(app='powerpoint')`, then `'word'`, `'excel'`, `'outlook'` and `'paint'` (a Store app). Each should open; close them afterwards.
- **Search:** `get('web_search').run(query='weather in Pune')`, and `.run(query='lofi', site='youtube')`. Check that the browser opens the right results.
- **Find:** `t=r(); print(t.get('find_file').run(name='resume')); print(t.get('find_file').last_details); print(t.get('open_found_file').run())`. Check that the result makes sense, and that it finishes in a few seconds.
- **Mail:** `get('compose_mail').run(to='you@example.com', subject='Test from Red', body='Line one\nLine two')`. A draft should open in your mail app with both lines. Don't send it. If nothing opens, choose a default email app in Windows Settings.
- **Volume and media:** `volume` with `action='down', percent=20`, then `'up'`, `'mute'`, `'unmute'`, and `action='set', percent=30`. Watch the Windows volume flyout. With Spotify or a YouTube tab playing, `get('pause_music').run()`, then `resume_music`, `next_song` and `previous_track`.
- **Settings:** `get('open_settings').run(page='bluetooth')`, then `'windows_update'`.
- **Status:** `get('tell_status').run(what='battery')`, then `'time'` and `'date'`.
- **Screenshot:** `get('take_screenshot').run()`. A new file should appear in Pictures\Screenshots.
- **Lock:** `get('lock_pc').run()`, then sign back in.
- **Sleep (destructive, so try it through Red's confirmation):** in `python -m red --typed` (Track D), say "put the computer to sleep". It should ask first; answer `n` once to check it cancels, then `y`.
- **Recycle Bin (destructive, deletes for real):** with only junk in the Recycle Bin, in `python -m red --typed`, say "empty the recycle bin". Check that the question gives the item count and size, and that `n` cancels.

### 8.16 Final merge (planning session, after 13:15)

Merge with `--no-ff`. Test and push after each merge. A merge with an unclear conflict or a real test failure is undone and left for the user. Then write the morning report.

**Done early (11:30):** D (`ab839d3`) and F (`f48c8e9`) are merged and pushed. Tests: 502 pass in Track B's venv and 410 in Track C's venv (non-voice files), and the skipped tests are real-model tests. Left: E, then the Phase 3 branches (8.17).

### 8.17 Phase 3: while there's time (about 11:35 until the 13:15 stop)

D and F finished early, so those two sessions continue. Track E carries on with 8.14. Same rules as 8.12. New branch from `origin/main` in the same worktree, push after each item, and at 13:15 stop, update your section, commit, push, and send `red-a7` a one-line report.

| Track | Session | Worktree | Branch | Work |
|---|---|---|---|---|
| G | `red-62` (was F) | `D:\RED\worktrees\c` | `track-g-assistant` | Timers and reminders, offline questions, online answers |
| H | `red-c3` (was D) | `D:\RED\worktrees\a` | `track-h-release` | Track F's integration notes, a `doctor` command, release readiness |

**File ownership in Phase 3:**
- **G** owns `red/tools/*` (except `music.py` and `git_sync.py`), `red/router.py`, `red/llm.py`, new `red/scheduler.py`, and its tests.
- **H** owns `red/__main__.py`, `red/config.py`, `.env.example`, `red/executor.py`, `red/overlay.py`, `red/tools/music.py`, `red/tools/git_sync.py`, `requirements*.txt` (except `requirements-voice.txt` and `requirements-train.txt`), `README.md`, `AGENTS.md`, new `contacts.example.toml`, new `CHANGELOG.md`, and its tests.
- E keeps its 8.12 files.

**Contract between G and H (reminders):** G provides `red/scheduler.py` with:

```python
class Scheduler:
    on_due: Callable[[str], None] | None   # set by the app; called from a background thread with the text to say
    def add(self, when: datetime, text: str) -> str: ...  # returns an id
    def cancel(self, id_or_text: str) -> bool: ...
    def pending(self) -> list[tuple[str, datetime, str]]: ...

def default_scheduler() -> Scheduler: ...                 # one per process
```

Reminders survive a restart (stored under `RED_HOME`).

H sets `default_scheduler().on_due` in voice mode. It speaks inside `listener.paused_while()` and shows the overlay. In typed mode it prints. If the import fails, because G isn't merged yet, H skips this.

### 8.18 Track G: assistant abilities

Done when each tool works with fakes, routes with the real model in `tests/test_integration_g_tools.py`, the earlier routing tests still pass, and the prompt still fits `num_ctx`.

- [x] **Timers and reminders:** "set a timer for 10 minutes", "remind me at 3 pm to call mom", "what reminders do I have", "cancel the timer". Built on `red/scheduler.py` (8.17). Times are in the local time zone; reject times in the past and anything more than 7 days ahead
- [x] **Offline questions:** an `answer` tool for general questions ("what is Hugging Face", "explain recursion"). It makes a second local-LLM call for a short spoken answer (2 to 4 sentences). There's no cloud model
- [x] **Online answers:** for "search the web for X and tell me", "what's the weather in Pune", or "latest news about X", fetch a public, keyless source over HTTPS, such as the Wikipedia REST summary API or Open-Meteo for weather, and summarise it with the local model. Use a time limit and say "I'm offline" when there's no network. Keep `web_search` (which opens the browser) for "open a search for X"
- [x] Update the section 2 table

Result (branch `track-g-assistant`, pushed after each item). **The session missed the 13:15 stop:** its time checks were wrong (Git Bash and PowerShell clocks disagreed), and the last item finished at about 17:35. No new work started after that was noticed; only this section was written.
- 594 unit tests pass and 121 are skipped (worktree venv with the UI and voice requirements, `QT_QPA_PLATFORM=offscreen`).
- With `RED_INTEGRATION=1`, 112 real-model tests pass and 1 is an expected failure (see Decisions), across `tests/test_integration_g_tools.py`, `_f_`, `_c_` and `test_integration_llm.py`.
- `tests/test_g_online.py::test_live_sources` passed once against the real Open-Meteo, Wikipedia and Google News, with `RED_ONLINE=1`. Normal runs never use the network.

**Router at 32 tools** (same scratchpad measurement as 8.15, 98 commands): the prompt is 2,749 tokens of `num_ctx` 4096, leaving about 1,100 tokens for the reply (`num_predict` is 256), so `num_ctx` stays at 4096. Accuracy is 96/98, median 0.9 to 1.2 s with the GPU shared. Before compacting, the prompt was 3,034 tokens.

Decisions:
- **Scheduler** (`red/scheduler.py`, the exact 8.17 contract):
  - Reminders are stored in `RED_HOME\data
eminders.json`, written atomically (temp file, then `os.replace`).
  - One daemon thread checks every second. Due reminders wait while `on_due` is unset, so none is lost before the app wires its voice. A handler that raises doesn't stop the others.
  - A reminder that came due while Red was closed is said on the next start as "You missed a reminder at 2:10 PM: …" if it's less than a day late; older ones are dropped.
  - `add()` raises `ValueError` for past times, more than 7 days ahead, empty text, or more than 100 pending. `cancel()` takes an id, or the soonest reminder whose text contains the words.
  - `default_scheduler()` creates and starts it on first use only. Building the registry doesn't touch it.
- **Timers and reminders:**
  - Timers say "Your 10 minute timer is done." (or "Your pasta timer is done."); reminders say "Reminder: call mom."
  - `set_reminder` takes `time` (24-hour `HH:MM`), `day` (today, tomorrow or a weekday) or `in_minutes`.
  - **A time with no day that has already passed today means tomorrow** ("remind me at 9 am", said in the evening). Saying "today" with a past time is rejected, as the spec asks.
  - `cancel_reminder` takes words, "timer" or "all". With no words and only one reminder, it cancels that one; with several, it asks which.
- **`answer`:** a second call to the same local model, with its own JSON schema (`{"answer": …}`), so it works with every backend. Markdown, links and list markers are removed and the reply is cut to 4 sentences. The Router now calls `bind_llm(llm)` on every tool that has one, so `default_registry()` still needs no arguments and `__main__` doesn't change. A real answer took 1.5 s.
- **Online answers** (`red/tools/online.py`):
  - Fixed https URLs only, with the user's words as one encoded query value. 6-second limit, 1 MB cap, User-Agent `Red/0.1 (local voice assistant; https://github.com/AryanLanke/Red)`. No network means "I'm offline, so I can't reach X right now"; a timeout or an HTTP error gets its own short reply.
  - `weather`: Open-Meteo geocoding, then the forecast. **The reply is built from the numbers, not by the model,** so temperatures can't be misread. Place defaults to `RED_WEATHER_PLACE`.
  - `look_up`: Wikipedia opensearch, then the REST page summary, summarised by the local model using only that text, and introduced as "From Wikipedia:". Disambiguation pages say the name means several things. The page URL goes to `last_details`.
  - `news`: Google News RSS (keyless). The top 3 headlines are read as written, with their source; no model summary, so nothing is invented. Edition `RED_NEWS_EDITION` (for example `IN:en`), default `US:en`.
  - Only the search words leave the PC.
- **Router prompt:**
  - Schemas are now printed as compact JSON, which saved about 380 tokens.
  - The question rules were rewritten: `answer` for knowledge, `look_up` for "look up X" or "… and tell me", `web_search` only to open results in the browser.
  - Two short examples were added, worded differently from the tests.
- **Known misroutes, left visible:**
  - "search the web for X and tell me" still goes to `web_search` (it opens the browser instead of answering aloud). The test is marked `xfail` with the reason. Rules and an example didn't fix it reliably.
  - "search youtube for X" sometimes goes to `open_url` with the YouTube results URL. The same page opens, so the test accepts it, as with the pictures case in 8.15.
  - Accepted as better: "look up the weather in Pune" now goes to `weather`, and "who was Alan Turing" may go to `look_up`.

Integration notes:
- **New settings:** `RED_WEATHER_PLACE` and `RED_NEWS_EDITION` (in `red/tools/online.py`). New data file: `RED_HOME\data
eminders.json`, from `scheduler.reminders_file()`. Move them into `Settings`, and add `data` to `ensure_dirs()`.
- Track H wires `default_scheduler().on_due` (8.17).
- `look_up`, `news` and `list_reminders` set `last_details`, like `find_file`.
- `answer` and `look_up` need the Router to have an LLM. In `--dry-run` or without a model, `answer` says the model isn't connected, and `look_up` reads the first sentences of the Wikipedia summary.
- With 32 tools the prompt is about 2,750 tokens. Before adding many more tools, consider raising `num_ctx` (about 60 MB of VRAM per 1,000 tokens for the 7B model) or choosing tools in two steps.
- `default_registry()` now has 32 tools.

Manual checks for the user (in `D:\RED\worktrees\c`, `.\.venv\Scripts\python.exe`, `$env:RED_HOME = "D:\RED"`, after Track H's wiring is merged):
- Say or type "set a timer for 1 minute". After a minute, Red should say "Your 1 minute timer is done."
- Say "remind me in 2 minutes to stretch", then quit Red and restart it after 3 minutes. It should say "You missed a reminder at …: stretch."
- Say "what reminders do I have", then "cancel the timer".
- Say "what is Hugging Face" and "explain recursion". Each answer should be 2 to 4 sentences.
- Say "what's the weather in Pune" (or your city) and check it against a weather site. Say "latest news about India", then "look up the James Webb telescope".
- With Wi-Fi off, say "what's the weather in Pune". Red should say it's offline within a few seconds.

### 8.19 Track H: integration notes and release readiness

Done when Track F's integration notes are done, `python -m red doctor` works, the README covers all 24+ tools, and all tests pass.

- [x] **Track F's integration notes:**
  - `RED_SEARCH_ENGINE` and `contacts.toml` move into `Settings`, with a new `contacts.example.toml`
  - `FindFile.last_details` goes into the overlay and the log
  - music pausing keeps using `music.default_player()`, never the media-key tools
- [x] **Reminders wiring** to `red.scheduler`, per the 8.17 contract, behind a try-import
- [x] **`python -m red doctor`:** checks Python, the packages, `RED_HOME`, Ollama and the model, the microphone (opens it only, doesn't record), the speakers (lists the device, doesn't play), the GPU, the wake word model, and the allowlist, repos and contacts files. Each check gets a clear ✅/⚠️/❌ with a fix
- [x] **Start at login (helper only):** `python -m red startup on|off` creates or removes a shortcut in the user's Startup folder. Tested with a fake folder only; never run for real
- [x] **README** for users: every tool, with an example sentence for each; the troubleshooting section points to `doctor`
- [x] **`CHANGELOG.md`** with a v0.1.0 draft (not tagged)
- [x] **Merged list of manual checks**, phases 1 to 3, for the user (below)

**Result (2026-11-08, about 11:50, branch `track-h-release`, pushed after each item):**
- Unit tests:
  - Track B's venv, with `QT_QPA_PLATFORM=offscreen`: 537 passed, 94 skipped. The skipped tests are the real-model tests.
  - The shared venv still lacks the voice and UI packages (8.13).
- `python -m red doctor` on this PC, in Track B's venv: 0 problems. The 6 warnings are all expected: no PySide6 in that venv, no `.env`, "hey_red" not merged yet, and no allowlist, repos or contacts files yet.
- Every example sentence in the README's "What you can say" table went through the real model (57 sentences). Three wordings misrouted and were replaced:
  - "open projects" went to Documents; it's now "open my projects folder".
  - "open file explorer" went to `open_folder` with `C:\`; it's now "open the file explorer app".
  - "is red pushed?" became a web search; it's now "is my red repo pushed".

Decisions:
- **`Settings`:**
  - `search_engine`: an unknown value means Google, the same as `web_search` itself, so a typo never stops Red.
  - `contacts_path` is the new path for contacts.
  - `setup` also creates `contacts.toml` from `contacts.example.toml`.
  - `web.web_engine()` and `mail.contacts_file()` are Track G's files, so they still read the environment and `red_home()`. The values are the same.
- **`last_details`** already went to the overlay and the log for any tool (Track D), so `find_file` needed no new code. A test checks that `find_file` and `check_repos` both have it.
- **Music pausing** uses `music.active_player()`. It's the same shared player as `default_player()`, but never creates one. The media-key tools are never called. One edge case is fixed: for "pause the music" by voice, Red resumes its own player just before the tool runs, so the tool really pauses it and says "Paused." instead of "The music is already paused."
- **Reminders:**
  - `attach_reminders(on_due)` sets `default_scheduler().on_due` and returns the scheduler. It returns `None` if `red.scheduler` can't be imported or raises.
  - In voice mode, `VoiceApp.announce()`:
    - waits for any command in progress (an `RLock` shared with `handle()`)
    - pauses Red's music
    - shows `speaking`, then `idle`
    - speaks inside `listener.paused_while()`, so the wake word doesn't hear Red
  - Typed mode prints `Red (reminder): …`.
  - `on_due` is cleared again when Red quits. `VoiceApp(attach=...)` is injectable, so the tests never touch the real scheduler.
- **Doctor:**
  - It lives in its own module, `red/doctor.py`, and runs before `load_settings()` and `connect()`. It never starts Ollama.
  - **Ollama check:** first `/api/tags` on 127.0.0.1:11434. If that doesn't answer, it looks for Red's Ollama `.installed` marker and the model's manifest under `models\ollama\manifests`.
  - **Microphone:** it queries the device and opens an `InputStream` without starting it, then closes it. **Speakers:** it only queries the device.
  - **Wake word:** the details of an unknown name go nowhere, because B's message lists the other openWakeWord names.
  - Missing config files are warnings, not failures.
  - It prints ✅/⚠️/❌, or `[ok]`/`[warn]`/`[FAIL]` when the console can't show emoji (the cp1252 pipes). The exit code is 1 only when there's a ❌.
- **Startup:**
  - `red/startup.py` writes `Red.lnk` in `shell:startup` (`FOLDERID_Startup`, with `%APPDATA%` as a fallback). It goes through a fixed `-EncodedCommand` PowerShell script with `WScript.Shell`, and the paths travel only in `RED_LNK_*` environment variables.
  - The target is the venv's `python.exe` (not `pythonw`, so typed confirmations still have a console). The arguments are `-m red --home <RED_HOME>`, in a minimized window, with the repo as the working folder.
  - The new global `--home` flag sets `RED_HOME` for that process only, because a shortcut can't set environment variables.
- **README:** a new "What you can say" table covers all 24 tools. It adds sections for `contacts.toml` and `RED_SEARCH_ENGINE`, safety notes (email is never sent, finding files only reads), and `doctor` and `startup on`. Troubleshooting starts with `doctor`.
- **CHANGELOG:** follows the Keep a Changelog style. v0.1.0 is marked "unreleased (draft)". There's no tag.

Integration notes:
- **Track G:**
  - **Reminders:** `__main__` only uses `default_scheduler()` and sets `.on_due`. If the scheduler needs an explicit `start()` or `stop()`, `default_scheduler()` should do it, or tell me and `attach_reminders()` can call it. `on_due(text)` is called from G's thread, and H speaks `text` exactly as given.
  - **README:** add G's new tools (timers and reminders, answers, online answers) to the "What you can say" table and to `CHANGELOG.md`. G doesn't own those files, so whoever merges G should do it.
  - **Settings:** `web.web_engine()` could use `load_settings().search_engine`, and `mail.contacts_file()` could use `load_settings().contacts_path`. That's optional, because the values match.
  - **Routing, for whoever owns `tools/system.py`:**
    - "open file explorer" and "launch file explorer" go to `open_folder` with `C:\`, which is refused. A line in `open_folder`'s description ("File Explorer itself is an app") or a `This PC` folder would fix it.
    - Allowlisted folder names aren't in the prompt, so "open projects" without "folder" can go to Documents.
- **Track E:** if "Hey Red" isn't merged by the final merge, change the CHANGELOG's first bullet under "Talking to Red" to say the wake word is coming, and that the shortcut works now.
- **Shared venv:** still waiting for the user's `pip install` (8.13). Until then, the voice tests can only run in Track B's venv.
- **New files:** `red/doctor.py`, `red/startup.py`, `contacts.example.toml`, `CHANGELOG.md`, `tests/test_doctor.py`, `tests/test_startup.py` and `tests/test_reminders_wiring.py`. Changed: `red/__main__.py`, `red/config.py`, `.env.example`, `README.md`, `AGENTS.md`, `tests/test_main.py`, `tests/test_voice_app.py` and `tests/test_settings_voice.py`.

Manual checks for the user (phases 1 to 3, one list). This list replaces the ones in 8.6, 8.7, 8.8, 8.13 and 8.15. Track E's "Hey Red" checks (8.14) and Track G's (8.18) are added when those tracks merge.

**0. Install and check the setup** (in PowerShell):

```powershell
cd D:\RED\red
$env:RED_HOME = "D:\RED"
$env:PIP_CACHE_DIR = "D:\RED\cache\pip"
D:\RED\.venv\Scripts\python.exe -m pip install --only-binary=:all: -r requirements-dev.txt
D:\RED\.venv\Scripts\Activate.ps1
python -m red setup
python -m red doctor
```

The doctor should show no ❌. Expect a ⚠️ for any of `allowlist.toml`, `repos.toml` or `contacts.toml` you haven't edited, and for "Hey Red" until Track E is merged. Also check that the doctor didn't make a sound or show a microphone-in-use icon for more than a moment.

**1. Voice loop**
1. Run `python -m red`. A dark card appears in the bottom-right corner, above the taskbar, and the console says `Ready.`
2. Press Ctrl+Alt+R. After the beep, say "open my downloads folder". The card goes through Listening, Thinking (with your words), and the reply. Explorer opens Downloads, and Red says "Opening Downloads."
3. Say "shut down in 60 minutes". Red asks aloud, with the time, and the card shows the question.
   - Say "no": "Cancelled.", and no Windows notice.
   - Ask again and say "yes": the Windows notice appears. Then "cancel the shutdown" cancels it.
4. Press Ctrl+Alt+R and stay silent: "I didn't hear anything." Press it twice quickly: only one recording starts.
5. Play music ("play some music"), then give any command. The music pauses while Red listens and talks, then resumes. Say "pause the music": Red says "Paused." and it stays paused. "resume" plays it again, and "stop the music" stops it.
6. "check my repos", after you set up `repos.toml`: the card shows one line per repo, and `D:\RED\logs\commands.jsonl` has a `details` field. Your repos look the same in `git status` afterwards. A repo with expired credentials says "couldn't fetch" within about 45 s, with no login prompt.
7. "find my resume": the card lists the matches. "open it" opens the best one. Programs are never opened; Red opens their folder instead.
8. Press Ctrl+C: Red prints "Bye.", and Task Manager shows no leftover `python.exe` or Red-started `ollama.exe`.

**2. Typed mode** (`python -m red --typed`)

9. "restart in 10 minutes" with no answer: after 30 s, "No answer, so I cancelled it.", and no Windows notice. With nothing scheduled, "cancel the shutdown" says "Nothing was scheduled".
10. `python -m red --dry-run` only shows the tool calls.

**3. Opening things**

11. "open Documents" and "open Pictures" open the OneDrive folders.
12. "open notepad", "open calculator", "open the file explorer app" and "open task manager" each start. Task Manager may show a UAC prompt.
13. "open PowerPoint", "open Word", "open Excel", "open Outlook" and "open paint" each start. Close them afterwards.
14. In `allowlist.toml`, set `projects` to a real folder. Check "open my projects folder" and "open vs code".
15. "open youtube" opens your browser. "search the web for weather in Pune" and "search YouTube for lofi music" show the right results. Set `RED_SEARCH_ENGINE=duckduckgo` in `.env` and check that the next search uses DuckDuckGo.
16. "open bluetooth settings" and "check for windows updates" open the right Settings pages.

**4. Mail**

17. Add yourself to `contacts.toml`, then say "compose a mail to <your name> about a test". A draft opens with the address, the subject and the body. Don't send it. A name that isn't in the file leaves the recipient empty, and Red says so. If nothing opens, choose a default email app in Windows Settings.

**5. PC controls**

18. Volume: "volume down 20 percent", "volume up", "mute", "unmute" and "set the volume to 30 percent". Watch the Windows volume flyout.
19. With Spotify or a YouTube tab playing (and no music from Red), "pause the music", "resume", "next song" and "previous track" control it.
20. "what time is it", "what's the date today" and "how much battery do I have" give the right answers.
21. "take a screenshot": a new file appears in Pictures\Screenshots.
22. "lock my PC" locks it. Sign back in.
23. "put the computer to sleep": it asks first. `n` cancels; then try `y`.
24. "empty the recycle bin", with only junk in it: the question gives the item count and size, and `n` cancels.

**6. Voice parts on their own**

25. Speakers: `python -m red.voice_demo --say "Hello, I am Red."` is spoken clearly, once.
26. Microphone: `python -m red.voice_demo --levels`. Speech should read above about 0.02 and silence below 0.008. If the wrong microphone is used, set `RED_MIC_DEVICE` to part of its name.
27. Spoken yes/no: "yes" confirms; "no" and 30 s of silence cancel.
28. Optional: `python -m red.voice_demo --device cuda --no-wakeword` falls back to the CPU with a warning, unless `nvidia-cublas-cu12` is installed.
29. No antivirus warning about the keyboard hook.

**7. Overlay on its own**

30. `python -m red.overlay`: the card goes through every state, never takes focus, lets clicks through, hides after about 3 s, and the program exits. Also try a high-DPI or second monitor.
31. `python -m red.overlay --fallback`: 4 Windows notifications appear.

**8. Start at sign-in**

32. Run `python -m red startup on`. `Red.lnk` appears in `shell:startup` (press Win+R and type it). Sign out and back in: Red starts in a minimized PowerShell window and says Ready. Then `python -m red startup off` removes the shortcut, and `python -m red startup` says it's off.

---

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

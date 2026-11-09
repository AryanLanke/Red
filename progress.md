# Red: progress and plan

This file is for developers and coding agents. [README.md](README.md) is for users. Read [AGENTS.md](AGENTS.md) for commands and how the code fits together.

Last updated: 2026-11-08.

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
| Music and repo sync tools | `red/tools/music.py`, `red/tools/git_sync.py` | ✅ Done (Track C) |
| Wiring it all together: settings, setup, voice loop, docs | `red/__main__.py`, `red/config.py`, `README.md`, `AGENTS.md` | ✅ Done (Track D, section 8.13). The shared venv install and the v0.1.0 tag are still to do |

**Day 1 result:** typed commands like "open Downloads" and "shut down in 2 hours" produce the right JSON in under a second once the model is loaded. 38 unit tests and 8 real-model tests pass. Commits: `a44da78` (project setup), `ebae152` (Day 1 code), `727ac5f` and `ffe2ff1` (README).

---

## 2. Goals and scope

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
| Intent routing | Qwen2.5 7B Instruct (Q4_K_M) via Ollama; Qwen2.5 3B for low-VRAM machines | Free, private, offline, good at JSON tool calls |
| Speech to text | Whisper small via faster-whisper (float16 on GPU, int8 on CPU) | Fast and accurate; works on any machine through the CPU fallback |
| Wake word | openWakeWord: a pre-trained phrase for v0.1, a custom "Hey Red" model later | Free, open source, low CPU |
| Text to speech | Piper | Free, local, fast |

**Developer machine:** Windows 11, AMD Ryzen 7 7735HS, RTX 4050 laptop GPU (6 GB VRAM), 16 GB RAM, Python 3.11.9. With 6 GB of VRAM, the 7B model and Whisper on the GPU at the same time is tight, so tests run Whisper on the CPU.

**Data folder on this machine:** `RED_HOME = D:\RED`. The repo is `D:\RED\red`, the venv is `D:\RED\.venv`, and Ollama v0.40.11 and the 7B model are already downloaded. The full `RED_HOME` layout is in the README.

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
- Only `y` or `yes` confirms (case-insensitive; surrounding spaces and trailing punctuation are ignored, so a spoken "Yes." works). Anything else, or no answer within 30 seconds, cancels.
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

### 7.2 Voice (Track B)

- Push-to-talk: a global hotkey (default `Ctrl+Alt+R`, set with `RED_HOTKEY`) starts recording. Recording stops after a short silence or a maximum length.
- Wake word: openWakeWord with a pre-trained phrase until a custom "Hey Red" model exists. Use the ONNX runtime, because tflite isn't available on Windows. The wake word pauses while Red is recording or speaking.
- Whisper small through faster-whisper. GPU float16 when CUDA works, otherwise CPU int8. The model loads on first use, falls back to the CPU on CUDA errors, and is stored under `RED_HOME\models\whisper`.
- Piper voice models live under `RED_HOME\models\piper`, pinned and checksum-verified with `red.downloads.download`.
- Spoken confirmation: Red speaks the question, records the answer, and passes the transcript to the same yes check as typed input.

### 7.3 Overlay (Track C)

- PySide6. Frameless, always on top, translucent, and doesn't take keyboard focus. Sits in the bottom-right corner of the primary screen.
- States: `idle`, `listening`, `thinking`, `confirm`, `speaking`, `error`, each with a short text. It hides itself a few seconds after returning to `idle`.
- Qt must own the main thread. Other threads update it through a thread-safe method (Qt signals).
- Fallback if PySide6 can't start: a Windows notification.

### 7.4 Music (Track C)

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

- [ ] **A "Hey Red" detector that works today, without training.** For example: voice-activity gating plus a small pinned Whisper model (such as `tiny.en` or `base.en`) on short clips, matching "hey red" and close variants ("hey, red", "hay red"). Use the existing `Listener` detector interface. Measure CPU use while idle and while people are talking, and keep it low
- [ ] `RED_WAKEWORD=hey_red` is the default. `RED_WAKEWORD_THRESHOLD` (or a sensible equivalent) tunes it. Remove `hey_jarvis` as a default and from docs. Other openWakeWord names and `.onnx` paths can stay as options
- [ ] `voice_demo.py`: use `"Hey Red"` everywhere, and replace `_is_yes` with `red.confirm.is_yes`, which now exists on `main`
- [ ] Real-model tests: Piper saying "Hey Red" (several voices and speeds) triggers it; a set of ordinary sentences, including ones with "red" in them ("I read the red book"), doesn't
- [ ] **A custom openWakeWord "hey_red" model,** if it's feasible on this machine before 13:15. Put the scripts in `scripts/train_hey_red/` and the training deps in `requirements-train.txt`. Generate synthetic speech with Piper voices, add noise, and train. Compare false accepts and misses against the detector above, and make whichever is better the default. If training isn't feasible (Windows-only tooling, time, or data size), write down exactly why and what it would take
- [ ] Manual checks for the user, with exact commands

Decisions:

Integration notes:

Manual checks for the user:

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

- [ ] **Track F's integration notes:**
  - `RED_SEARCH_ENGINE` and `contacts.toml` move into `Settings`, with a new `contacts.example.toml`
  - `FindFile.last_details` goes into the overlay and the log
  - music pausing keeps using `music.default_player()`, never the media-key tools
- [ ] **Reminders wiring** to `red.scheduler`, per the 8.17 contract, behind a try-import
- [ ] **`python -m red doctor`:** checks Python, the packages, `RED_HOME`, Ollama and the model, the microphone (opens it only, doesn't record), the speakers (lists the device, doesn't play), the GPU, the wake word model, and the allowlist, repos and contacts files. Each check gets a clear ✅/⚠️/❌ with a fix
- [ ] **Start at login (helper only):** `python -m red startup on|off` creates or removes a shortcut in the user's Startup folder. Test it with a fake folder; don't run it for real
- [ ] **README** for users: every tool, with an example sentence for each; the troubleshooting section points to `doctor`
- [ ] **`CHANGELOG.md`** with a v0.1.0 draft (don't tag)
- [ ] **Merged list of manual checks**, phases 1 to 3, for the user

Decisions:

Integration notes:

Manual checks for the user:

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
- **Ollama** uses an NVIDIA GPU automatically when drivers are current. Its logs are in `RED_HOME\logs\ollama.log`.
- **Smart App Control** blocks unsigned programs and DLLs. Exit code `0xC0E90002` means it blocked something.
- **faster-whisper on the GPU** needs cuBLAS and cuDNN through pip (`nvidia-cublas-cu12`, `nvidia-cudnn-cu12`).
- **Global shortcut:** `pynput` works on Windows. Some antivirus tools flag keyboard hooks.
- **openWakeWord:** use the ONNX inference framework, because tflite runtime has no Windows wheels.
- **Autostart:** a shortcut in `shell:startup`, or Task Scheduler at login.
- **Qt:** tests run with `QT_QPA_PLATFORM=offscreen`, and the GUI must run on the main thread.

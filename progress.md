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
| CLI: `setup`, `route`, typed loop (dry run only) | `red/__main__.py` | ✅ Done (Day 1) |
| Actions: folder, app, URL, shutdown, restart, cancel | `red/tools/system.py`, `red/tools/web.py` | ⏳ Schemas only; `run()` raises `NotImplementedError`. Track A |
| Confirmation, allowlist, command log | `red/confirm.py`, `red/allowlist.py`, ... | ⏳ Not started. Track A |
| Speech to text, text to speech, hotkey, wake word | `red/audio.py`, `red/stt.py`, `red/tts.py`, `red/listener.py` | ⏳ Not started. Track B |
| Floating overlay | `red/overlay.py` | ⏳ Not started. Track C |
| Music and repo sync tools | `red/tools/music.py`, `red/tools/git_sync.py` | ⏳ Not started. Track C |
| Wiring it all together, setup docs, v0.1.0 tag | `red/__main__.py`, `README.md` | ⏳ After the three tracks (section 8.9) |

**Day 1 result:** typed commands like "open Downloads" and "shut down in 2 hours" produce the right JSON in under a second once the model is loaded. 38 unit tests and 8 real-model tests pass. Commits: `a44da78` (project setup), `ebae152` (Day 1 code), `727ac5f` and `ffe2ff1` (README).

---

## 2. Goals and scope

**The aim:** a Jarvis for your own PC. You tell Red to do something and it does it, locally and safely.

| You say | What Red does | Where it is in the plan |
|---|---|---|
| "Shut down" | Shuts down, after a yes | v0.1, Track A (`shutdown`) |
| "Open YouTube" | Opens it in the browser | v0.1, Track A (`open_url`) |
| "Open PowerPoint" | Starts the app | v0.1, Track A (`open_app`). Add Word, Excel and PowerPoint to the built-in apps when they're installed |
| "Find my resume" / "where is file X" | Finds the file or folder and offers to open it | **New, v0.2:** `find_file`. Read-only search of known folders and allowlisted folders (or the Windows Search index), never the whole disk unasked |
| "Search the web for X" | Opens a web search in the browser | **New, v0.2:** `web_search`, building a search URL. Reading results aloud and summarising them comes later |
| "Compose a mail to X about Y" | Opens a new draft with the recipient, subject and body filled in | **New, v0.2:** `compose_mail` through a `mailto:` link (works with any mail app, no account access). Sending through Gmail stays with the Gmail work, and always asks first |
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

- [ ] `requirements-voice.txt`, pinned and verified on Windows with Python 3.11
- [ ] `audio.py`: recording that stops on silence
- [ ] `stt.py`: Whisper loaded on first use, GPU with CPU int8 fallback, models under `RED_HOME\models\whisper`
- [ ] `tts.py`: Piper with a pinned, checksum-verified voice under `RED_HOME\models\piper`
- [ ] `listener.py`: global hotkey and pre-trained wake word, with pause and resume
- [ ] `voice_confirm.py`: `spoken_ask`
- [ ] `voice_demo.py`
- [ ] Unit tests with fake audio, fake models and a fake keyboard
- [ ] Section updated, committed on `track-b-voice`

Decisions:

Integration notes:

Manual checks for the user:

### 8.8 Track C: overlay, music, repo sync

Specs: 7.3, 7.4 and 7.5. Done when `python -m red.overlay` shows every state, the music and repo-sync tools work from `Tool.run()` and route correctly with the real model, and all tests pass (overlay tests use `QT_QPA_PLATFORM=offscreen`).

- [ ] `requirements-ui.txt`, pinned and verified
- [ ] `overlay.py` with a demo under `__main__`, plus the notification fallback
- [ ] `tools/music.py`: library scan, name matching, play and stop, injectable player
- [ ] `tools/git_sync.py` and `repos.example.toml`: all statuses from 7.5, read-only, with timeouts, using an injectable git runner in tests
- [ ] Registered in `default_registry()`; real-model routing tests for the new tools in their own test file
- [ ] Check that the new tool descriptions don't break routing for the existing tools
- [ ] Section updated, committed on `track-c-ui-tools`

Decisions:

Integration notes:

Manual checks for the user:

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

---

## 10. Open questions, and the defaults used until you decide

| Question | Default for v0.1 |
|---|---|
| Music source: local folder or Spotify? | Local folder (`RED_MUSIC_DIR`, otherwise the Music folder) |
| Which repos should the sync check cover? | Whatever you list in `repos.toml`; with no list, Red says how to add one |
| Which folders and apps go on the allowlist? | Built-in known folders and the four default apps, plus whatever you add to `allowlist.toml` |
| Train a custom "Hey Red" wake word now, or use a pre-trained phrase? | Pre-trained openWakeWord phrase; the hotkey always works |
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

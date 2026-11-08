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

- [ ] `known_folders.py`: Known Folder API through ctypes
- [ ] `allowlist.py` and `allowlist.example.toml`: load with `tomllib`; a missing file means only the built-in defaults
- [ ] `open_folder`, `open_app`, `open_url` actions, with side effects passed in through the constructor
- [ ] `shutdown`, `restart`, `cancel_shutdown`, plus `describe()` with the exact time
- [ ] `confirm.py`: typed, 30-second timeout, `is_yes`
- [ ] `executor.py`: confirm, run, write to `commands.jsonl`; errors become a short reply and a log line, never a crash
- [ ] `__main__.py`: run actions by default; `--dry-run` keeps the Day 1 behaviour
- [ ] Unit tests with fakes; real-model tests still pass
- [ ] Section updated, committed on `track-a-actions`

Decisions:

Integration notes:

Manual checks for the user:
- Schedule a shutdown in 60 minutes, see the Windows notice, type "cancel the shutdown", and check that it's gone.

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
7. Ask the user before merging into `main`, removing the worktrees (`git worktree remove`), or tagging `v0.1.0`.

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

- **v0.2:** Gmail read and mark-as-read through the Gmail API, with confirmation for each batch.
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

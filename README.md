# Red

A local voice and action assistant for your laptop. Say "Hey Red" or press a shortcut, and Red listens, acts, and answers. Red runs on your machine, and its core features work without any cloud model.

Red is open source, so others can run it on their own machines. Users don't need to install a separate model server. Red downloads a pinned, code-signed Ollama build on first run, starts it only while Red is running, and stops it when Red exits.

---

## 1. Goals

**MVP (5 days):**
- Wake word "Hey Red" plus a global shortcut to activate
- Floating overlay window that shows Red's status and reply
- Spoken replies (TTS)
- Commands: open a folder or app, open a URL, shut down or restart after a delay, play music from a local folder
- Repo sync check: compare local Git repos with GitHub and report what's unpushed or behind
- Confirmation step for any destructive action

**Later (not in the MVP):**
- Gmail read and mark actions
- Automated multi-step tasks
- Plugin system for new capabilities
- Calendar, reminders, and smart home

**Out of scope:** trading or financial automation.

---

### Data folder (`RED_HOME`)

Everything Red downloads or writes lives under one folder, `RED_HOME`. The default is `%LOCALAPPDATA%\Red`. Set `RED_HOME` to put it somewhere else, for example `D:\Red`.

```
RED_HOME\
├── red\                  # the git repo (developers only)
├── .venv\                # Python virtual environment (developers only)
├── bin\
│   ├── ollama\           # Ollama build, downloaded on first run
│   └── llama.cpp\        # optional fallback backend
├── models\
│   ├── ollama\           # Ollama's model store
│   ├── llm\              # GGUF files for the llama.cpp fallback
│   ├── whisper\          # speech-to-text models
│   ├── piper\            # voice models
│   └── wakeword\         # openWakeWord models
├── cache\
│   ├── pip\              # PIP_CACHE_DIR
│   ├── huggingface\      # HF_HOME
│   └── ollama-home\      # Ollama's settings and key, kept off C:
├── logs\                 # logs and command history
└── config\
    ├── .env              # your settings and secrets (never in the repo)
    └── allowlist.toml    # folders and apps Red may open
```

Pip and Hugging Face cache files on C: by default. Set `PIP_CACHE_DIR=%RED_HOME%\cache\pip` and `HF_HOME=%RED_HOME%\cache\huggingface` to keep them under `RED_HOME`.

### Storage needed

Plan for about **15 GB free**. Rough sizes:

| Item | Approx. size |
|---|---|
| Python packages (faster-whisper with CUDA libraries, PySide6, etc.) | 2 to 3 GB |
| Ollama build (includes CUDA libraries) | about 2.1 GB unpacked |
| Qwen2.5 7B Instruct, Q4_K_M | about 4.7 GB |
| Whisper small model | about 0.5 GB |
| Piper voice model | 0.1 GB |
| openWakeWord models | under 0.1 GB |
| Logs and room to grow | 2 GB or more |

### Hardware

**Developer machine (reference):** Windows 11, AMD Ryzen 7 7735HS, NVIDIA RTX 4050 laptop GPU (6 GB VRAM), 16 GB RAM.

**For users:**
- **NVIDIA GPU with 6 GB or more:** 7B model on the GPU. Ollama picks the GPU automatically.
- **No GPU, or low VRAM:** smaller 3B model, with Whisper on the CPU (int8).

Red loads the model only while it's in use. After `RED_LLM_KEEP_ALIVE` (default 5 minutes) without a command, the model is unloaded and its GPU memory is freed. When Red exits, its Ollama process exits too, even if Red crashes.

6 GB of VRAM is tight for a 7B model plus Whisper. If the GPU runs out of memory, run Whisper on the CPU or switch to the 3B model. Keep other heavy apps closed while Red's models are loaded.

---

## 2. Architecture

```
          +-------------------+
 "Hey Red"|  Wake word        |  openWakeWord (always on, local)
 shortcut ->  + hotkey        |  pynput / keyboard
          +--------+----------+
                   |
                   v
          +-------------------+
          |  Speech to text   |  faster-whisper (local)
          +--------+----------+
                   |
                   v
          +-------------------+
          |  Intent router    |  Local LLM via Red-managed Ollama
          |  (picks a tool)   |  JSON-schema constrained: {tool, args}
          +--------+----------+
                   |
                   v
          +-------------------+
          |  Tool registry    |  each capability is a plugin module
          |  files, system,   |
          |  music, git, ...  |
          +--------+----------+
                   |
                   v
          +-------------------+
          |  Reply            |  overlay text + TTS (Piper)
          +-------------------+
```

### Folder layout

```
red/
├── README.md
├── LICENSE
├── .gitignore
├── .env.example          # placeholder keys only, never real secrets
├── allowlist.example.toml # folders and apps Red may open (Day 2)
├── requirements.txt
├── red/
│   ├── __main__.py       # entry point
│   ├── config.py         # resolves RED_HOME and loads config\.env
│   ├── downloads.py      # checksum-verified downloads
│   ├── llm.py            # LLM backends (Ollama, llama.cpp) and clients
│   ├── process.py        # child servers that stop when Red stops
│   ├── listener.py       # wake word + hotkey
│   ├── stt.py            # Whisper wrapper
│   ├── router.py         # LLM intent to tool call
│   ├── tts.py            # Piper wrapper
│   ├── overlay.py        # floating status window
│   ├── confirm.py        # yes/no confirmation for risky actions
│   └── tools/
│       ├── base.py       # Tool interface
│       ├── system.py     # open app, open folder, shutdown, restart
│       ├── web.py        # open URL
│       ├── music.py      # play local songs
│       └── git_sync.py   # check repos against GitHub
└── tests/
```

Each tool follows one interface, so adding a feature means adding one file.

---

## 3. Tool interface

```python
class Tool:
    name: str            # "shutdown"
    description: str     # shown to the LLM so it knows when to use it
    args_schema: dict    # JSON schema for arguments
    destructive: bool    # if True, Red asks for confirmation first

    def run(self, **kwargs) -> str:
        """Do the action and return a short reply for the user."""
```

The router sees the list of tool names, descriptions, and schemas. It replies with JSON only, for example `{"tool": "shutdown", "args": {"minutes": 180}}`. The LLM's output is constrained to that JSON schema at generation time, and Red still validates the JSON and the argument ranges before running anything.

---

## 4. Models

| Job | Model | Why |
|---|---|---|
| Intent routing at runtime | Qwen2.5 7B Instruct (Q4_K_M) via Ollama; Qwen2.5 3B for low-VRAM machines | Free, private, works offline, good at JSON tool calls |
| Speech to text | Whisper small via faster-whisper (float16 on GPU, int8 on CPU) | Fast and accurate; CPU fallback for any machine |
| Wake word | openWakeWord with a custom "Hey Red" model | Free, open source, low CPU |
| Text to speech | Piper | Free, local, fast |

Every model runs locally, so Red keeps working without a subscription or internet.

---

## 5. Five-day plan

**Day 1: Foundation. ✅ Done.** Set up the repo, `.gitignore`, and README. Got the local model running through a Red-managed Ollama. Wrote `config.py`, the `Tool` interface, and the router. Result: typed commands like "open Downloads" and "shut down in 2 hours" produce the right JSON in under a second once the model is loaded. 38 unit tests and 8 real-model tests pass.

**Day 2: Actions.** Build `system.py` (open folder, open app, shutdown and restart with a delay) and `web.py`. Add the confirmation step for destructive actions. Test: each action works from typed input. Details below.

**Day 3: Voice.** Add Whisper for speech input, Piper for speech output, and the shortcut trigger. Test: press the shortcut, say a command, hear a reply.

**Day 4: Wake word and overlay.** Add openWakeWord and the PySide6 floating window. Test: say the wake word from across the room, and the overlay appears on screen. Training a custom "Hey Red" model takes extra time, so use a pre-trained phrase until it's ready.

**Day 5: Music, repo sync, and polish.** Build `music.py` and `git_sync.py`. Write setup instructions. Test the full flow end to end, then tag a first release.

**If time runs short:** cut the wake word and keep the shortcut. Cut the overlay and use a simple notification. Keep the shutdown, folder, and repo sync features, since they're the most useful.

### Day 2 in detail: actions and confirmation

**Goal:** every tool from Day 1 really runs from typed input, and nothing destructive runs without a clear yes.

| Tool | How it works | Safety |
|---|---|---|
| `open_folder` | Downloads, Documents, Desktop, Pictures, Music, and Videos are found through Windows' Known Folder API, so folders moved to OneDrive still work. Other folders come from the allowlist. Opens with `os.startfile`. | Only known folders or allowlisted ones. If Red can't match the name, it says so instead of guessing. |
| `open_app` | App names map to commands in the allowlist. Built-in defaults: Notepad, Calculator, File Explorer, and Task Manager. | Only allowlisted apps. The model's text is only used as a lookup key, never as a command line. |
| `open_url` | Opens in the default browser. | `http` and `https` only, already enforced by the schema. |
| `shutdown`, `restart` | `shutdown /s` or `/r` with `/t <seconds>`. Red says the exact time it will happen. | Destructive, so it asks first. The delay is capped at 24 hours. A new schedule replaces the old one. |
| `cancel_shutdown` | `shutdown /a`. | Runs at once, with no confirmation. Says so if nothing was scheduled. |

**Confirmation (`confirm.py`):**
- Red repeats the action in plain words: `Shut down in 2 hours (at 11:40 PM)? [y/N]`
- Only `y` or `yes` confirms. Anything else, or no answer within 30 seconds, cancels.
- Day 2 confirms by typing. Day 3 adds a spoken yes or no with the same rules.

**Allowlist:** `RED_HOME\config\allowlist.toml`, copied from `allowlist.example.toml` in the repo:

```toml
[folders]
projects = 'D:\Projects'

[apps]
"vs code" = "code"
```

**Command log:** each action Red runs or cancels is written as one JSON line to `RED_HOME\logs\commands.jsonl`, with the time, the command text, the tool, its arguments, whether you confirmed, and the result.

**Testing:**
- Unit tests use a fake runner, so they never open windows or schedule a real shutdown.
- `python -m red --dry-run` keeps the Day 1 behavior: it shows tool calls without running them.
- Manual check: schedule a shutdown in 60 minutes, see the Windows notice, then type "cancel the shutdown" and check that it's gone.

**Done when:** each tool works from typed input, every destructive action asks first, cancel always works, and all tests pass.

---

## 6. Repo sync check

For each folder in a list you configure:

1. `git fetch` to update remote information
2. `git status` to find uncommitted changes
3. `git log @{u}..HEAD` to find local commits not pushed yet
4. `git log HEAD..@{u}` to find remote commits you don't have locally

Red reports each repo as clean, ahead, behind, or dirty. It also reports a repo with no upstream branch, a detached HEAD, or a failed fetch (for example, missing credentials) instead of skipping it. Use the GitHub CLI (`gh`) or the GitHub API if you also want to see open issues or pull requests.

---

## 7. Setup and safety

- **Secrets:** Store API tokens and credentials in `RED_HOME\config\.env`, and never commit them. The repo only contains `.env.example` with placeholder values.
- **Permissions:** Red can only open known Windows folders and the folders and apps listed in `RED_HOME\config\allowlist.toml`. It never runs an arbitrary path the LLM suggests.
- **Confirmations:** Shutdown, restart, and anything that changes files ask "Are you sure?" first. Red repeats the action back ("Shutting down in 3 hours. Confirm?") so a misheard number is caught.
- **Shutdown limits:** Delays are bounded, Red always announces a scheduled shutdown, and "cancel shutdown" works at any time.
- **Logs:** Red keeps a local log of the commands it ran under `RED_HOME\logs`. Logs contain your transcribed speech, stay on your machine, and are never committed.
- **Microphone:** Windows must allow microphone access for desktop apps (Settings > Privacy & security > Microphone).

---

## 8. Open source checklist

- [x] MIT license
- [ ] README with install steps under 30 minutes
- [x] `.env.example` with placeholder values
- [x] `.gitignore` covering `.env`, models, and audio files
- [ ] Safety section explaining what Red can access
- [x] Tests for the router's JSON validation

---

## 9. Setup steps (Windows, PowerShell)

Requires Python 3.11 and Git.

```powershell
# Optional: choose where Red keeps its data (default is %LOCALAPPDATA%\Red)
$env:RED_HOME = "D:\Red"

git clone https://github.com/<you>/red.git "$env:RED_HOME\red"
cd "$env:RED_HOME\red"
python -m venv "$env:RED_HOME\.venv"
& "$env:RED_HOME\.venv\Scripts\Activate.ps1"

$env:PIP_CACHE_DIR = "$env:RED_HOME\cache\pip"
$env:HF_HOME = "$env:RED_HOME\cache\huggingface"
pip install -r requirements.txt

New-Item -ItemType Directory -Force "$env:RED_HOME\config"
Copy-Item .env.example "$env:RED_HOME\config\.env"

python -m red setup                  # downloads Ollama and the model (about 6.3 GB)
python -m red route "open Downloads" # shows the tool call for one command
python -m red                        # type commands interactively
```

If Ollama is already running on your PC, Red uses it instead of downloading its own. Set `RED_LLM_MODEL=qwen2.5-3b-instruct-q4_k_m` in `config\.env` for a smaller model. The Ollama and llama.cpp downloads are pinned to exact versions and checked against SHA-256 hashes. Ollama checks the model files itself.

### Running tests

```powershell
pip install -r requirements-dev.txt
python -m pytest --basetemp="$env:RED_HOME\cache\pytest-tmp"
$env:RED_INTEGRATION = "1"; python -m pytest tests\test_integration_llm.py   # uses the real model
```

---

## 10. Decisions

- **Local model runtime: Red-managed Ollama (for v0.1).** Red downloads Ollama's standalone zip (no installer, no tray app, no autostart), runs `ollama serve` only while Red runs, and passes the JSON schema as Ollama's `format` so tool calls are constrained.
- **Why not bundle llama.cpp's llama-server?** It was the first choice, but its Windows builds aren't code-signed. Windows 11 Smart App Control, which is on by default on many new PCs, refuses to load them. Ollama's binaries are signed by Ollama Inc. llama-server stays as a fallback (`RED_LLM_BACKEND=llama.cpp`) for PCs that allow it.
- **Bring your own server.** Set `RED_LLM_URL` to use LM Studio or any OpenAI-compatible server instead.
- **Skipped: llama-cpp-python.** Installing its CUDA build on Windows often means compiling with Visual Studio and the CUDA toolkit, which is too much to ask of users.
- **Skipped: Hugging Face Transformers.** Too much setup on Windows for short command routing.
- **One data folder (`RED_HOME`).** No hard-coded paths, so Red works on any machine.
- **No cloud models.** Red never calls a cloud model, so it works offline and needs no subscription.
- **Scope discipline.** Trading and financial automation are out of scope.

---

## 11. Future plans

**v0.2:** Gmail read and mark-as-read through the Gmail API. Confirmation for each batch.

**v0.3:** Multi-step automations, such as "open my project, check the repo sync, and tell me what's unpushed," with a short plan shown before running.

**v0.4:** A plugin system so others can add tools without editing core code. Tool discovery from a `tools/` folder.

**v0.5:** Calendar, reminders, and timers.

**Packaging:** A Windows installer (PyInstaller or Nuitka) so users don't need Python.

**Later:** Smart home control, a web dashboard for the command log, and per-tool permission settings.

Each version should ship with tests for the new tools and an updated safety section.

---

## 12. Windows notes

- **Shutdown:** `shutdown /s /t <seconds>` for shutdown, `/r` for restart, and `shutdown /a` to cancel a pending shutdown. Red should always tell you a shutdown is scheduled and offer to cancel it.
- **Opening apps and folders:** `os.startfile(path)` opens folders, files, and apps registered with Windows.
- **Ollama:** uses an NVIDIA GPU automatically when drivers are current. Check GPU use in Task Manager while a prompt runs. Red's Ollama logs go to `RED_HOME\logs\ollama.log`.
- **Smart App Control:** blocks unsigned programs and DLLs. If a backend exits with code `0xC0E90002`, that's the cause. Use the Ollama backend.
- **faster-whisper on GPU:** needs the cuBLAS and cuDNN libraries, installed through pip (`nvidia-cublas-cu12`, `nvidia-cudnn-cu12`).
- **Global shortcut:** `pynput` works on Windows. Some antivirus tools flag keyboard hooks, so you may need to allow the app.
- **Autostart:** Put a shortcut to Red in the Startup folder (`shell:startup`) or use Task Scheduler to launch it at login.
- **Music:** Use `python-vlc` (needs VLC installed) or `pygame`, which both work well on Windows.

---

## 13. Open questions

- Which music source first: a local folder, or Spotify?
- Which repos should the sync check cover?
- Which folders and apps should be on the allowlist?
- Train a custom "Hey Red" wake word now, or ship v0.1 with a pre-trained phrase?

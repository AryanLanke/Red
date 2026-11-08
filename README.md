# Red

A local voice and action assistant for your Windows laptop. Say "Hey Red" or press a shortcut, and Red listens, acts, and answers. Red runs entirely on your machine: no cloud model, no subscription, and its core features work offline.

> **Status: v0.1 in progress.** Red takes spoken and typed commands, runs them, asks before anything risky, answers out loud, and shows a small status window. Developers can follow along in [progress.md](progress.md).

---

## What Red does

- **Wakes up** when you press **Ctrl+Alt+R** or say **"Hey Red"**
- **Opens things:** folders like Downloads or Documents, apps like Notepad or VS Code, and websites
- **Shuts down or restarts** your PC after a delay ("shut down in 2 hours"), and cancels it again
- **Plays music** from a folder on your PC: play, pause, resume, next song, stop
- **Checks your Git repos** against GitHub and tells you what's unpushed or behind
- **Answers out loud** and shows its status in a small floating window
- **Asks before anything risky:** shutdown and restart always need a clear "yes"

---

## Requirements

- Windows 11
- Python 3.11 and Git
- About **15 GB** of free disk space
- A microphone, for voice commands

| Your PC | What Red uses |
|---|---|
| NVIDIA GPU with 6 GB or more | The 7B model on the GPU (picked automatically) |
| No GPU, or less video memory | The smaller 3B model, with speech recognition on the CPU |

Red loads the model only while you're using it. After 5 minutes without a command (you can change this), the model is unloaded and its memory is freed. When Red exits, everything it started exits too, even if Red crashes.

---

## Install

Open PowerShell and run:

```powershell
# Optional: choose where Red keeps its data (default is %LOCALAPPDATA%\Red)
$env:RED_HOME = "D:\Red"

git clone https://github.com/AryanLanke/Red.git "$env:RED_HOME\red"
cd "$env:RED_HOME\red"
python -m venv "$env:RED_HOME\.venv"
& "$env:RED_HOME\.venv\Scripts\Activate.ps1"

$env:PIP_CACHE_DIR = "$env:RED_HOME\cache\pip"
$env:HF_HOME = "$env:RED_HOME\cache\huggingface"
pip install -r requirements.txt

New-Item -ItemType Directory -Force "$env:RED_HOME\config"
Copy-Item .env.example "$env:RED_HOME\config\.env"

python -m red setup    # downloads the model runtime, the language model and the voice models (about 7 GB)
```

If you set `RED_HOME`, set it again in every new PowerShell window, or set it once as a user environment variable.

You don't need to install a separate model server. Red downloads a pinned, code-signed build of Ollama on first run, starts it only while Red is running, and stops it when Red exits. If Ollama is already running on your PC, Red uses that instead.

---

## Using Red

```powershell
python -m red             # voice: press Ctrl+Alt+R or say "Hey Red", then speak
python -m red --typed     # type commands instead; type 'quit' to stop
python -m red --dry-run   # type commands and only see what Red would do
python -m red run "open Downloads"     # run one command
python -m red route "open Downloads"   # only show what Red would do for one command
```

**Talking to Red:** press **Ctrl+Alt+R** (or say "Hey Red"), wait for the short beep, then say your command. Red stops listening about a second after you finish, then answers out loud. The small window in the bottom-right corner shows what Red is doing: listening, thinking, asking, or speaking. It never takes the keyboard focus, and it hides itself when Red is idle. Press Ctrl+C in the PowerShell window to quit Red.

**"Hey Red":** if the wake word can't start on your PC, Red says so once when it starts and keeps working with the shortcut.

**Confirming:** for a shutdown or restart, Red repeats the action with the exact time, for example "Shut down in 2 hours (at 11:40 PM)? Say yes to confirm." Only "yes" goes ahead. Anything else, or silence for 30 seconds, cancels. If your microphone fails at that moment, Red asks in the PowerShell window instead. In typed mode, you type `y` or `yes`.

**Music:** Red pauses the music while it listens and talks, then resumes it.

Examples:
- "open my Downloads folder", "open Documents"
- "open notepad", "open calculator", "open task manager"
- "open YouTube"
- "shut down the computer in 3 hours", "restart in 10 minutes", "cancel the shutdown"
- "play some music", "play Daft Punk", "pause the music", "next song", "stop the music"
- "check my repos", "is red pushed?"

---

## Settings

Your settings are in `RED_HOME\config\.env` (copied from `.env.example`). Settings already in your environment take priority over that file.

| Setting | What it does | Default |
|---|---|---|
| `RED_HOTKEY` | The shortcut that makes Red listen, for example `Ctrl+Alt+R`. `off` turns it off | `Ctrl+Alt+R` |
| `RED_WAKEWORD` | `hey_red`, a path to a custom `.onnx` wake word model, or `off` for the shortcut only | `hey_red` |
| `RED_WAKEWORD_THRESHOLD` | How sure the wake word detector must be, from 0 to 1. Lower is more sensitive | `0.5` |
| `RED_MIC_DEVICE` | Which microphone: a device number or part of its name | Windows default |
| `RED_WHISPER_DEVICE` | Speech recognition on `cpu`, `cuda` (NVIDIA GPU) or `auto` | `cpu` |
| `RED_WHISPER_MODEL` | Speech recognition model | `small` |
| `RED_PIPER_VOICE` | The voice Red speaks with | `en_US-lessac-medium` |
| `RED_MUSIC_DIR` | The folder Red plays music from | your Music folder |
| `RED_LLM_MODEL` | `qwen2.5-7b-instruct-q4_k_m`, or `qwen2.5-3b-instruct-q4_k_m` for PCs with less video memory | 7B |
| `RED_LLM_KEEP_ALIVE` | How long the model stays loaded after your last command (`5m`, `30m`, `0`) | `5m` |
| `RED_LLM_BACKEND` | `auto`, `ollama`, or `llama.cpp` | `auto` |
| `RED_LLM_URL` | Use your own OpenAI-compatible server (LM Studio, etc.) instead | not set |
| `RED_LLM_GPU` | For the `llama.cpp` backend only: `auto`, `cuda`, `vulkan`, or `cpu` | `auto` |
| `GITHUB_TOKEN` | Optional, for the repo check. Read-only access is enough | not set |

Speech recognition runs on the CPU by default, because on a 6 GB GPU the language model and Whisper don't fit together.

### Folders and apps: `allowlist.toml`

Red opens Windows' standard folders (Downloads, Documents, Desktop, Pictures, Music and Videos, even if they were moved to OneDrive) and four apps (Notepad, Calculator, File Explorer and Task Manager). To add more, edit `RED_HOME\config\allowlist.toml`. `python -m red setup` creates it from `allowlist.example.toml`. Changes apply to the next command; you don't need to restart Red.

```toml
[folders]
projects = 'D:\Projects'

[apps]
"vs code" = '%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe'
notes = ['notepad.exe', 'D:\notes.txt']     # a program with arguments
```

Use single quotes around Windows paths. The name is what you say ("open projects").

### Repos: `repos.toml`

List the repos for "check my repos" in `RED_HOME\config\repos.toml`. `python -m red setup` creates it from `repos.example.toml`.

```toml
[repos]
red = 'D:\RED\red'
website = 'D:\Projects\website'
```

Red reports each repo as clean, ahead (unpushed commits), behind, diverged, or with uncommitted changes. It says the short version out loud and shows each repo in the status window. It only reads your repos.

### Music

Red plays `mp3`, `ogg`, `opus`, `flac` and `wav` files from your Music folder, or from `RED_MUSIC_DIR`. It doesn't play `m4a`, `aac` or `wma`. Songs are matched by file and folder names, so "play Daft Punk" works if there's a folder or file with that name.

---

## Where Red keeps its files

Everything Red downloads or writes lives in one folder, `RED_HOME` (default `%LOCALAPPDATA%\Red`). To remove Red completely, delete that folder.

```
RED_HOME\
├── red\          # the app (the git repo)
├── .venv\        # Python environment
├── bin\          # Ollama, downloaded on first run
├── models\       # the language, speech and voice models
├── cache\        # downloads and caches
├── logs\         # logs and command history
└── config\
    ├── .env           # your settings and secrets
    ├── allowlist.toml # folders and apps Red may open
    └── repos.toml     # repos for the repo check
```

Disk space, roughly: Python packages 2 to 3 GB, Ollama 2.1 GB, the 7B model 4.7 GB, speech and voice models under 1 GB, and room for logs.

---

## Privacy and safety

- **Everything stays on your PC.** Red never sends your voice or commands to a cloud service. Your commands and transcribed speech are logged only under `RED_HOME\logs`.
- **Red only opens what you allow:** Windows' standard folders, plus the folders and apps in `allowlist.toml`. It never runs a command or path the model makes up.
- **Risky actions ask first.** Shutdown and restart repeat the action back to you ("Shut down in 2 hours, at 11:40 PM?") and only go ahead on "yes". No answer within 30 seconds cancels.
- **Shutdowns are limited and cancellable.** Delays are capped at 24 hours, Red always says when a shutdown is scheduled, and "cancel the shutdown" works at any time. When the time comes, Windows closes open apps without asking, so save your work first.
- **The repo check only reads.** It never pulls, pushes, or changes your repos.
- **Secrets** such as `GITHUB_TOKEN` stay in `RED_HOME\config\.env`, which is never part of the repo.
- **Downloads are verified.** Ollama, the llama.cpp fallback, and the speech, voice and wake word models are pinned to exact versions and checked against SHA-256 hashes, and Ollama checks the model files itself.

---

## Troubleshooting

- **"Smart App Control blocked llama-server" or exit code `0xC0E90002`:** Windows blocks unsigned programs. Use the default Ollama backend (`RED_LLM_BACKEND=ollama`).
- **The GPU runs out of memory:** switch to the 3B model with `RED_LLM_MODEL=qwen2.5-3b-instruct-q4_k_m`, and close other heavy apps while Red is loaded.
- **Red can't hear you:** allow microphone access for desktop apps in Settings > Privacy & security > Microphone. To use a different microphone, set `RED_MIC_DEVICE` to part of its name.
- **No status window, only Windows notifications:** the window needs PySide6, which is in `requirements.txt`. Without it, Red shows notifications for questions, answers and errors.
- **"Voice needs the voice packages":** run `pip install -r requirements.txt` again, or use `python -m red --typed`.
- **The shortcut doesn't work:** some antivirus tools block keyboard hooks, so you may need to allow Red.
- **Something else went wrong:** check `RED_HOME\logs\red.log` and `RED_HOME\logs\ollama.log`.

**Start Red at login:** put a shortcut to Red in your Startup folder (press Win+R, type `shell:startup`), or use Task Scheduler.

---

## Contributing

- [progress.md](progress.md) has the plan, the architecture, the decisions, and what's being built now.
- [AGENTS.md](AGENTS.md) has developer commands and how the code fits together.

Run the tests:

```powershell
pip install -r requirements-dev.txt
python -m pytest --basetemp="$env:RED_HOME\cache\pytest-tmp"
$env:RED_INTEGRATION = "1"; python -m pytest tests\test_integration_llm.py tests\test_voice_models.py   # real models
```

## License

MIT. See [LICENSE](LICENSE).

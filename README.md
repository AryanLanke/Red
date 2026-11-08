# Red

A local voice and action assistant for your Windows laptop. Say "Hey Red" or press a shortcut, and Red listens, acts, and answers. Red runs entirely on your machine: no cloud model, no subscription, and its core features work offline.

> **Status: early development (v0.1 in progress).** Today Red understands typed commands and shows which action it would take. Running the actions, voice, the floating window, music and the repo check are being built. Developers can follow along in [progress.md](progress.md).

---

## What Red will do in v0.1

- **Wake up** when you say "Hey Red" or press a keyboard shortcut
- **Open things:** folders like Downloads or Documents, apps like Notepad or VS Code, and websites
- **Shut down or restart** your PC after a delay ("shut down in 2 hours"), and cancel it again
- **Play music** from a folder on your PC
- **Check your Git repos** against GitHub and tell you what's unpushed or behind
- **Answer out loud** and show its status in a small floating window
- **Ask before anything risky:** shutdown and restart always need a clear "yes"

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

python -m red setup    # downloads the local model runtime and the model (about 6.3 GB)
```

If you set `RED_HOME`, set it again in every new PowerShell window, or set it once as a user environment variable.

You don't need to install a separate model server. Red downloads a pinned, code-signed build of Ollama on first run, starts it only while Red is running, and stops it when Red exits. If Ollama is already running on your PC, Red uses that instead.

---

## Using Red

```powershell
python -m red route "open Downloads"   # show what Red would do for one command
python -m red                          # type commands one after another; type 'quit' to stop
```

Examples:
- "open my Downloads folder"
- "open notepad"
- "open YouTube"
- "shut down the computer in 3 hours"
- "restart in 10 minutes"
- "cancel the shutdown"

---

## Settings

Your settings are in `RED_HOME\config\.env`. Settings already in your environment take priority over that file.

| Setting | What it does | Default |
|---|---|---|
| `RED_LLM_MODEL` | `qwen2.5-7b-instruct-q4_k_m`, or `qwen2.5-3b-instruct-q4_k_m` for PCs with less video memory | 7B |
| `RED_LLM_KEEP_ALIVE` | How long the model stays loaded after your last command (`5m`, `30m`, `0`) | `5m` |
| `RED_LLM_BACKEND` | `auto`, `ollama`, or `llama.cpp` | `auto` |
| `RED_LLM_URL` | Use your own OpenAI-compatible server (LM Studio, etc.) instead | not set |
| `RED_LLM_GPU` | For the `llama.cpp` backend only: `auto`, `cuda`, `vulkan`, or `cpu` | `auto` |
| `GITHUB_TOKEN` | Optional, for the repo check. Read-only access is enough | not set |

**Allowed folders and apps** will go in `RED_HOME\config\allowlist.toml` (coming in v0.1):

```toml
[folders]
projects = 'D:\Projects'

[apps]
"vs code" = "code"
```

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
    └── allowlist.toml # folders and apps Red may open
```

Disk space, roughly: Python packages 2 to 3 GB, Ollama 2.1 GB, the 7B model 4.7 GB, speech and voice models under 1 GB, and room for logs.

---

## Privacy and safety

- **Everything stays on your PC.** Red never sends your voice or commands to a cloud service. Your commands and transcribed speech are logged only under `RED_HOME\logs`.
- **Red only opens what you allow:** Windows' standard folders, plus the folders and apps in `allowlist.toml`. It never runs a command or path the model makes up.
- **Risky actions ask first.** Shutdown and restart repeat the action back to you ("Shut down in 2 hours, at 11:40 PM?") and only go ahead on "yes". No answer within 30 seconds cancels.
- **Shutdowns are limited and cancellable.** Delays are capped at 24 hours, Red always says when a shutdown is scheduled, and "cancel the shutdown" works at any time.
- **The repo check only reads.** It never pulls, pushes, or changes your repos.
- **Secrets** such as `GITHUB_TOKEN` stay in `RED_HOME\config\.env`, which is never part of the repo.
- **Downloads are verified.** Ollama and the llama.cpp fallback are pinned to exact versions and checked against SHA-256 hashes, and Ollama checks the model files itself.

---

## Troubleshooting

- **"Smart App Control blocked llama-server" or exit code `0xC0E90002`:** Windows blocks unsigned programs. Use the default Ollama backend (`RED_LLM_BACKEND=ollama`).
- **The GPU runs out of memory:** switch to the 3B model with `RED_LLM_MODEL=qwen2.5-3b-instruct-q4_k_m`, and close other heavy apps while Red is loaded.
- **Red can't hear you:** allow microphone access for desktop apps in Settings > Privacy & security > Microphone.
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
$env:RED_INTEGRATION = "1"; python -m pytest tests\test_integration_llm.py   # uses the real model
```

## License

MIT. See [LICENSE](LICENSE).

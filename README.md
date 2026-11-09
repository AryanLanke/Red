# Red

A local voice and action assistant for your Windows laptop. Say "Hey Red" or press a shortcut, and Red listens, acts, and answers. Red runs entirely on your machine: no cloud model, no subscription, and its core features work offline.

> **Status: v0.1 in progress.** Red takes spoken and typed commands, runs them, asks before anything risky, answers out loud, and shows a small status window. Developers can follow along in [progress.md](progress.md).

---

## What Red does

- **Wakes up** when you press **Ctrl+Alt+R** or say **"Hey Red"**
- **Opens things:** folders, apps (including Word, Excel, PowerPoint and Outlook), websites and Windows Settings pages
- **Finds files** by name and opens the one you pick
- **Searches the web** in your browser: the web, YouTube, images, maps, news or Wikipedia
- **Writes email drafts** in your mail app, ready for you to check and send
- **Controls your PC:** volume, media keys, screenshots, lock, sleep, shutdown and restart (with a delay), and emptying the Recycle Bin
- **Plays music** from a folder on your PC
- **Checks your Git repos** against GitHub and tells you what's unpushed or behind
- **Tells you** the time, the date and the battery level
- **Answers out loud** and shows its status in a small floating window
- **Asks before anything risky:** shutdown, restart, sleep and emptying the Recycle Bin always need a clear "yes"

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
python -m red doctor   # checks that everything is in place, and says how to fix what isn't
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
python -m red doctor                   # check the setup
python -m red startup on               # start Red when you sign in (off to undo)
```

**Talking to Red:** press **Ctrl+Alt+R** (or say "Hey Red"), wait for the short beep, then say your command. Red stops listening about a second after you finish, then answers out loud. The small window in the bottom-right corner shows what Red is doing: listening, thinking, asking, or speaking. It never takes the keyboard focus, and it hides itself when Red is idle. Press Ctrl+C in the PowerShell window to quit Red.

**"Hey Red":** if the wake word can't start on your PC, Red says so once when it starts and keeps working with the shortcut.

**Confirming:** for a shutdown, restart, sleep or emptying the Recycle Bin, Red repeats the action with the exact time, for example "Shut down in 2 hours (at 11:40 PM)? Say yes to confirm." A clear yes goes ahead ("yes", "yeah, go ahead", "sure, do it"). "No", "don't" or "stop" anywhere in your answer cancels, and so does a vague "okay" or 30 seconds of silence. Everything else, like opening an app, just happens: "can you open YouTube?" opens YouTube. If your microphone fails at that moment, Red asks in the PowerShell window instead. In typed mode, you type `y` or `yes` (or a sentence like "yeah, go ahead").

**Music:** Red pauses the music while it listens and talks, then resumes it.

---

## What you can say

You don't need exact words; these are examples.

| To | Say |
|---|---|
| Open a folder | "open my Downloads folder", "open Documents", "open my projects folder" (a folder from `allowlist.toml`) |
| Start an app | "open notepad", "open calculator", "open the file explorer app", "open task manager", "open PowerPoint", "open Word", "open Excel", "open Outlook", "open VS Code" |
| Open a website | "open YouTube", "open github.com", "open YouTube in Edge" |
| Search the web | "search the web for cheap flights to Goa", "search YouTube for lofi music", "show me pictures of the Eiffel Tower", "find Pune on the map", "latest news about the World Cup", "look up Marie Curie on Wikipedia", "compare Hey Copilot with Hey Siri and OK Google" |
| Find a file | "find my resume", "where is the budget spreadsheet" |
| Open what Red found | "open it", "open the second one" |
| Write an email | "compose a mail to mom about dinner on Sunday", "write an email to alex@example.com saying I'll be late" |
| Shut down or restart | "shut down the computer in 3 hours", "restart in 10 minutes", "restart now" |
| Cancel it | "cancel the shutdown", "cancel the restart" |
| Sleep | "put the computer to sleep" |
| Lock | "lock my PC" |
| Play music | "play some music", "play Daft Punk", "play my jazz folder" |
| Play podcasts and videos | "play a podcast about loneliness", "play the Punisher trailer", "play lofi on YouTube" |
| Control playback | "pause the music", "resume", "next song", "previous track", "stop the music" |
| Change the volume | "volume up", "turn it down", "mute", "unmute", "set the volume to 30 percent" |
| Open a Windows setting | "open Bluetooth settings", "open display settings", "check for Windows updates" |
| Ask the time, date or battery | "what time is it", "what's the date today", "how much battery do I have" |
| Take a screenshot | "take a screenshot" |
| Empty the Recycle Bin | "empty the recycle bin" |
| Check your repos | "check my repos", "check the red repo", "is my red repo pushed" |

Pause, resume and next work for Red's own music and also for Spotify or a YouTube tab. Screenshots go to Pictures\Screenshots. Email drafts are never sent by Red: you check them and press Send.

---

## Settings

Your settings are in `RED_HOME\config\.env` (copied from `.env.example`). Settings already in your environment take priority over that file.

| Setting | What it does | Default |
|---|---|---|
| `RED_HOTKEY` | The shortcut that makes Red listen, for example `Ctrl+Alt+R`. `off` turns it off | `Ctrl+Alt+R` |
| `RED_WAKEWORD` | `hey_red`, a path to a custom `.onnx` wake word model, or `off` for the shortcut only | `hey_red` |
| `RED_WAKEWORD_THRESHOLD` | How sure the wake word detector must be, from 0 to 1. Lower is more sensitive | `0.5` |
| `RED_MIC_DEVICE` | Which microphone: a device number or part of its name | Windows default |
| `RED_END_SILENCE` | Seconds of quiet that mean you've finished talking. Raise it if Red cuts you off | `1.5` |
| `RED_QUICK_END_SILENCE` | A shorter pause that's enough when what you said sounds finished ("open Edge"). After "and", "um" or a comma Red still waits `RED_END_SILENCE`. `0` turns it off | `0.8` |
| `RED_MAX_COMMAND_SECONDS` | The longest a command can be | `20` |
| `RED_FOLLOW_UP_SECONDS` | After chat, an answer (Red asks "Anything more you want to know about it?"), a reply that asks you something, or something that failed, Red keeps listening this long (you hear the chime). After an action it just goes quiet. Say "no" or "that's all" and it stops. `0` turns it off | `7` |
| `RED_OVERLAY` | What Red shows while it works: `glow` around the screen edges, a `card` in the corner, `notify` (Windows notifications), or `off` | `glow` |
| `RED_WHISPER_DEVICE` | Speech recognition on `cpu`, `cuda` (NVIDIA GPU) or `auto` | `cpu` |
| `RED_WHISPER_MODEL` | Speech recognition model | `small` |
| `RED_PIPER_VOICE` | The voice Red speaks with | `en_US-lessac-medium` |
| `RED_MUSIC_DIR` | The folder Red plays music from | your Music folder |
| `RED_SEARCH_ENGINE` | `google`, `bing` or `duckduckgo` for web searches | `google` |
| `RED_BROWSER` | The browser pages and searches open in: `chrome`, `edge`, `firefox`, or `default` for the Windows default. If it isn't installed, Red uses the Windows default | `chrome` |
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

Use single quotes around Windows paths. The name is what you say ("open my projects folder").

### Repos: `repos.toml`

List the repos for "check my repos" in `RED_HOME\config\repos.toml`. `python -m red setup` creates it from `repos.example.toml`.

```toml
[repos]
red = 'D:\RED\red'
website = 'D:\Projects\website'
```

Red reports each repo as clean, ahead (unpushed commits), behind, diverged, or with uncommitted changes. It says the short version out loud and shows each repo in the status window. It only reads your repos.

### Contacts: `contacts.toml`

To write email by name ("compose a mail to mom"), list the addresses in `RED_HOME\config\contacts.toml`. `python -m red setup` creates it from `contacts.example.toml`. Without an entry, Red opens the draft with the recipient empty and tells you.

```toml
[contacts]
mom = "mom@example.com"
"alex kim" = "alex.kim@example.com"
```

### Music

Red plays `mp3`, `ogg`, `opus`, `flac` and `wav` files from your Music folder, or from `RED_MUSIC_DIR`. It doesn't play `m4a`, `aac` or `wma`. Songs are matched by file and folder names, so "play Daft Punk" works if there's a folder or file with that name. If the song isn't on your PC (or your Music folder is empty), Red plays it on YouTube instead of something random.

Podcasts, videos and trailers play on YouTube: Red searches YouTube for your words, opens the first video in your browser, and says its title. Only the search words leave your PC, and no account or API key is used. If YouTube can't be read, Red opens the search results instead.

---

**Teach Red your voice.** Run `python -m red voice-setup` and say "Hey Red" six times after the beeps, like setting up "Hey Siri". Red learns how it hears your voice and accent, so it notices you reliably. Run it again any time, for example with a new microphone. Only the words it heard are saved, never the recordings. It doesn't yet tell your voice apart from other people's.

**Talk to Red like a friend.** Anything that isn't a command ("what's on your mind?", "I had a rough day") gets a real answer, not a stock line, and Red remembers the conversation for a while. Ask "what's on my screen?" and Red tells you what you're looking at. After an answer Red asks whether you want to know more and keeps listening; say "no" or just stay quiet and it stops. Questions about new products, or "compare Hey Copilot with Hey Siri", are looked up on Wikipedia, and when Red doesn't know a name it says so instead of guessing. "Can you open YouTube?" just opens YouTube, like an order would. Only risky things (shutdown, restart, sleep, emptying the Recycle Bin) get one question first.

**Keeping Red running.** The microphone is only on while Red runs. `python -m red background` starts Red with no window, so closing PowerShell doesn't stop it, and `python -m red stop` stops it and turns the microphone off. `python -m red startup on` starts it when you sign in. If you'd rather have the microphone open only after you press Ctrl+Alt+R, set `RED_WAKEWORD=off`.

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
    ├── repos.toml     # repos for the repo check
    └── contacts.toml  # names for email drafts
```

Disk space, roughly: Python packages 2 to 3 GB, Ollama 2.1 GB, the 7B model 4.7 GB, speech and voice models under 1 GB, and room for logs.

---

## Privacy and safety

- **Everything stays on your PC.** Red never sends your voice or commands to a cloud service. Your commands and transcribed speech are logged only under `RED_HOME\logs`.
- **Reading your screen happens only when you ask** ("what's on my screen?"). Red takes one screenshot, reads its text with the OCR built into Windows, and deletes the screenshot at once. Only the local model sees the text, and the log keeps just the window title.
- **Conversations are remembered briefly.** Red keeps the last few things you both said so it can follow a conversation, in memory only, and forgets them after 10 quiet minutes.
- **Red only opens what you allow:** Windows' standard folders, plus the folders and apps in `allowlist.toml`. It never runs a command or path the model makes up.
- **Risky actions ask first.** Shutdown and restart repeat the action back to you ("Shut down in 2 hours, at 11:40 PM?") and only go ahead on "yes". No answer within 30 seconds cancels.
- **Shutdowns are limited and cancellable.** Delays are capped at 24 hours, Red always says when a shutdown is scheduled, and "cancel the shutdown" works at any time. When the time comes, Windows closes open apps without asking, so save your work first.
- **The repo check only reads.** It never pulls, pushes, or changes your repos.
- **Secrets** such as `GITHUB_TOKEN` stay in `RED_HOME\config\.env`, which is never part of the repo.
- **Email is never sent by Red.** It only opens a draft in your mail app. Red has no access to your mail account.
- **Finding files only reads.** Red never opens programs or scripts it finds; it opens their folder instead.
- **Downloads are verified.** Ollama, the llama.cpp fallback, and the speech, voice and wake word models are pinned to exact versions and checked against SHA-256 hashes, and Ollama checks the model files itself.

---

## Troubleshooting

**Start with `python -m red doctor`.** It checks Python, the packages, `RED_HOME`, the language model, the microphone and speakers, the GPU, the speech and wake word models, and your `allowlist.toml`, `repos.toml` and `contacts.toml`. It shows a ✅, ⚠️ or ❌ for each, with a fix. It only looks: it doesn't record, play sound or change anything.

- **"Smart App Control blocked llama-server" or exit code `0xC0E90002`:** Windows blocks unsigned programs. Use the default Ollama backend (`RED_LLM_BACKEND=ollama`).
- **The GPU runs out of memory:** switch to the 3B model with `RED_LLM_MODEL=qwen2.5-3b-instruct-q4_k_m`, and close other heavy apps while Red is loaded.
- **Red can't hear you:** allow microphone access for desktop apps in Settings > Privacy & security > Microphone. To use a different microphone, set `RED_MIC_DEVICE` to part of its name.
- **No status window, only Windows notifications:** the window needs PySide6, which is in `requirements.txt`. Without it, Red shows notifications for questions, answers and errors.
- **"Voice needs the voice packages":** run `pip install -r requirements.txt` again, or use `python -m red --typed`.
- **The shortcut doesn't work:** some antivirus tools block keyboard hooks, so you may need to allow Red.
- **Something else went wrong:** check `RED_HOME\logs\red.log` and `RED_HOME\logs\ollama.log`.

**Start Red when you sign in:** run `python -m red startup on`. This puts a shortcut in your Startup folder that starts Red in a minimized window. `python -m red startup off` removes it, and `python -m red startup` tells you whether it's on.

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

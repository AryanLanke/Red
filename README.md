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
- **Mail and calendar, if you sign in to Google (optional):** new mail, reading and replying, sending, and your Google Calendar
- **Controls your PC:** volume, media keys, screenshots, lock, sleep, shutdown and restart (with a delay), and emptying the Recycle Bin
- **Plays anything on YouTube:** songs, artists, podcasts, videos and trailers, in your browser
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
| NVIDIA GPU with 8 GB or more | Qwen3.5 9B on the GPU |
| GPU with 4 to 8 GB (RTX 3050, 4050) | Qwen3.5 4B on the GPU, speech recognition on the CPU |
| No GPU | Qwen2.5 3B, which is the fastest on a CPU |

`python -m red setup` looks at your GPU and memory and picks one. You can change it later with `RED_LLM_MODEL`.

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

python -m red setup    # downloads the model runtime, the language model and the voice models (about 6 GB)
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
| Play songs, podcasts and videos | "play Believer", "play some Arijit Singh", "play some music", "play a podcast about loneliness", "play the Punisher trailer" |
| Control playback | "pause the music", "resume", "next song", "previous track", "stop the music" |
| Change the volume | "volume up", "turn it down", "mute", "unmute", "set the volume to 30 percent" |
| Open a Windows setting | "open Bluetooth settings", "open display settings", "check for Windows updates" |
| Ask the time, date or battery | "what time is it", "what's the date today", "how much battery do I have" |
| Take a screenshot | "take a screenshot" |
| Empty the Recycle Bin | "empty the recycle bin" |
| Check your repos | "check my repos", "check the red repo", "is my red repo pushed" |
| Do several things at once | "open Chrome and search flights to Delhi", "mute and lock the PC", "set a timer for 5 minutes and remind me to call mom at 6 pm" (up to four; Red stops at the first one that fails or that you say no to, and tells you which) |

Pause, resume, next, previous and stop are your keyboard's media keys, so they work for YouTube in the browser, Spotify and other players. Screenshots go to Pictures\Screenshots. Email drafts are never sent by Red: you check them and press Send.

After you sign in to Google (see "Mail and calendar" below) you can also say:

| To | Say |
|---|---|
| Check your mail | "any new mail?" |
| Read a mail | "read my mail from Rahul", "what did Amazon send me" |
| Reply to it | "reply saying I'll come tomorrow" |
| Send a mail | "mail Mom that I'll be late" |
| Your calendar | "what's on my calendar tomorrow?", "add a meeting Friday at 3", "move my 5 pm to 6", "cancel my 4 pm" |

Before sending a mail or deleting an event, Red reads it back once ("Sending to Mom: I'll be late. Send?") and only goes ahead on a clear yes. Everything else just happens.

---

## Settings

Your settings are in `RED_HOME\config\.env` (copied from `.env.example`). Settings already in your environment take priority over that file.

| Setting | What it does | Default |
|---|---|---|
| `RED_HOTKEY` | The shortcut that makes Red listen, for example `Ctrl+Alt+R`. `off` turns it off | `Ctrl+Alt+R` |
| `RED_WAKEWORD` | `hey_red`, a path to a custom `.onnx` wake word model, or `off` for the shortcut only | `hey_red` |
| `RED_WAKEWORD_THRESHOLD` | How sure the wake word detector must be, from 0 to 1. Lower is more sensitive | `0.5` |
| `RED_VOICE_MATCH` | `on`: only your voice (from `voice-setup`) wakes Red. The shortcut always works | `off` |
| `RED_VOICE_MATCH_THRESHOLD` | How alike the voice must be, from 0 to 1. Empty: the value voice-setup worked out for you | empty |
| `RED_MIC_DEVICE` | Which microphone: a device number or part of its name | Windows default |
| `RED_END_SILENCE` | Seconds of quiet that mean you've finished talking. Raise it if Red cuts you off | `1.5` |
| `RED_QUICK_END_SILENCE` | A shorter pause that's enough when what you said sounds finished ("open Edge"). After "and", "um" or a comma Red still waits `RED_END_SILENCE`. `0` turns it off | `0.8` |
| `RED_MAX_COMMAND_SECONDS` | The longest a command can be | `20` |
| `RED_FOLLOW_UP_SECONDS` | After chat, an answer (Red asks "Anything more you want to know about it?"), a reply that asks you something, or something that failed, Red keeps listening this long (you hear the chime). After an action it just goes quiet. Say "no" or "that's all" and it stops. `0` turns it off | `7` |
| `RED_OVERLAY` | What Red shows while it works: `glow` around the screen edges, a `card` in the corner, `notify` (Windows notifications), or `off` | `glow` |
| `RED_WHISPER_DEVICE` | Speech recognition on `cpu`, `cuda` (NVIDIA GPU) or `auto` | `cpu` |
| `RED_WHISPER_MODEL` | Speech recognition model | `small` |
| `RED_TTS` | Voice engine: `kokoro` (more natural, default) or `piper` (fast fallback) | `kokoro` |
| `RED_VOICE` | Kokoro voice name, such as `af_heart`, `af_bella`, `am_adam`, `bf_emma` | `af_heart` |
| `RED_VOICE_SPEED` | Voice speed multiplier, from `0.7` to `1.5` | `1.0` |
| `RED_PIPER_VOICE` | Fallback Piper voice used if Kokoro is unavailable or `RED_TTS=piper` | `en_US-lessac-medium` |
| `RED_SEARCH_ENGINE` | `google`, `bing` or `duckduckgo` for web searches | `google` |
| `RED_WEB_SEARCH` | `on` or `off`: answers also check web pages through Red's own SearXNG, not just Wikipedia. See *Privacy and safety* | `on` |
| `RED_SEARCH_URL` | Use your own [SearXNG](https://docs.searxng.org/) on this PC instead of Red's, such as `http://127.0.0.1:8888`. Only addresses on your own PC are accepted | Red's own |
| `RED_BROWSER` | The browser pages and searches open in: `chrome`, `edge`, `firefox`, or `default` for the Windows default. If it isn't installed, Red uses the Windows default | `chrome` |
| `RED_LLM_MODEL` | `qwen3.5-4b`, `qwen3.5-9b` (8 GB+ GPU), `qwen2.5-3b-instruct-q4_k_m` (no GPU), `qwen3.5-2b` or `qwen2.5-7b-instruct-q4_k_m` | `qwen3.5-4b` |
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

### Mail and calendar (optional)

Red can use your Gmail, Google Calendar and Google Contacts. It's optional, and nothing changes if you don't sign in. Red ships no Google client of its own, so you make a free one once:

1. In [Google Cloud Console](https://console.cloud.google.com/), create a project and enable the **Gmail API**, the **Google Calendar API** and the **People API**.
2. Under **OAuth consent screen**, choose External, keep it in Testing, and add your own Google account as a test user.
3. Under **Credentials**, create an **OAuth client ID** of type **Desktop app**, download its JSON, and save it as `RED_HOME\config\google-client.json`.
4. Run `python -m red google-login`. Your browser opens Google's page; approve it. Then restart Red (`python -m red stop`, then `python -m red background`).

Red asks for the smallest permissions that work: reading mail, sending mail, your calendar's events, and reading your contacts. The sign-in token is saved in `RED_HOME\config\google-token.json`, only on your PC. `python -m red google-logout` revokes it and deletes the file. Names you say ("mail Mom") come from your Google Contacts first, then `contacts.toml`; Red never guesses an address. Red talks to Google directly with Python's standard library: no extra packages to install.

### Playing music and videos

Everything you ask Red to play, songs and artists as well as podcasts, videos and trailers, plays on YouTube: Red searches YouTube for your words, opens the first video in your browser (`RED_BROWSER`), brings it to the front, and says its title. "Play some music" starts a mix of popular songs. Red doesn't play music files from your PC. Only the search words leave your PC, and no account or API key is used. If YouTube can't be read, Red opens the search results instead.

---

**If "Hey Red" doesn't wake Red,** run `python -m red wake-test` and say it a few times: it prints what the microphone hears, the score, and whether the microphone is too quiet. "Hey Red" followed by a command in one breath wakes Red too (you still wait for the beep before saying the command).

**Teach Red your voice.** Run `python -m red voice-setup` and say "Hey Red" ten times after the beeps, like setting up "Hey Siri". Red learns how it hears your voice and accent, so it notices you reliably, and it learns your voice itself. Set `RED_VOICE_MATCH=on` and Red answers only your "Hey Red" and stays silent for anyone else (the shortcut always works). It's off until you turn it on; try it with someone else in the room first, and adjust `RED_VOICE_MATCH_THRESHOLD` if others get in or Red ignores you. Run voice-setup again any time, for example with a new microphone. Only the words it heard and a set of numbers describing your voice are saved, never the recordings.

**Talk to Red like a friend.** Anything that isn't a command ("what's on your mind?", "I had a rough day") gets a real answer, not a stock line, and Red remembers the conversation for a while. Ask "what's on my screen?" and Red tells you what you're looking at. After an answer Red asks whether you want to know more and keeps listening; say "no" or just stay quiet and it stops. Questions about new products, or "compare Hey Copilot with Hey Siri", are looked up on Wikipedia, and when Red doesn't know a name it says so instead of guessing. "Can you open YouTube?" just opens YouTube, like an order would. Common commands ("open YouTube", "volume up", "pause", "lock", "what time is it", "play Believer") don't wait for the language model at all, so they're done about a second after you stop talking. Only risky things (shutdown, restart, sleep, emptying the Recycle Bin) get one question first.

**Long answers start right away.** Red starts speaking the first sentence while the rest is still being written, so even "tell me the whole story" begins in about two seconds. To cut Red off, say "Hey Red" (or press Ctrl+Alt+R) while it's talking: it stops and listens for what you say next.

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

Disk space, roughly: Python packages 2 to 3 GB, Ollama 2.1 GB, the model 2 to 7 GB (Qwen3.5 4B is about 3.4 GB), speech and voice models under 1 GB, and room for logs.

---

## Privacy and safety

- **Everything stays on your PC.** Red never sends your voice, your screen or your commands to a cloud service, and the AI runs on your PC. Your commands and transcribed speech are logged only under `RED_HOME\logs`. The one exception is opt-in: after `python -m red google-login`, the text of the mails and calendar events you ask about goes between Red and your own Google account. Summaries of your mail are written by the local model.
- **Answers check the web, and you can turn that off.** For a fact question ("who made Siri"), Red reads Wikipedia and searches the web through its own copy of [SearXNG](https://docs.searxng.org/), which `python -m red setup` installs and Red runs on your PC only. The words of your question go to the search engines SearXNG asks (such as Google and Brave), and Red downloads the top three result pages. Those sites see your internet address, as they would if you searched in your browser. No voice, account, cookies or history is sent. Set `RED_WEB_SEARCH=off` and Red answers from Wikipedia only, which gets just the topic's words ("Siri"). With no internet, Red answers from its own knowledge at once and says so. Text from web pages is only used to write the spoken answer, with links removed. It can't make Red do anything by itself, and anything risky still needs your spoken "yes". A page can be wrong or misleading, though, so Red says where its answer came from.
- **Reading your screen happens only when you ask** ("what's on my screen?"). Red takes one screenshot, reads its text with the OCR built into Windows, and deletes the screenshot at once. Only the local model sees the text, and the log keeps just the window title.
- **Conversations are remembered briefly.** Red keeps the last few things you both said so it can follow a conversation, in memory only, and forgets them after 10 quiet minutes.
- **Red only opens what you allow:** Windows' standard folders, plus the folders and apps in `allowlist.toml`. It never runs a command or path the model makes up.
- **Risky actions ask first.** Shutdown and restart repeat the action back to you ("Shut down in 2 hours, at 11:40 PM?") and only go ahead on "yes". No answer within 30 seconds cancels.
- **Shutdowns are limited and cancellable.** Delays are capped at 24 hours, Red always says when a shutdown is scheduled, and "cancel the shutdown" works at any time. When the time comes, Windows closes open apps without asking, so save your work first.
- **The repo check only reads.** It never pulls, pushes, or changes your repos.
- **Secrets** such as `GITHUB_TOKEN` stay in `RED_HOME\config\.env`, which is never part of the repo.
- **Email is sent only after a read-back.** Without the Google sign-in, Red only opens a draft in your mail app and has no access to your mail. With it, Red reads every mail or reply back to you and sends it only on a clear yes, and it does the same before deleting a calendar event.
- **Finding files only reads.** Red never opens programs or scripts it finds; it opens their folder instead.
- **Downloads are verified.** Ollama, the llama.cpp fallback, and the speech, voice and wake word models are pinned to exact versions and checked against SHA-256 hashes, and Ollama checks the model files itself.

---

## Troubleshooting

**Start with `python -m red doctor`.** It checks Python, the packages, `RED_HOME`, the language model, the microphone and speakers, the GPU, the speech and wake word models, and your `allowlist.toml`, `repos.toml` and `contacts.toml`. It shows a ✅, ⚠️ or ❌ for each, with a fix. It only looks: it doesn't record, play sound or change anything.

- **"Smart App Control blocked llama-server" or exit code `0xC0E90002`:** Windows blocks unsigned programs. Use the default Ollama backend (`RED_LLM_BACKEND=ollama`).
- **The GPU runs out of memory:** switch to a smaller model, `RED_LLM_MODEL=qwen3.5-2b` or `qwen2.5-3b-instruct-q4_k_m`, and close other heavy apps while Red is loaded.
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

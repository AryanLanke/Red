# Changelog

All notable changes to Red are listed here. Versions follow [Semantic Versioning](https://semver.org/).

## [0.1.0] - unreleased (draft)

The first version of Red: a local voice and action assistant for Windows 11. Everything runs on your PC, with no cloud model.

### Added

**Talking to Red**
- Press **Ctrl+Alt+R**, or say the **"Hey Red"** wake word, then speak. If the wake word can't start, Red says so once and keeps working with the shortcut.
- Speech recognition with Whisper (small), on the CPU by default. Red answers out loud with a Piper voice.
- A small floating status window in the bottom-right corner shows Listening, Thinking, Confirm, Speaking and Problem. It never takes the keyboard focus. Without PySide6, Red shows Windows notifications instead.
- Typed mode (`python -m red --typed`), a dry run that only shows what Red would do (`--dry-run`), and one-off commands (`python -m red run "..."`, `python -m red route "..."`).
- A local language model (Qwen2.5 7B, or 3B for smaller GPUs) through a pinned, code-signed Ollama that Red starts and stops itself. Red can also use an Ollama that's already running, or your own OpenAI-compatible server.

**What Red can do (24 actions)**
- Open folders (Downloads, Documents, Desktop, Pictures, Music and Videos, even when they're in OneDrive) and your own folders from `allowlist.toml`.
- Start apps: Notepad, Calculator, File Explorer, Task Manager, Office (Word, Excel, PowerPoint, Outlook, and more) found through Windows' App Paths, and your own apps from `allowlist.toml`.
- Open websites, and search the web, YouTube, images, maps, news or Wikipedia in your browser. The search engine is Google, Bing or DuckDuckGo.
- Find files by name in your usual folders, and open the one you pick.
- Write email drafts in your mail app, with names from `contacts.toml`. Red never sends email.
- Shut down or restart after a delay of up to 24 hours, and cancel it again. Sleep, lock, and empty the Recycle Bin.
- Volume up, down, mute, unmute and set to a percent. Media play/pause, next and previous, for Red's music and for apps like Spotify.
- Play music from your Music folder (mp3, ogg, opus, flac, wav): play, pause, resume, next and stop. Red pauses the music while it listens and talks.
- Open Windows Settings pages, tell the time, the date and the battery level, and take screenshots.
- Check your Git repos (from `repos.toml`) against GitHub and report what's unpushed, behind, diverged or uncommitted.

**Setup and tools**
- `python -m red setup` downloads and verifies everything: Ollama, the language model, Whisper, the Piper voice and the wake word model. It also creates `allowlist.toml`, `repos.toml` and `contacts.toml` from the examples.
- `python -m red doctor` checks Python, the packages, `RED_HOME`, the model, the microphone, the speakers, the GPU, the voice models and your config files. Each result is ✅, ⚠️ or ❌, with a fix.
- `python -m red startup on|off` starts Red when you sign in, through a shortcut in your Startup folder.
- Every setting is in `RED_HOME\config\.env` (see `.env.example`). Everything Red downloads or writes stays in one folder, `RED_HOME`.

### Safety
- Shutdown, restart, sleep and emptying the Recycle Bin always ask first, out loud or typed, and repeat the action ("Shut down in 2 hours (at 11:40 PM)?"). Only "yes" goes ahead. Anything else, or 30 seconds of silence, cancels.
- Red only opens Windows' standard folders and what you list in `allowlist.toml`. It never runs a command or path the model makes up.
- Web searches use fixed URL templates with the query encoded. Websites must be `http` or `https`.
- Finding files only reads, and Red never opens a program or script it found. The repo check only reads, too.
- Every command and its result is logged in `RED_HOME\logs\commands.jsonl`, on your PC only.
- Every download is pinned to a version and checked against a SHA-256 hash.

### Known issues
- "Show me pictures of …" and "find … on the map" sometimes open the page through a link the model builds, instead of Red's search. The same page opens.
- Say "open the file explorer app"; "open file explorer" can be taken as a folder and refused.
- The music player can't play m4a, aac or wma files.
- With 6 GB of video memory, Whisper runs on the CPU, because the language model needs the GPU. A command takes about 2 seconds to transcribe.
- When a shutdown or restart time comes, Windows closes open apps without asking. Save your work first.

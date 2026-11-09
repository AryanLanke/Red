# Red: what to do next

Updated 2026-11-09 (morning). The first plan (7 tasks) and the second plan (9 tasks) are done: see `git log`
and progress.md 5, 7.1, 7.2 and 7.4 for what each one did and the numbers. This third plan comes from the
user's voice test at 04:26–04:46 on 2026-11-09 (log: RED_HOME\logs\commands.jsonl and red.log).

Read this first, then AGENTS.md. Do the tasks in order. Each task lists the files and how to check it.
After finishing a task: run the tests, commit (several small commits), push to main, restart the hidden Red
(`python -m red stop` then `python -m red background`), and tick it off here.

**If your usage limit is near (90%), read "Usage limit" in the Rules first.**

## The goal

A **Windows-only** voice assistant that competes with "Hey Siri", "OK Google" and "Hey Copilot". The
wake phrase is "Hey Red". Red must be **faster than doing it by hand** and must **finish the whole job**,
otherwise the user does it themselves.

- **Any Windows PC:** it runs on everything from a laptop with no GPU to one with an 8 GB+ GPU (RTX 3050,
  4050 and so on).
- **English only.**
- **Local and free:** the AI model, speech-to-text, voice, wake word and screen reading all run on the
  PC, with no account needed. The one exception is the optional Google sign-in for mail and calendar
  (built in the second plan).

Speed targets, measured from when the user stops talking (the `Timing` lines in `red.log`):

| Request | Target |
|---|---|
| "open Edge", "volume up", "pause", "lock" | done in about 1–3 s |
| "play Believer" | playing in about 2–3 s |
| a question or chat | Red starts speaking in about 1–2 s |
| "give me a big summary" | starts in about 1–2 s, then talks as long as the answer needs |

Waiting 5 s or more before anything happens is a failure: the user could have done it by hand.

**Not doing:**
- smart home
- other languages
- Mac or Linux
- cloud AI models
- big models that run partly on the CPU (gpt-oss-20b, Qwen3.5-35B-A3B), which are too slow

## Done in the second plan (2026-11-09)

Browser fix (Chrome by default, `RED_BROWSER`), follow-up questions and a Whisper vocabulary, every "play"
on YouTube, Qwen3.5 4B, the fast path for common commands, speaking while the model writes and cutting in
with "Hey Red", Gmail and Calendar (optional sign-in), voice match (off by default), several commands in one
sentence. **Not yet tried by the user:** the Google sign-in, voice match, and cutting in.

## What the user found in the voice test (2026-11-09, 04:26–04:46)

| Said | What happened | Cause found in the logs |
|---|---|---|
| "Hey Red" (many times) | Almost never woke | `match_score` gives 0 to anything over 4 words, and Whisper wrote "Hey Red Red Red Red Red Red Red" and "Hey Red, hey Red, hey Red" (both 0.00). "Hey Red, <command>" in one breath scores 0.45, below the 0.5 threshold. |
| "Open YouTube" | Opened, then YouTube was blank | Unknown: the log shows the right window ("YouTube - Google Chrome") fronted. Must be reproduced. |
| "Play any song of my favorite" | A random video | `play_online` searched the words "any song of my favorite". |
| "Play Crazy by Le Sserafim" | Misheard ("Alexa Raffy", "Lisa Raffin"), so it played "If Alexa was RUDE" and Shorts | Whisper doesn't know the artist; the first result is used without a check. |
| "Play my favorites from my YouTube playlist" | Other music | Red has no access to the user's playlists. |
| "When VS Code says finished, remind me" | A reminder at 12:00 AM that failed, after two chat replies about waking up | `set_reminder` got `"time": "00:00"`, invented by the model. Nothing can watch a window. |
| "Let's have a debate" | Said a few words, then went quiet | Routed to `answer` (one reply, no turn-taking). |

## Tasks, in order

### 1. Make "Hey Red" wake reliably
**Why:** this is the first thing the user does, and it failed in the whole test.
- In `match_score` (`red/wakeword.py`), collapse repeats before counting words: "hey red red red" and
  "hey red, hey red" become "hey red".
- One breath: "Hey Red, open YouTube" must wake, and the words after "Hey Red" become the command, with no
  second recording. Keep the guards against "a red light" (the phrase must start the clip and follow a
  pause).
- Add `python -m red wake-test`: for 30 s it prints each wake check, the words heard and the score, so the
  user (and you) can see what the microphone gives.
- Look at the real clips: log the loudness of each check, and see whether the microphone is too quiet or the
  VAD cuts the start ("Hey" lost).
- **Files:** `red/wakeword.py`, `red/listener.py`, `red/__main__.py`, `tests/test_wakeword.py`.
- **Check:** unit tests with the lines from `red.log` of 2026-11-09 as cases (text and expected score); Piper
  clips of "Hey Red" and "Hey Red, open YouTube" through `HeyRedDetector`; then the user tries it by voice.

### 2. "Open YouTube" shows a blank page
- **Reproduce first**, with the hidden Red stopped: `python -m red run "open YouTube"` with VS Code in front,
  read the screen 3 s later with `red/screen.py` `read_screen`, and check it has YouTube's words. Try
  Chrome already open and closed, and the window minimised or behind other windows.
- Suspects, to test and not assume: fronting (`Win32Desktop.front` in `red/windows.py`) before the page has
  painted; Chrome throttling a window it thinks is hidden. Fix what the test shows, and write the finding in
  progress.md 7.1.
- **Files:** `red/windows.py`, `red/browser.py`.

### 3. Play the right song
- **Names.** A personal list, `RED_HOME\config\vocabulary.txt` (one name per line, for example
  "LE SSERAFIM"), added to Whisper's hotwords (`command_vocabulary` in `red/stt.py`). Then correct the query
  with YouTube's public search suggestions before searching (only the search words leave the PC).
- **A real song.** Skip Shorts and anything under 60 s; prefer a result whose title has the query's words
  (`first_video` and `fetch_results` in `red/tools/youtube.py`). If nothing fits, open the results page and
  say so, instead of playing the first thing.
- **"My favorites", "my liked songs", "my playlist":** open the user's own list in Chrome, where they are
  signed in to YouTube (Liked videos is playlist `LL`, YouTube Music's likes `LM`; check which URL starts
  playing). A named playlist ("my workout playlist") needs YouTube access: add the `youtube.readonly` scope
  to the optional Google sign-in (`red/google_auth.py`) and find the playlist by name.
- **Files:** `red/stt.py`, `red/tools/youtube.py`, `red/google_auth.py`, `red/router.py`.
- **Check:** unit tests with saved result pages (never the live site) for "Crazy by Le Sserafim", for the
  misheard "Lisa Raffin", and for "play my liked songs"; real-model routing for the three.

### 4. "Tell me when VS Code finishes"
- New harmless tool `notify_when_done` (`red/tools/watch.py`): the app's name and, optionally, words to wait
  for. Every 15 s it reads that window's title and text (`red/screen.py`, OCR of that window only) and says
  aloud (`VoiceApp.announce`) when it sees "finished", "done" or "completed", or when the text has stopped
  changing for 2 minutes. At most 3 hours; "stop watching" cancels. Say plainly what it can and can't see.
- `set_reminder` must never use a time the user didn't say. With no time in their words (`set_command`, as
  `cancel_reminder` does), ask "When?".
- Add router examples for the 04:27 sentences.
- **Files:** `red/tools/watch.py`, `red/tools/reminders.py`, `red/router.py`, `red/tools/__init__.py`.
- **Check:** unit tests with a fake screen that changes over time; real-model routing for the four sentences
  in the log.

### 5. Debates and back-and-forth talk
- "Let's have a debate", "you choose the topic", "quiz me": route to chat, not `answer`. Give `Chat` a
  debate mode: Red picks a side and the topic if the user didn't, says 2 or 3 sentences, ends with "Your
  turn.", and keeps listening for longer than usual (15 s). It answers the user's point, until "stop",
  "you win", or silence. Quiz and storytelling can reuse the same mode if it is cheap.
- **Files:** `red/chat.py`, `red/router.py`, `red/__main__.py` (follow-up length), `tests/test_voice_app.py`.
- **Check:** `tests/test_voice_app.py` with fakes: a debate takes at least three turns and ends on "stop";
  real-model routing for the 23:53 sentence.

### 6. The Red app: set everything up in one window
**Why:** the user asked for an app, because setting up from the command line is too hard.
- First-run wizard: hardware check and model choice (`red/hardware.py`), downloads with progress and
  checksums, microphone pick with a level meter, `voice-setup` with live "Hey Red" checks, an optional
  voice-match test, and the optional Google sign-in.
- Then the settings pages from "Later" below.
- PySide6 (already used). Frosted, milky glass with no edge line and no rounded edges. It saves
  `RED_HOME\config\.env` through `Settings` and restarts the hidden Red when you press Save. Start menu
  shortcut and `python -m red app`.
- **Files:** new `red/app/` package, `red/__main__.py`, `red/config.py`, `red/startup.py`.
- **Check:** render every page offscreen (`QT_QPA_PLATFORM=offscreen`), look at the screenshots, and unit-test
  that saving changes only the keys on the page. Ask the user before changing their `.env`.

## Later: more for the Red app

**Sections:**
- **Model:** the current model, a pick from `MODELS` with each one's `best_for` line, downloads, and the
  hardware recommendation.
- **Voice:** Piper voices with a Play sample button (downloaded: female `en_US-amy`, `en_US-lessac`,
  `en_GB-jenny_dioco`, `en_US-libritts_r`; male `en_US-joe`, `en_US-ryan`, `en_GB-alan`), and speed.
- **Wake phrase and listening:** "Hey Red", "Yo Red", "Okay Red", "What's up Red" with voice training,
  sensitivity, hotkey, microphone, voice match on/off and re-recording.
- **Speech-to-text:** Whisper model (`base.en` / `small.en`) and device.
- **Personality:** normal or opt-in casual (banter that swears back).
- **Browser:** `RED_BROWSER` and the search engine.
- **Accounts:** Google sign-in and sign-out.
- **General:** start with Windows (`red/startup.py`).

Also later:
- A one-click Windows installer, so users need no Python or venv. Without a code-signing certificate,
  Windows warns about an unknown publisher.
- A glow that reacts to the voice.
- Ollama that reuses the cached prompt for Qwen3.5: check each new Ollama release (progress.md 5), and then
  Qwen3.5 can be the model for PCs with no GPU too.

## Rules: what to do and what not to do

Do:
- Read the latest lines of `RED_HOME\logs\commands.jsonl` and `red.log` before changing behaviour. The
  user's real sentences are there.
- Test against the real local model (`RED_INTEGRATION=1`) whenever routing, prompts or the model change.
  Run the full unit suite with the shared venv:
  `$env:RED_HOME="D:\RED"; $env:QT_QPA_PLATFORM="offscreen"; D:\RED\.venv\Scripts\python.exe -m pytest --basetemp="D:\RED\cache\pytest-tmp"`.
- Measure speed before and after every speed change, with numbers from the `Timing` lines in `red.log`.
- For any visual change, render previews offscreen and look at them before telling the user it's done.
- Commit as several small commits and push to `main` (the user wants contributions), then restart the
  hidden Red so the user tests the new code.
- Use files for long scripts and commit messages. PowerShell and bash here-docs break on quotes.
- Keep confirmations for shutdown, restart, sleep, emptying the Recycle Bin, and sending a mail or deleting a calendar
  event (the user chose a read-back for those two). Keep allowlists. Never run model text as a command.

Don't:
- Don't ask permission or "Anything else?" for harmless actions.
- Don't use stock assistant lines ("I'm here to help", "How can I assist you").
- Don't let Red claim things that aren't true (seeing images, music playing, a body, a page that didn't
  open).
- Don't send voice, screen or the AI's work to any cloud service. Red is local-only. Public look-ups
  (Wikipedia, weather, news, YouTube search) are fine, and so is the user's own Google mail and calendar
  after they sign in.
- Don't build for Mac, Linux or other languages.
- Don't install packages with unsigned native DLLs. Smart App Control blocks them (it blocked `winrt-*`).
  Use Windows PowerShell or signed system APIs instead.
- Don't run a hidden test copy of Red while the user is testing. Stop the background Red first, and
  restart it after.
- Don't bring back a rim or outline line on the glow, or rounded-corner edges. The user wants frosted,
  milky, liquid glass with no edge line.
- Don't use "Jarvis" anywhere in Red's text or defaults.

Usage limit (any coding agent: Claude, DeepSeek, Kimi or another):
- If your usage (a weekly or session limit, or any provider's quota) reaches **90%**, don't start anything
  new. Finish the smallest working part of the task you are on, run the unit tests, commit, **push to
  `main`**, and write a short hand-off note under that task in this file: what is done, what is left, and
  the exact next step. Then stop and tell the user.
- If you can't see your usage, commit and push after every task anyway, and after every hour of work.
- Never leave uncommitted work, a half-edited file, or a stopped hidden Red when you stop. Restart it.

Any agent:
- Read AGENTS.md first. This is Windows with PowerShell 5.1: no `&&` (use `;`), and the shared venv is
  `D:\RED\.venv` with `RED_HOME=D:\RED`.
- Don't write code through shell here-docs: they turn `\b` into a backspace and break quotes. Write files
  with your editor tool, and after any script edit search the changed files for control characters.
- Don't change `D:\RED\config\.env` without asking the user.

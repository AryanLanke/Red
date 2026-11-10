# DeepSeek v4.1 Flash — Execution Plan & Handoff Guide

> **Current Repository State:** Clean on `main`. Kokoro-82M TTS committed (`8500e14`). Full test suite: **1,310 passed, 0 failed**.
> **Location:** `D:\RED\red` (Git repository). `RED_HOME` is `D:\RED`.
> **Python:** `D:\RED\.venv\Scripts\python.exe` (Python 3.11.9 on Windows 11).

---

## 1. DeepSeek v4.1 Flash: Strengths & Rules for Success

DeepSeek v4.1 Flash is fast and strong at Python, regex, tool calling, and unit tests, but to get 100% accuracy and avoid hallucinations over your 2-day timeline, follow these rules:

1. **One task per session/prompt**: Never say "do tasks 2, 3, 4, 5, 6". Feed one task at a time.
2. **Test-Driven Verification**: DeepSeek must run pytest after every file edit. If a test fails, DeepSeek must fix it before moving on.
3. **Windows Constraints**: DeepSeek must remember this is Windows PowerShell (`$env:RED_HOME="D:\RED"`, `$env:QT_QPA_PLATFORM="offscreen"`). No bash assumptions.
4. **No Placeholders**: Never let it write `# TODO: implement this later`. All code must be complete.

---

## 2. The 2-Day Roadmap for DeepSeek

```
Day 1 (Quick Wins & Core Tools):
  ├── Task 2: Fix "Open YouTube" blank page (30 mins)
  ├── Task 3: Music & song playback improvements (2-3 hours)
  └── Task 4: Build notify_when_done tool for VS Code / processes (2-3 hours)

Day 2 (Conversation & UI):
  ├── Task 5: Multi-turn debates and quiz mode (2-3 hours)
  └── Task 6: PySide6 Red App Setup Wizard (3-4 hours)
```

---

## 3. Copy-Paste Prompts for DeepSeek (Task by Task)

When you open a new session with DeepSeek v4.1 Flash, copy-paste the project preamble once, then feed the specific task prompt.

### Initial Preamble (Give this to DeepSeek at the start of any new session):
```text
You are an expert Windows Python developer working on "Red", a local offline voice assistant for Windows 11 located at D:\RED\red.
RED_HOME is D:\RED. Python is D:\RED\.venv\Scripts\python.exe.
Read AGENTS.md, HANDOFF.md, and plan.md first.
Rules:
- Windows PowerShell syntax only.
- All tests must pass: $env:RED_HOME="D:\RED"; $env:QT_QPA_PLATFORM="offscreen"; D:\RED\.venv\Scripts\python.exe -m pytest -q --basetemp=D:\RED\cache\pytest-tmp
- Commit working changes after each task.
```

---

### Task 2 Prompt: Fix "Open YouTube" blank page
```text
Read Task 2 in plan.md.
When the user says "Open YouTube", the browser window opens or comes to front, but sometimes shows a blank white page.
1. Inspect red/windows.py (Win32Desktop.front) and red/browser.py (open_url / open_browser).
2. Look at how window fronting interacts with Chrome hardware acceleration and window repaint. Ensure Chrome is given sufficient paint time or correct Win32 SW_RESTORE / SetForegroundWindow calls.
3. Write a reproduction test in tests/test_browser.py or tests/test_windows.py.
4. Run tests, verify they pass, and commit: git commit -m "fix(browser): prevent YouTube blank page on window fronting"
```

---

### Task 3 Prompt: Play the right song
```text
Read Task 3 in plan.md.
Users say "Play Crazy by Le Sserafim" or "Play my liked songs", and currently it can pick Shorts, wrong titles, or misheard words.
1. STT hotwords: Check red/stt.py to support loading vocabulary names from RED_HOME\config\vocabulary.txt into Whisper's prompt/hotwords.
2. In red/tools/youtube.py:
   - Filter out YouTube Shorts (/shorts/ URLs) and videos under 60 seconds.
   - Prefer results where the video title matches words in the query.
   - If user asks for "my liked songs" or "my favorites", open YouTube's Liked Videos playlist ('https://www.youtube.com/playlist?list=LL').
3. Add unit tests in tests/test_youtube.py with mock HTML responses (do NOT hit live YouTube in tests).
4. Run tests and commit: git commit -m "feat(youtube): filter Shorts, match query titles, and support liked playlist"
```

---

### Task 4 Prompt: Build `notify_when_done` tool
```text
Read Task 4 in plan.md.
User says: "When VS Code finishes, remind me" or "Tell me when the build is done".
1. Create red/tools/watch.py containing a tool notify_when_done(app_name: str, target_text: str = "").
2. Every 15 seconds, inspect window title and text using red/screen.py. When "finished", "done", or "completed" is detected (or target_text matches), notify via VoiceApp.announce.
3. Timeout after 3 hours max. Add ability to cancel when user says "stop watching".
4. Register the tool in red/tools/__init__.py and default_registry().
5. Add routing examples in red/router.py.
6. Write tests in tests/test_watch.py with mock window frames.
7. Run tests and commit: git commit -m "feat(tools): add notify_when_done watcher tool"
```

---

### Task 5 Prompt: Multi-turn debate mode
```text
Read Task 5 in plan.md.
User says: "Let's have a debate" or "Quiz me".
1. Update red/router.py so debate requests route to chat instead of one-shot answer.
2. In red/chat.py: add a multi-turn debate state. Red picks a side and topic if not given, responds with 2-3 concise punchy sentences, ends with "Your turn.", and increases follow-up listening timeout to 15 seconds.
3. Stops when user says "stop", "you win", or after silence.
4. Write unit tests in tests/test_chat.py and test_voice_app.py.
5. Run tests and commit: git commit -m "feat(chat): multi-turn debate and discussion mode"
```

---

### Task 6 Prompt: PySide6 Setup App (Windowed Wizard)
```text
Read Task 6 in plan.md.
Create a clean PySide6 setup & settings app for Red (startable via `python -m red app`).
1. Create package red/app/ with QMainWindow.
2. Pages: Hardware check (CPU/GPU/RAM), Model selection & download status, Microphone picker with live volume meter, Voice selection (Kokoro/Piper).
3. Offscreen testability: Ensure all widgets can be instantiated and tested with QT_QPA_PLATFORM=offscreen.
4. Saving settings updates RED_HOME\config\.env cleanly via Settings class.
5. Write unit tests in tests/test_app.py.
6. Run tests and commit: git commit -m "feat(gui): PySide6 setup and settings wizard"
```

---

## 4. How to Verify in Any Agent Session

Whenever DeepSeek finishes any task, paste this command to verify:
```powershell
$env:RED_HOME="D:\RED"
$env:QT_QPA_PLATFORM="offscreen"
cd D:\RED\red
D:\RED\.venv\Scripts\python.exe -m pytest -q --basetemp=D:\RED\cache\pytest-tmp
```
If you see all green (e.g., `1310+ passed`), you are ready to commit and advance to the next task!

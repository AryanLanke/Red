# AUTONOMOUS TASK QUEUE & HANDOFF FOR QODER (DeepSeek v4.1 Flash)

> **Workspace Root:** `D:\RED`  
> **Git Repository:** `D:\RED\red` (Branch: `main`)  
> **Python Virtualenv:** `D:\RED\.venv\Scripts\python.exe`  
> **Environment Variables:** `RED_HOME=D:\RED`, `QT_QPA_PLATFORM=offscreen`  
> **Repository Baseline:** Commit `b79d7eb`. Kokoro-82M TTS is 100% finished. **1,310 tests passing**.

---

## Autonomous Execution Protocol (FOR QODER AGENT)

You are running autonomously inside Qoder. When given this file, **do not stop after one task**. Work through the tasks below sequentially from Task 2 to Task 6 using this cycle:

```
[1. Read Specs] ➔ [2. Edit Code] ➔ [3. Run Pytest] ➔ [4. Fix if any failures] ➔ [5. Git Commit] ➔ [6. Mark [x]] ➔ [7. Proceed to Next Task]
```

### Global Rules:
1. **TTS Engine Standard**: Kokoro-82M ONNX has replaced Piper as Red's default primary voice (`RED_TTS=kokoro`, default voice `af_heart`). Piper is strictly an automatic fallback if files are missing. All new voice outputs, UI settings, wizards, and tests must treat Kokoro as primary.
2. **Always set environment variables** before running Python commands in PowerShell:
   ```powershell
   $env:RED_HOME="D:\RED"; $env:QT_QPA_PLATFORM="offscreen"
   ```
2. **Always run tests** using the virtualenv Python:
   ```powershell
   D:\RED\.venv\Scripts\python.exe -m pytest <test_files> -q --basetemp=D:\RED\cache\pytest-tmp
   ```
3. **No placeholders**: Never leave `# TODO` or unwritten functions. Every feature must be fully functional.
4. **Clean Commits**: Commit working code after each task finishes and passes tests.
5. **Tick off the task**: Change `- [ ]` to `- [x]` in this file after committing.

---

## Task Progress Checklist

- [x] **Task 0: Kokoro-82M TTS Integration** (Completed & committed in `8500e14`, 24/24 tests passing)
- [x] **Task 1: Wake Reliability** (Completed & committed in `8bc4f71`)
- [x] **Task 2: Fix "Open YouTube" shows blank page**
- [x] **Task 3: Play the right song (Filter Shorts, match titles, liked playlist)**
- [ ] **Task 4: Build `notify_when_done` tool for VS Code & processes**
- [ ] **Task 5: Multi-turn debates and back-and-forth talk**
- [ ] **Task 6: PySide6 Setup and Settings App**

---

## Detailed Task Specifications

---

### Task 2: Fix "Open YouTube" shows blank page

#### Problem:
When the user says "Open YouTube", Chrome opens or comes to the front, but sometimes displays a blank white page because the window was minimised or throttled by Chrome's background rendering before paint finished.

#### Implementation Steps:
1. **Inspect [`red/windows.py`](red/windows.py)**:
   - Check `Win32Desktop.front(hwnd)`.
   - When fronting a minimised window, ensure `win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)` is executed before `SetForegroundWindow(hwnd)`.
   - Add a brief yield / repaint trigger so Windows forces Chrome to repaint the client area.
2. **Inspect [`red/browser.py`](red/browser.py)**:
   - In `open_url(url, browser=...)`, verify the URL passed for YouTube is valid (`https://www.youtube.com`).
   - If an existing YouTube tab or window is found, fronting must properly wake up the rendering process.
3. **Write Unit Tests**:
   - In `tests/test_windows.py` or `tests/test_browser.py`, test the fronting sequence with mock HWND states (minimised, hidden, normal).
4. **Verification Command**:
   ```powershell
   $env:RED_HOME="D:\RED"; $env:QT_QPA_PLATFORM="offscreen"; cd D:\RED\red; D:\RED\.venv\Scripts\python.exe -m pytest tests/test_windows.py tests/test_browser.py -v
   ```
5. **Git Commit**:
   ```powershell
   cd D:\RED\red; git add red/windows.py red/browser.py tests/; git commit -m "fix(browser): ensure window restore and repaint on fronting to prevent blank YouTube page"
   ```

---

### Task 3: Play the right song (Filter Shorts, match titles, liked playlist)

#### Problem:
When the user says "Play Crazy by Le Sserafim" or "Play my liked songs", Red sometimes plays YouTube Shorts, misheard songs, or random videos.

#### Implementation Steps:
1. **Vocabulary Hotwords in [`red/stt.py`](red/stt.py)**:
   - Read `RED_HOME\config\vocabulary.txt` if it exists.
   - Inject these names as hotwords / initial prompt into faster-whisper's transcribe call (`prompt` parameter) so non-English artist names (e.g. "LE SSERAFIM") are transcribed accurately.
2. **Filter Shorts & Pick Right Video in [`red/tools/youtube.py`](red/tools/youtube.py)**:
   - In `first_video()` and `fetch_results()`:
     - Ignore any video URL that contains `/shorts/`.
     - Skip videos under 60 seconds unless the user specifically said "short".
     - Prefer results whose title contains words from the search query.
     - If no good match is found, fallback to opening YouTube search results (`https://www.youtube.com/results?search_query=...`) and tell the user.
3. **Liked Songs & Playlists in [`red/tools/youtube.py`](red/tools/youtube.py)**:
   - When query mentions "my favorites", "my liked songs", or "liked videos", directly open `https://www.youtube.com/playlist?list=LL` in the browser.
4. **Write Unit Tests in [`tests/test_youtube.py`](tests/test_youtube.py)**:
   - Test filtering of `/shorts/`.
   - Test filtering of videos < 60s.
   - Test "my liked songs" returns playlist URL.
   - Use mock HTML fixtures (never make live web requests during pytest).
5. **Verification Command**:
   ```powershell
   $env:RED_HOME="D:\RED"; $env:QT_QPA_PLATFORM="offscreen"; cd D:\RED\red; D:\RED\.venv\Scripts\python.exe -m pytest tests/test_youtube.py tests/test_stt.py -v
   ```
6. **Git Commit**:
   ```powershell
   cd D:\RED\red; git add red/stt.py red/tools/youtube.py tests/test_youtube.py; git commit -m "feat(youtube): filter Shorts, match query titles, and support liked songs playlist"
   ```

---

### Task 4: Build `notify_when_done` tool for VS Code & processes

#### Problem:
User says: "When VS Code finishes, remind me" or "Tell me when the build is done". Currently Red has no tool to watch windows or processes.

#### Implementation Steps:
1. **Create [`red/tools/watch.py`](red/tools/watch.py)**:
   - Tool signature: `notify_when_done(app_name: str, target_text: str = "") -> str`.
   - Reads target window title and OCR text using `red/screen.py` (`read_screen` or window grab).
   - Polls every 15 seconds in a background thread or timer.
   - Completion conditions:
     - Target text appears ("finished", "done", "completed", "exit code 0", or `target_text`).
     - Screen text stops changing for 2 continuous minutes.
     - Maximum timeout: 3 hours.
   - When completed: announces aloud via `VoiceApp.announce(...)` and shows Windows notification.
   - Add `cancel_watch(app_name: str)` to cancel watching when user says "stop watching".
2. **Fix `set_reminder` in [`red/tools/reminders.py`](red/tools/reminders.py)**:
   - If user didn't specify a time, do NOT invent "00:00". Instead return a response asking "When should I remind you?".
3. **Register Tool**:
   - Register in [`red/tools/__init__.py`](red/tools/__init__.py) and `default_registry()`.
   - Add routing descriptions in [`red/router.py`](red/router.py).
4. **Write Unit Tests in [`tests/test_watch.py`](tests/test_watch.py)**:
   - Test detection of "finished", timeout limit, cancellation, and router tool call creation.
5. **Verification Command**:
   ```powershell
   $env:RED_HOME="D:\RED"; $env:QT_QPA_PLATFORM="offscreen"; cd D:\RED\red; D:\RED\.venv\Scripts\python.exe -m pytest tests/test_watch.py tests/test_reminders.py tests/test_router.py -v
   ```
6. **Git Commit**:
   ```powershell
   cd D:\RED\red; git add red/tools/watch.py red/tools/reminders.py red/tools/__init__.py red/router.py tests/test_watch.py; git commit -m "feat(tools): add notify_when_done window watcher and reminder validation"
   ```

---

### Task 5: Multi-turn debates and back-and-forth talk

#### Problem:
User says: "Let's have a debate" or "Quiz me". Currently Red answers with 1 sentence and goes quiet.

#### Implementation Steps:
1. **Router Updates in [`red/router.py`](red/router.py)**:
   - Route requests containing "debate", "quiz me", "discuss" to `Chat` mode rather than one-shot `answer`.
2. **Debate Mode in [`red/chat.py`](red/chat.py)**:
   - Add state: `is_debate: bool = False`, `debate_topic: str = ""`.
   - When initiated, Red picks a side and topic if not given by the user.
   - Formulates a 2 to 3 sentence punchy argument.
   - Always finishes its turn with: `"Your turn."`
   - Sets follow-up silence listening timeout to 15 seconds (longer than default).
   - Ends the session when user says "stop", "I give up", "you win", or upon timeout.
3. **Write Unit Tests in [`tests/test_chat.py`](tests/test_chat.py)**:
   - Test multi-turn transitions with mock LLM responses.
   - Test debate exit triggers ("stop", "you win").
4. **Verification Command**:
   ```powershell
   $env:RED_HOME="D:\RED"; $env:QT_QPA_PLATFORM="offscreen"; cd D:\RED\red; D:\RED\.venv\Scripts\python.exe -m pytest tests/test_chat.py tests/test_router.py -v
   ```
5. **Git Commit**:
   ```powershell
   cd D:\RED\red; git add red/chat.py red/router.py tests/test_chat.py; git commit -m "feat(chat): add interactive multi-turn debate and discussion mode"
   ```

---

### Task 6: The Red App (PySide6 Setup Wizard & Settings Window)

#### Problem:
Setting up and configuring Red via command-line `.env` editing is daunting for regular users. We need a clean PySide6 window (`python -m red app`).

#### Implementation Steps:
1. **Create Package [`red/app/`](red/app/)**:
   - `red/app/__init__.py`
   - `red/app/main_window.py` (QMainWindow)
   - Pages / Tabs:
     1. **Hardware Check**: Shows detected CPU, GPU, VRAM, RAM via `red/hardware.py`.
     2. **Model Status**: Download status of LLM (Ollama), Whisper, Kokoro/Piper models with progress indication.
     3. **Audio Setup**: Dropdown to select input microphone device with real-time level meter test.
     4. **Voice Settings**: Dropdown for TTS engine (`kokoro` / `piper`), voice picker (`af_heart`, etc.), speed slider (0.7 - 1.5).
     5. **General Settings**: Hotkey trigger, overlay style (`glow` / `card` / `off`).
2. **Configuration Persistence**:
   - "Save Settings" reads inputs and updates `RED_HOME\config\.env` cleanly without overwriting comments or unmanaged keys.
3. **CLI Entrypoint in [`red/__main__.py`](red/__main__.py)**:
   - Add sub-command `python -m red app` to launch the application.
4. **Offscreen Testability in [`tests/test_app.py`](tests/test_app.py)**:
   - Ensure widgets instantiate and operate properly when `$env:QT_QPA_PLATFORM="offscreen"`.
5. **Verification Command**:
   ```powershell
   $env:RED_HOME="D:\RED"; $env:QT_QPA_PLATFORM="offscreen"; cd D:\RED\red; D:\RED\.venv\Scripts\python.exe -m pytest tests/test_app.py -v
   ```
6. **Git Commit**:
   ```powershell
   cd D:\RED\red; git add red/app/ red/__main__.py tests/test_app.py; git commit -m "feat(app): add PySide6 graphical setup and settings wizard"
   ```

---

## Final Verification (Run After All Tasks Complete)

When all tasks 2-6 are completed, run the entire project test suite:
```powershell
$env:RED_HOME="D:\RED"
$env:QT_QPA_PLATFORM="offscreen"
cd D:\RED\red
D:\RED\.venv\Scripts\python.exe -m pytest -q --basetemp=D:\RED\cache\pytest-tmp
```
**Goal:** 1,350+ passing tests, 0 failures.

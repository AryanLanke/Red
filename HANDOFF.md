# HANDOFF — Red Voice Assistant

> **Created:** 2026-11-10 by Antigravity (Claude Opus 4.6)
> **For:** DeepSeek v4.1 Flash (or any successor agent)
> **Project:** Red — a local, offline voice and action assistant for Windows 11
> **Repo root:** `D:\RED\red\` (this is the git repo; `D:\RED\` is RED_HOME)

---

## What Is Red?

Red is "Hey Siri but local." The user says "Hey Red" or presses Ctrl+Alt+R, Red listens (Whisper STT), thinks (Qwen3.5 4B via Ollama), acts (17 tool modules), and speaks back (Piper/Kokoro TTS). Everything runs offline on Windows 11 — no cloud, no subscription.

**Hardware:** AMD Ryzen 7 7735HS, RTX 4050 (6GB VRAM), 16GB RAM, Python 3.11.9

---

## Current Git State (branch: main)

**Last commit:** `b71bce3` — "Fact questions skip the model's routing; comparisons fetch alongside"

### Uncommitted Changes (NOT staged, NOT committed)

The previous agent was integrating **Kokoro TTS** (a more natural-sounding voice engine using Kokoro-82M ONNX). The work is substantially complete but was never committed. Here's exactly what's in the working tree:

| Status | File | What Changed |
|--------|------|-------------|
| Modified | `red/__main__.py` | Changed speaker creation from direct Piper → `make_speaker(settings)` which uses Kokoro with Piper fallback |
| Modified | `red/config.py` | Added 3 new settings: `tts` ("kokoro"/"piper"), `voice` ("af_heart"), `voice_speed` (0.7–1.5) |
| Modified | `red/doctor.py` | Added Kokoro voice model health check in `check_voice_models()` |
| Modified | `red/voice_setup.py` | Uses Kokoro speaker instead of plain Piper for voice enrollment |
| Modified | `tests/test_doctor.py` | Updated expected check count to include Kokoro WARN |
| **New** | `red/tts_kokoro.py` | Complete Kokoro TTS engine (262 lines): KokoroEngine, KokoroSpeaker, phonemization via espeak, Piper fallback, 27 English voices |
| **New** | `red/kokoro_vocab.json` | Kokoro phoneme vocabulary (114 entries) |
| **New** | `tests/test_tts_kokoro.py` | Full test suite (213 lines): 13+ tests covering synthesis, fallback, settings, download, phonemes |

### What's Left to Finish the Kokoro Integration

1. **Update `.env.example`** — Add `RED_TTS`, `RED_VOICE`, `RED_VOICE_SPEED` with descriptions
2. **Update `README.md`** — Mention Kokoro as the default voice engine, how to switch to Piper
3. **Update `AGENTS.md`** — Add Kokoro module to the developer guidance
4. **Update `CHANGELOG.md`** — Add Kokoro TTS entry
5. **Wire `red setup` to download Kokoro files** — Check if `_setup_voice()` in `__main__.py` calls `KokoroSpeaker.download()`. The download method exists in `tts_kokoro.py` but may not be called during `python -m red setup`
6. **Run the full test suite** — `RED_HOME=D:\RED QT_QPA_PLATFORM=offscreen timeout 300 D:\RED\.venv\Scripts\python.exe -m pytest -q --basetemp=D:\RED\cache\pytest-tmp`
7. **Commit everything** — `git add -A && git commit -m "feat: Kokoro TTS — more natural voice with Piper fallback"`

---

## Remaining Tasks (from plan.md)

These are the 7 planned tasks. Tasks 1 and 7 are done. The Kokoro TTS integration (above) is a bonus task the agent added.

### Task 2 — "Open YouTube" shows blank page
- **Problem:** When the user says "Open YouTube", the browser opens but shows a blank page
- **Action:** Reproduce the bug, trace through `red/tools/apps.py` and `red/tools/web.py`, fix URL handling
- **Difficulty:** Easy-medium

### Task 3 — Play the right song
- **Problem:** "Play [song name]" should play the correct song on YouTube, not Shorts
- **Action:** Improve YouTube search/play in `red/tools/youtube.py` — better vocabulary, skip Shorts, use YouTube suggestions
- **Difficulty:** Medium

### Task 4 — "Tell me when VS Code finishes"
- **Problem:** Need a new `notify_when_done` tool that watches a process and notifies the user
- **Action:** Create new tool module, register it
- **Difficulty:** Medium

### Task 5 — Debates and back-and-forth talk
- **Problem:** Red should support multi-turn debates/discussions
- **Action:** Modify conversation flow in `red/router.py` and `red/llm.py`
- **Difficulty:** Hard

### Task 6 — The Red App (PySide6 GUI)
- **Problem:** Need a setup wizard and settings window using PySide6
- **Action:** Create GUI application, integrate with existing config
- **Difficulty:** Hard

---

## Key Architecture Reference

```
D:\RED\                          # RED_HOME
├── red\                         # GIT REPO (cd here to work)
│   ├── red\                     # Main Python package
│   │   ├── __main__.py          # Entry point, CLI, VoiceApp class (1036 lines)
│   │   ├── config.py            # Settings dataclass, env loading (276 lines)
│   │   ├── doctor.py            # Health checks: ollama, whisper, piper, kokoro (385 lines)
│   │   ├── tts.py               # Piper TTS engine (Speaker class) — the fallback
│   │   ├── tts_kokoro.py        # Kokoro TTS engine (NEW, 262 lines)
│   │   ├── router.py            # Intent routing via LLM
│   │   ├── llm.py               # LLM backends (Ollama)
│   │   ├── executor.py          # Action execution
│   │   ├── voice_setup.py       # "Hey Red" wake word enrollment
│   │   ├── kokoro_vocab.json    # Phoneme vocabulary (NEW)
│   │   └── tools/               # 17 tool modules
│   │       ├── base.py          # Tool base class
│   │       ├── system.py        # OS commands
│   │       ├── web.py           # Browser/URL
│   │       ├── apps.py          # Application launching
│   │       ├── youtube.py       # YouTube playback
│   │       ├── gmail.py         # Gmail integration
│   │       ├── calendar.py      # Calendar
│   │       ├── git_sync.py      # Git operations
│   │       └── ...              # more tools
│   ├── tests/                   # 59 test files
│   ├── README.md                # User docs (307 lines)
│   ├── AGENTS.md                # Developer guidance (104 lines)
│   ├── CHANGELOG.md             # Release notes draft
│   ├── plan.md                  # Task backlog (301 lines)
│   ├── progress.md              # Full dev history (1498 lines)
│   ├── pyproject.toml           # Package config
│   └── .env.example             # All RED_* settings template
├── .venv\                       # Python 3.11.9 venv
├── bin\                         # Ollama v0.40.11
├── models\                      # LLM, Whisper, Piper, wakeword models
├── config\                      # .env, allowlist.toml, repos.toml
├── logs\                        # red.log, commands.jsonl
├── searxng\                     # Local SearXNG instance
└── worktrees\                   # Git worktrees (a, b, c) — all clean/merged
```

---

## How to Run

```powershell
# Activate venv
D:\RED\.venv\Scripts\Activate.ps1

# Run Red (voice mode)
cd D:\RED\red
python -m red

# Run Red (typed mode for testing)
python -m red --typed

# Run doctor (health check)
python -m red doctor

# Run tests
$env:RED_HOME="D:\RED"
$env:QT_QPA_PLATFORM="offscreen"
cd D:\RED\red
D:\RED\.venv\Scripts\python.exe -m pytest -q --basetemp=D:\RED\cache\pytest-tmp

# Run specific test file
D:\RED\.venv\Scripts\python.exe -m pytest tests/test_tts_kokoro.py -v
```

---

## Important Guidance

1. **Read `AGENTS.md` first** — it has developer rules: test before commit, no placeholders, keep voice latency under 400ms
2. **Read `plan.md`** for task details — each task has acceptance criteria
3. **Read `progress.md`** for historical context on design decisions
4. **All work happens in `D:\RED\red\`** (the git repo directory)
5. **The worktrees (`D:\RED\worktrees\a,b,c`) are done** — don't touch them
6. **Tests must pass before committing** — the test suite is comprehensive (59 files)
7. **The `.env` file is at `D:\RED\config\.env`**, not in the repo. `.env.example` in the repo is the template

---

## Priority Order for DeepSeek

### Immediate (finish what was started):
1. Finish Kokoro TTS integration (update .env.example, README, AGENTS.md, CHANGELOG)
2. Run tests, fix any failures
3. Commit the Kokoro work

### Then (from plan.md):
4. Task 2 — Fix "Open YouTube" blank page
5. Task 3 — Fix song playback
6. Task 4 — Build notify_when_done tool
7. Task 5 — Multi-turn debates
8. Task 6 — PySide6 GUI

---

## Tips for DeepSeek

- The codebase is clean (no TODOs/FIXMEs). Keep it that way.
- Every module has corresponding tests in `tests/`. Follow the pattern.
- `red/tts.py` is the original Piper engine; `red/tts_kokoro.py` is the new one. Kokoro wraps Piper as fallback.
- The `Speaker` base class is in `red/tts.py`. `KokoroSpeaker` inherits from it.
- Config settings use `RED_` prefix env vars: `RED_TTS`, `RED_VOICE`, `RED_VOICE_SPEED`.
- The project uses piper-tts's bundled espeak-ng for phonemization — no additional native DLLs needed.
- Kokoro model files: `kokoro-v1.0.int8.onnx` (88MB), `voices-v1.0.bin` (27MB) — pinned by SHA-256 in `tts_kokoro.py`.

# AGENTS.md

**Start here:** read [plan.md](plan.md) first. It lists the next tasks in order and the rules for working on Red. Then read [docs/architecture.md](docs/architecture.md): how Red is built (parts, event bus, companions, avatars, wake names, speech tags, hardware tiers, settings registry, shipping, testing). Build to it, and update it in the same commit when a design changes.

Red is a local companion for Windows: a friend with a personality that lives on the PC, remembers the user, and does their work (apps, files, mail, code), growing through plugins. A local LLM turns a command into one JSON tool call, and Red validates it before anything runs.

- [progress.md](progress.md) is the developer document: status, specs, decisions and open questions. Follow its specs and safety rules when building a feature, and keep its status up to date.
- [README.md](README.md) is for users. Keep it free of developer planning.

**Status:** Days 1 to 5 are merged into one app: the Phase 1 tracks A, B and C, then Track D's integration. `python -m red` runs the full voice loop:
1. the hotkey or the wake word
2. recording
3. Whisper
4. the router
5. spoken confirmation for destructive tools
6. the action
7. Spoken reply (Kokoro TTS, or Piper fallback)

The overlay shows each step. All the parallel tracks are merged; work happens on `main`.

## Commands

Windows and PowerShell only. Python 3.11 or newer.

On this machine `RED_HOME` is `D:\RED`, the venv is `D:\RED\.venv`, and the repo is `D:\RED\red`. Set `$env:RED_HOME = "D:\RED"` first; otherwise Red uses `%LOCALAPPDATA%\Red` and downloads a second copy of Ollama and the model (about 6 GB).

```powershell
pip install -r requirements-dev.txt   # core + requirements-voice.txt + requirements-ui.txt + pytest
$env:QT_QPA_PLATFORM = "offscreen"     # overlay tests without a window
python -m pytest --basetemp="$env:RED_HOME\cache\pytest-tmp"            # unit tests (integration tests are skipped)
python -m pytest tests\test_router.py::test_shutdown_is_destructive    # one test
$env:RED_INTEGRATION = "1"; python -m pytest tests\test_integration_llm.py tests\test_integration_c_tools.py tests\test_voice_models.py   # real models, slow

python -m red setup                   # Ollama, the LLM, Whisper, Piper and the wake word; copies the allowlist, repos and contacts examples
python -m red doctor                  # read-only checks with fixes (red/doctor.py; starts nothing)
python -m red startup on|off          # sign-in shortcut (red/startup.py); --home sets RED_HOME for one run
python -m red                         # voice loop with the overlay (Ctrl+C quits)
python -m red --typed                 # typed loop that runs actions
python -m red --dry-run               # typed loop that only shows tool calls
python -m red run "open Downloads"    # run one command
python -m red route "open Downloads"  # print the tool call for one command
python -m red.overlay                 # overlay demo through every state
python -m red wake-test               # 30 s of live "Hey Red" checks: words heard, score, loudness
python -m red plugins list            # plugins, on or off, and why one was skipped (on NAME / off NAME)
```

There is no build step, linter or formatter set up. Dependencies are pinned exactly in `requirements*.txt`.

## Architecture

The flow in `red/__main__.py`: `load_settings()` → `llm.connect(settings)` → `Router(default_registry(), llm)`. Then, by mode:
- **Voice (the default):** `run_with_overlay(worker)` gives Qt the main thread. The worker builds a `VoiceApp`, which starts a `Listener`: the hotkey plus the wake word, or the hotkey only if the wake word fails. Each trigger runs `VoiceApp.handle()` on the listener's thread, with `overlay.set_state()` at each step:
  1. `chime()` and `record_command()`
  2. `Transcriber.transcribe()`
  3. `router.route()`
  4. `Executor.execute()`
  5. `Speaker.say()`
- **Typed, `run`, `--dry-run` and `route`** need no voice packages and no Qt.

The voice and UI modules are imported lazily, through `load_voice()` and inside functions, so the core and its tests work without them. `VoiceApp` takes every part in its constructor (`Voice`, the overlay, the typed fallback), and `tests/test_voice_app.py` drives it with fakes.

- **Tools** (`red/tools/`): each one subclasses `Tool` and has `name`, `description`, `args_schema` and `destructive`. Register it in `default_registry()` in `tools/__init__.py`. The `description` and `args_schema` are inserted directly into the LLM's system prompt, so their wording changes routing. The schema bounds are also the safety limits; for example, `MAX_DELAY_MINUTES` caps shutdown delays. `none` is a reserved pseudo-tool for "no tool fits" (its args are `{"reply": ...}`), and the registry rejects a tool with that name.
- **Router** (`red/router.py`): `route()` tries `red/fastpath.py` first, then the model. `route_many()` splits "mute and lock the PC" (`split_commands`: "and", "then" or a comma before a command word, up to 4 parts) and routes each part; if any part is chat, it routes the whole sentence instead. `VoiceApp._run_steps` runs the parts in order and stops at the first error or "no". The router builds an `anyOf` JSON schema from the registry. The backend uses it to constrain generation, and `Router.parse()` checks it again with `jsonschema`, because a server may ignore the schema. `parse()` needs no LLM, so most router tests call it directly.
- **LLM backends** (`red/llm.py`): every client implements the `LLM` protocol (`complete_json(system, user, schema) -> str`). `connect()` tries them in this order:
  1. `RED_LLM_URL` (any OpenAI-compatible server)
  2. An Ollama already running on `127.0.0.1:11434`
  3. Red's own pinned Ollama
  4. With `RED_LLM_BACKEND=auto`, a llama.cpp `llama-server` as a fallback

  Ollama receives the schema as `format`. OpenAI-compatible servers receive it as `response_format` json_schema. Model names map to an Ollama tag and Hugging Face GGUF files in `MODELS`. The default is `qwen3.5-4b` (`DEFAULT_MODEL` in `red/config.py`); `python -m red setup` picks one for the PC with `red/hardware.py`. A `ModelSpec` with `thinking=True` (Qwen3.5) always gets thinking turned off (`"think": false`), and one with `vision=True` gets a screenshot from `describe_screen`.
- **Pinned downloads** (`red/llm.py` and `red/downloads.py`): every binary and GGUF is pinned to a version and a SHA-256. If you change a version, update its hash. A download is written to `.part` and moved to its final path only after the checksum matches, so an existing file there is always verified. Installs write an `.installed` marker. Zips go through `safe_extract`, which blocks paths that would escape the target folder.
- **Child servers** (`red/process.py`): `ManagedServer` starts a backend inside a Windows Job Object set to kill on close, so Ollama and its model runner die with Red, even after a crash. Whoever calls `connect()` owns the returned server and must `stop()` it in a `finally` block.
- **Config** (`red/config.py`): all paths come from `Settings`, which is built on `RED_HOME`. Never hard-code a path. Environment variables win over `RED_HOME\config\.env`. `RED_HOME` itself is only read from the environment. Every `RED_*` setting is a `Settings` field and is listed in `.env.example`. The paths are `allowlist_path`, `repos_path` and `command_log_path`.
- **Executor** (`red/executor.py`): asks through `confirm()` before a destructive tool, runs the tool, and writes one line to `logs\commands.jsonl`. A `ToolError` message becomes the reply; any other exception becomes a short apology. A tool's `last_details` (for example, one line per repo) goes into `Executor.last_details`, and from there to the overlay and the log.
- **Confirmation** (`red/confirm.py`): `Ask = (question, timeout) -> answer | None`. `typed_ask` reads the console with a timeout; `voice_confirm.spoken_ask` speaks the question and transcribes the answer. `with_fallback(spoken, typed_ask)` switches to typing only if the spoken ask raises. `is_yes` is the only yes check.
- **Voice** (`red/audio.py`, `stt.py`, `tts.py`, `listener.py`, `voice_confirm.py`):
  - recording with sounddevice, stopping on silence
  - faster-whisper, loaded once (`RED_WHISPER_DEVICE=cpu` by default)
  - Piper for speech
  - a pynput hotkey, and the wake word on its own thread

  The `Listener` calls `on_trigger` on one worker thread and pauses the wake word while it runs, except while Red talks: `VoiceApp` calls `listener.allow_interrupt(True)` then, and "Hey Red" or the hotkey calls `VoiceApp.interrupt()`, which stops the speech and listens for the next command. Models are pinned (`PinnedFiles`) under `RED_HOME\models\{whisper,piper,wakeword}`.
- **Voice match** (`red/voice_match.py`): with `RED_VOICE_MATCH=on` and a profile from voice-setup, `HeyRedDetector` checks the voice of each clip whose words matched (CAM++ ONNX speaker embedding on onnxruntime, numpy fbank, cosine against the owner's average). Not the owner: the score becomes 0 and Red stays silent. The hotkey never goes through it. A failing model lets the clip through rather than lock the owner out.
- **Speaking while the model writes** (`red/speech.py`): `VoiceApp` opens a `SpeechStream` for each command and makes it current on its thread (`speaking_to`). `ask_model` (answer, look_up, describe_screen) and `Chat.reply` then call the client's `stream_json`, read the JSON string field as it arrives (`JsonFieldReader`), cut it into sentences, and `SpeechStream.say()` each one; Piper makes the next sentence while the last one plays. The tool still returns the whole text, so the log and memory don't change. Clients and fakes without `stream_json`, and typed mode (no stream), work as before.
- **Reminders:** `attach_reminders()` in `__main__.py` sets `red.scheduler.default_scheduler().on_due` behind a try-import. In voice mode, `VoiceApp.announce()` waits for the current command (`_turn` lock), pauses the wake word and speaks; typed mode prints.
- **Doctor** (`red/doctor.py`): each check takes a `System` of injected functions (package lookup, HTTP, subprocess, sounddevice), so `tests/test_doctor.py` needs no hardware.
- **Bringing windows to the front** (`red/windows.py`): `open_app`, `open_folder`, `open_url`, `web_search` and `play_online` call `watch(target)` before launching (a snapshot of the top-level windows), then hand the watcher to `Tool.finish_later()`. While Red speaks, it waits up to 5 s for the new window (by pid, exe or title; browsers may reuse an existing window) and fronts it with `AttachThreadInput`, then the Alt-key trick. `tests/conftest.py` swaps `watch` for a no-op in every test.
- **Gmail and Calendar** (`red/google_auth.py`, `red/tools/gmail.py`, `red/tools/calendar.py`): registered by `default_registry()` only when `RED_HOME\config\google-token.json` exists. Plain urllib to fixed `googleapis.com` addresses (`GoogleApi` refuses others), PKCE loopback sign-in, the access token refreshed from the stored refresh token. `send_mail`, `reply_mail` and `calendar_cancel` are destructive (read back once, the user's choice); they check their arguments in `prepare()`, which the Executor calls before asking, so an unknown recipient fails without a question. Tests use a fake API (`tests/test_google.py`).
- **Look-up sources** (`red/tools/sources.py`): `look_up` asks Wikipedia and the web at the same time (`Gather`, 6 s budget) and answers first, then cites (`cross_check_system`). The web is a SearXNG on this PC, searched with the user's own words; the top three pages are read (`read_top_pages`), one page per site, no videos or social posts. `search_url()` accepts only loopback `RED_SEARCH_URL` addresses. "I'm searching." is said once Wikipedia has answered; offline (`Offline` from Wikipedia) the model answers from its own knowledge at once. DuckDuckGo instant answers, arXiv and Wikidata were tried and left out (see the module docstring).
- **Red's own SearXNG** (`red/searxng.py`): `python -m red setup` downloads a pinned commit (SHA-256), unpacks only `searx/`, `requirements.txt` and `LICENSE`, patches `pwd` for Windows, and makes its own venv under `RED_HOME\searxng\red-<commit>`. Voice, background and typed mode start it in a thread (`WebSearch`) on a free port as a `ManagedServer` and set `RED_SEARCH_URL` for this process; if it fails, Red carries on with Wikipedia only. `RED_WEB_SEARCH=off` turns it off; a user's own `RED_SEARCH_URL` wins. `tests/conftest.py` replaces `start` and `install`, so no test downloads or starts it.
- **Personality and memory** (`red/chat.py`, `red/memory.py`, `red/tools/memory.py`): `make_chat(llm, settings)` builds the Chat both loops use. Its system prompt is the fixed `CHAT_SYSTEM`, then the user's `config\personality.txt`, then the profile from `RED_HOME\memory\profile.md` (fixed part first, for Ollama's prompt cache). The facts that share the most words with the sentence go into the chat prompt. A `Learner` thread pulls facts from chats once Red has been quiet for 20 s. `bind_conversation` hands the memory to the `remember`, `what_you_know` and `forget` tools. Tests never touch the real memory (`tests/conftest.py`).
- **Plugins** (`red/plugins.py`): `default_registry()` adds the tools of every plugin that's on, from `red/plugins/<name>/` (Red's own; never give that folder an `__init__.py`) and `RED_HOME\plugins\<name>\` (`plugin.toml` + `tools.py`). A broken plugin is skipped and logged, never fatal. `python -m red plugins list`. New features that can be turned off go in as plugins.
- **Greetings and the chat window** (`red/greeter.py`, `red/chat_window.py`): `VoiceApp.run` starts both. The greeter says hello at the start of the day and after 30+ minutes away (`RED_CHATTINESS`), never queued behind a command (`VoiceApp.greet`). The chat window (Ctrl+Alt+Space, or the `open_chat` tool) shares the voice loop's `Chat`. Typed turns run through `typed_turn`, and spoken ones are mirrored from `VoiceApp.out` lines. `tests/conftest.py` stops both from starting in tests.
- **Overlay** (`red/overlay.py`): PySide6, frameless, click-through and never focused. `set_state()` is safe to call from any thread. If Qt can't start, Red falls back to Windows toast notifications.
- **Companion** (`red/avatar/`, the default `RED_OVERLAY=companion`): a character peeking from a bottom corner, over the bottom edge or hanging upside down from the top edge or a top corner (`topL_*`, `topR_*`: the bottom-corner poses turned over, cut at the top and side edges; `add.py --sets topL,topR` adds them to an existing companion), from 2D frames pre-rendered out of a VRM (`scripts/avatar_render`, `add.py` for a new model; run from PowerShell: headless Edge exits silently under Git Bash). Frames live in `RED_HOME\models\companion\<id>\` (peek_*, cornerR_*, cornerL_*, top_*, topL_*, topR_*, body_*; frames.json with name, voice, head and hand marks); any such folder is a companion (`available_companions`); without one `_start_qt` shows the glow. `pick_frame()` picks a peek_* frame and `frame_for_side()` turns it into the corner's. `pick_frame()` turns state, emotion (guessed from the reply by `emotion_from_text` until speech carries tags) and the voice loudness (`MouthMeter`, wrapped around the speaker's player by `attach_speaker`) into a frame. The window takes the mouse (only the character's pixels, as a layered window): hover, click opens the chat, drag picks it up (body frames, swing, a Kokoro "whoa!" clip, gravity back to the edge). Left alone it has an idle life (`red/avatar/idle.py`, played by the window): `look_left`/`look_right`/`look_up`, `yawn`, `stretch`, `sleepy`, `bored` frames for every placement, hop-walks along the edge, doze, a move to another corner; lane 2's `idle_action` events say when, and without them the window's own timer does (the companion's `[idle]` switches apply). `add.py --only` adds frames to an existing companion with the old crop. Right-click is a Desktop Mate-style menu (`build_menu`): talk, reminder, task, to-do list, play music, move, switch companion, size, sleep, quiet mode, microphone, settings, hide, quit. Its back end is `red/avatar/actions.py` (reminders through the scheduler, tasks in `RED_HOME\memory	asks.json`), the dialogs are `red/avatar/dialogs.py` (frameless, glow look), and `red/avatar/wiring.py` connects it to the voice loop. Tests drive it offscreen with a fake clock and `play_clip` patched out.

## Rules that come from the design

- A tool must never pass LLM text to a shell or command line. App and folder names are only lookup keys into Windows' standard folders or `RED_HOME\config\allowlist.toml`. If nothing matches, say so instead of guessing.
- `destructive = True` tools (shutdown, restart, anything that changes files) must get a clear yes, typed or spoken, before they run (`confirm.is_clear_yes`: "yes", or "yeah, go ahead" with no no-word in it). A no-word anywhere ("no", "don't", "stop", "cancel"), an unclear answer like "okay", or 30 seconds with no answer cancels. Harmless tools never ask, even for "can you ...?". `cancel_shutdown` never asks.
- Tests must never open windows, use the microphone or speakers, hook the keyboard, or schedule a real shutdown. Inject fakes through constructors, and follow the existing test patterns:
  - `FakeLLM` in `tests/test_router.py`
  - `FakeRunner`, `FakeStartfile`, `FakePopen` and `FakeAsk` in `tests/fakes.py`, and the voice fakes in `tests/voice_fakes.py`
  - `monkeypatch` to clear `RED_*` variables, with `load_settings(tmp_path)`
  - `monkeypatch` on `llm.start_ollama` / `llm.start_llama_server`
- The wake phrase is "Hey Red" (`RED_WAKEWORD=hey_red`). Never use "Jarvis" as a wake word, default, prompt or user-facing text.
- Red never calls a cloud model. Voice, screen and the AI stay on the PC. Red talks only to accounts the user signs into through Red: Google (after `python -m red google-login`, `red/google_auth.py`: mail and calendar text for the Gmail and Calendar tools) and plugins such as Spotify or other mail. Each service gets only what it needs. Tokens are encrypted with DPAPI and never go into git. Trading and financial automation are out of scope.
- Windows Smart App Control blocks unsigned binaries. Exit code `0xC0E90002` from llama-server means it was blocked; Ollama is the default for this reason.

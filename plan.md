# Red: what to do next

Updated 2026-11-13. The first three plans are done: see `git log` and progress.md. The fourth plan
below comes from the user's feedback on 2026-11-13.

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

## Done in the second and third plans

Second plan (2026-11-09): browser fix, follow-ups and a Whisper vocabulary, YouTube play, Qwen3.5 4B,
the fast path, speaking while the model writes, Gmail and Calendar, voice match (off by default), several
commands in one sentence. Third plan (2026-11-09 to 11-12): Kokoro TTS, wake fixes and `red wake-test`,
"open YouTube", the right song, `notify_when_done`, debates, the Red app wizard (`red/app/`), web search
with Red's own SearXNG. Details: `git log` and progress.md 7.

## Tasks, in order (fourth plan, 2026-11-13)

From the user's feedback on 2026-11-13: "Hey Red" wakes about 1–2 times in 100; Red should be on whenever
the PC is; the laugh clips sound pasted on and Red feels cold next to Hey Copilot; then a male voice, a
one-click installer and a desktop companion. **Ship every commit to `main` on its own** (many small
commits, each pushed right away).

### 0. ✅ Clean-up (2026-11-13)
Deleted the stale handoff docs (AUTONOMOUS_TASKS, QODER, DEEPSEEK_INSTRUCTIONS, HANDOFF) and
`red/voice_demo.py`; cut progress.md's parallel-sessions history (now `git show 94c6cae:progress.md`);
removed the three merged worktrees and every merged `track-*` branch, local and on GitHub; cleared old
pytest folders, scratch files, `kokoro-spike` and the pip cache from `RED_HOME\cache`. Kept
`cache\voice-samples` (Kokoro voice comparisons, for task 4) and `cache\train_hey_red` (for task 1.7).

### 1. "Hey Red" wakes 95 times in 100
**Why:** in `red.log`, 1,936 wake checks and only 22 scored above 0. Whisper writes the user's "Hey Red"
as "Headed", "Heading", "Hit it", "Here Red" or "Hey"; `match_score` rejects all of them. "Hey Red,
don't know" scores 0.45 (under 0.5). Many tries never reach Whisper (silent guards: 0.25 s pause before,
1.6 s cap, VAD start 0.5). The mic is quiet (23% of peaks under 0.05). Wake Whisper runs on the mic
thread (1.05 s average, 5.4 s max). `voice-setup` was never run. (The "Hey Copilot" lines at 04:44–04:48
on 2026-11-13 were the user trying Copilot: not misses.)
1. **A real corpus first.** `red wake-test --record`: the user says "Hey Red" 30 times, "Hey Red, open
   YouTube" 10 times, then talks normally for 2 minutes; labelled WAVs in `RED_HOME\cache\wake-corpus\`
   (never in git: it's their voice). `red wake-test --replay` runs the whole detector over it and prints
   hits and false wakes. Target: **≥ 95% hits, no false wakes on the talk.** Every step below is judged
   on it.
2. Log every guard's rejection in `HeyRedDetector._step` (no pause before, too long, too short, VAD).
3. `match_score`: "Hey Red" at the start of the clip plus more words scores 1.0, and those words become
   the command (no second recording). Keep the guard against "a red light".
4. Personal spellings through `voice-setup` (`red/voice_setup.py`), run with the user now and part of the
   first-run wizard: "Headed" or "Hit it" wake for this user only.
5. Looser guards, each measured: pause before ~0.1 s, always check the first 1.3 s of a long burst, VAD
   start ~0.35, loudness normalised before Whisper.
6. Wake checks on their own worker thread, off the mic thread; `beam_size=1` if the corpus allows.
7. Only if 3–6 miss 95%: retrain the openWakeWord model (`scripts/train_hey_red/`) with Kokoro's
   Indian-English voices and the user's clips, as a fast first stage that triggers a Whisper check.
- **Files:** `red/wakeword.py`, `red/wake_test.py`, `red/listener.py`, `red/voice_setup.py`,
  `red/__main__.py`, `tests/test_wakeword.py`.
- **Check:** unit tests with the logged transcripts; replay numbers before and after each step in
  progress.md; then the user's 100 tries by voice.

### 2. On whenever the PC is on, and ready fast
**Why:** the Startup shortcuts exist (`Red.lnk`, `Red Hotkey.lnk`; the hotkey is Ctrl+Alt+R), but a cold
start takes ~70 s, ~48 s of it Ollama's GPU discovery (the AMD iGPU's Vulkan check times out), close to
`start_ollama`'s 60 s limit.
1. Skip the iGPU discovery for Red's child Ollama (find the env var for the pinned version); wait up to
   120 s.
2. Load Whisper, Kokoro and the wake listener while Ollama starts; "Hey Red" and the hotkey work as soon
   as Whisper is up; a command before the model is ready gets "One sec, still waking up".
3. `Startup:` timing lines in `red.log`. Target: wake word live ≤ 15 s after logon, warm ≤ 30 s.
4. Watchdog in `red hotkey`: restart a crashed Red (at most 3 times an hour).
- **Files:** `red/llm.py`, `red/__main__.py`, `red/background.py`, `red/startup.py`.
- **Check:** a reboot with the timing lines; `taskkill` Red and see it come back.

### 3. No laugh clips; Red with taste on today's voice
1. Remove the laugh clips: revert `4f63934` (`red/laugh.py`, `red/assets/laugh/`, the speech and
   `__main__` changes, tests) and the laugh line in `CHAT_SYSTEM`.
2. Rewrite `CHAT_SYSTEM` (`red/chat.py`): a concrete character (dry humour, opinions, reacts before
   answering), with 4–6 short example exchanges that show taste. A light touch in `ANSWER_SYSTEM` too.
3. Pauses from punctuation instead of a flat 0.12 s: comma ~0.15 s, sentence ~0.3 s, "..." or a dash
   ~0.5 s; long sentences cut at commas so the intonation resets.
- **Check:** unit tests; 5 sample replies rendered to WAV for the user; first-word time unchanged.

### 4. A voice that really laughs and pauses (GPU), and a male voice
1. Spike first (`scripts/tts_bench.py`): local expressive TTS with laugh, sigh and pause tags (Chatterbox,
   Orpheus GGUF, Dia, Sesame CSM; check current versions and licences). On the user's GPU with the 4B
   model loaded: first audio ≤ ~1 s, VRAM, does a laugh sound real, licence, Smart App Control (ONNX or
   llama.cpp; no unsigned torch DLLs). Results table in progress.md; pick at most one.
2. The winner becomes an engine behind `make_speaker` (`red/tts_kokoro.py`), streamed like Kokoro;
   `RED_TTS=auto` uses it on a fitting GPU, else Kokoro, else Piper. Tags only for that engine (stripped
   for the others). Models pinned with SHA-256.
3. Male voice: a male/female choice with a Play sample button in the wizard and the Voice page
   (`red/app/pages.py`). Kokoro has `am_michael`, `am_puck`, `bm_george` and more; the expressive engine
   needs one too. The user picks by ear.

### 5. The glow (waiting for the user's design)
The edge glow (`red/overlay.py` `GlowWindow`) stays as it is until the user shares the design. Then build
it, render every state offscreen, look, and update `tests/test_voice_feel.py`.

### 6. One-click installer
`installer/build.ps1` bundles the python.org embeddable Python, the pinned wheels and `red`; Inno Setup
makes `Red-Setup.exe`: per-user install to `%LOCALAPPDATA%\Red` (no admin), `RED_HOME`, Start menu,
startup entries, uninstaller, then the first-run wizard (`red/app/`: hardware and model, downloads with
checksums, mic and level meter, voice-setup, male/female voice, web search, optional Google sign-in).
`install.ps1` does the same in one line. GitHub Releases with SHA-256 hashes; the README notes the
"unknown publisher" warning.
- **Check:** a clean Windows Sandbox or VM with Smart App Control on: download to a working "Hey Red"
  with no command line; the uninstaller leaves nothing.

### 7. Desktop companion (after the glow)
An original 2D mascot in a transparent, click-through PySide6 window in a corner: sleeps when idle,
perks up at "Hey Red", thinks, talks with its mouth moving to the TTS loudness. Optional, draggable, set
in the Red app. Show the user 2–3 sketches rendered offscreen before building.

**Needed from the user:** the wake corpus (~5 min) and the 100 tries (task 1), one reboot (task 2),
listening to samples and picking the male voice (tasks 3–4), the glow design (task 5).

## Speed plan: the first word in about a second (2026-11-11)

The user's test: answers "take a really large amount of time". The targets are already in "The
goal" above (a question or chat starts speaking in 1–2 s, an action is done in 1–3 s). This is the
plan to get there, in the order to do it. Measure with the `Timing` lines in `red.log`
(red/__main__.py:672) before and after every step, and never ship a step without numbers.

### Where the time goes (one command, from when you stop talking)

listen → transcribe (Whisper) → route → tool → speak.

1. **route** — `Router.route` (red/router.py:145) tries `red/fastpath.py` (regex, 0 s) first;
   everything else is one local-model call to Qwen3.5 4B writing a full JSON tool call.
2. **tool** — an action (open, volume, shutdown) is just the action. A question is a *second*
   model call: `answer` (red/tools/assistant.py) or `look_up` (red/tools/online.py), which also
   waits for SearXNG (budget 6 s, red/tools/sources.py:42) and reads up to 3 pages (1.5 s).
3. **speak** — Kokoro, streamed sentence by sentence (red/speech.py), so it overlaps the model.

So a question today is two full 4B generations in a row, plus a web search. That is the delay.

### The tasks, in order

1. **Numbers first.** Confirm the `Timing` lines land in `red.log` when Red runs hidden
   (`python -m red background`), and write down real first-word times for "open Edge", "what is a
   black hole" (answer), "who made Siri" (look_up), "weather in Pune", and one chat line.
   Everything below is judged against this table.

2. **Widen the fast path so routing is free.** `red/fastpath.py` already catches plain "what is X"
   (plan.md 7). Add the other common phrasings so they never pay for a routing call: "who is/was
   X", "when was X", "where is X", "how tall/big/far is X", "what does X mean", "how do I X" →
   straight to `answer`/`look_up` with the user's own words. Check against `commands.jsonl`:
   every sentence the fast path now answers must be one the model would have routed the same way.
   *Win: one whole 4B call off the front of every caught question.*

3. **One model call for a question, not two.** For `answer`, when the fast path already knows it
   is an `answer`, skip the router call and go straight to `Answer.run` (it only needs the
   question). `look_up` needs its topic extracted, but "who/what/where is X" gives it for free —
   same idea. The router's JSON call then remains only for sentences that genuinely need a tool
   choice. *Win: questions start speaking roughly one generation earlier.*

4. **Cut look_up's web wait.** SearXNG's two engines answered in 0.3–0.7 s warm (red/searxng.py),
   so the 6 s gather budget and 1.5 s page budget (red/tools/sources.py:42–47) are mostly
   headroom. Lower them to ~3 s and ~1.0 s; the page read already keeps the snippet when it misses
   its deadline. *Win: a slow lower site can no longer hold up the answer.*

5. **Cache the router prompt in Ollama.** The router system prompt (the whole tool list) is
   identical every call; only the command changes. Ollama 0.40 caches the prompt prefix, so the
   prefill is paid once per keep-alive. Check that `num_ctx=4096` fits it and that nothing varies
   the prefix between calls (red/llm.py:252). Noted in "Later" already; re-test with the pinned
   Ollama version. *Win: routing's time-to-first-token drops to near zero while the model stays
   loaded.*

6. **Route with a small model, answer with the big one.** Routing is classification; it doesn't
   need 4B. If steps 2–5 aren't enough, run a second, smaller model for routing (qwen3.5-2b, or
   qwen2.5-3b which measured 1.4 s a command on CPU in 2024, red/llm.py:148) and keep 4B for the
   answers. Needs both loaded (VRAM) or a fast swap. *Win: the routing generation itself gets
   2–4× faster for the commands that still use it.*

7. **The first spoken word.** The model is already kept loaded and primed (`keep_model_warm`,
   red/__main__.py:749) and TTS is streamed. If the step-1 numbers show the first sentence is slow
   after idle, the fix is preloading the Kokoro voice at startup and checking Ollama isn't
   unloading between the 240 s warm-ups. Whisper already reuses the pause-check transcript
   (red/__main__.py:434); if transcribe is a big slice, drop `small.en` → `base.en`.

### Definition of done

The step-1 table, re-measured after the work: "open Edge" in 1–3 s, a question or chat's first word
in 1–2 s, "play Believer" in 2–3 s — matching the targets in "The goal".

## Roadmap 2.0: shipping, personality and beating the competition

Merged from the user's plan2.md (2026-11-09). Do these after the tasks above, in the phase order at the end.

### Where Red lags and where it wins

| Competitor | Where they lead (Red lags) | Where Red wins |
|---|---|---|
| **Braina** | Big plugin ecosystem, Spotify, maths and dictation mode | Braina is paid, closed, cloud-dependent and stiff. Red is free, local, private, with modern LLMs. |
| **VoiceAttack** | Very reliable instant voice triggers, macros for games and apps | Rigid keywords, no conversation. Red understands natural speech. |
| **PyGPT** | Plugins, model switching, RAG on local documents | Feels like a workbench, not a daily voice companion. |
| **Desktop Mate (Steam)** | Charm: cute mascots on the desktop, high engagement | No intelligence, no PC control. Red has both. |
| **Copilot / Siri** | Pre-installed, zero setup, polished | Corporate tone, cloud-dependent. Red works offline (web search optional). |

### Gaps to close
1. **Setup:** Git, Python, venv, command line and 15 GB by hand. Goal: one-line PowerShell installer and a
   one-click `.exe`, with no Python needed by the user.
2. **Wake word:** reliable waking, no false wakes, the command in the same breath (task 1).
3. **Plugins:** a light structure for community tools (Spotify, media players, macros).
4. **Personality:** Siri, Copilot and ChatGPT Voice are sterile. Most assistants, and companion apps like
   Desktop Mate, have no real personality with brains behind it. Red's warmth and character are the edge.

### Personality and mascot
- **Persona modes:** Classic Companion (warm, casual, concise, like Windows XP's Rover), Witty / Banter
  (sharp, light teasing, never customer-service), Minimal / Focused (one-sentence confirmations for power
  users), and a custom system prompt in settings. Replaces "Personality: normal or opt-in casual" in Later.
- **Visual presence, light on GPU memory:**
  - Phase 1, the living indicator: the frosted milky-glass overlay breathes when idle, ripples when
    listening, glows in waves when speaking (replaces "a glow that reacts to the voice" in Later).
  - Phase 2, mascot skins: an optional corner companion (2D pixel-art or vector: a mini robot, a flame, a
    retro companion) that sleeps, perks up at "Hey Red", thinks and talks.
- Expressive start and stop chimes instead of system beeps.

### Shipping ($0 budget)
1. **One-line installer:** `irm https://raw.githubusercontent.com/AryanLanke/Red/main/install.ps1 | iex`.
   It brings a portable Python, downloads the pinned dependencies, runtimes and models (SearXNG included,
   task 7), sets `RED_HOME`, and makes shortcuts and the startup entry.
2. **`Red-Setup.exe`** with Inno Setup or PyInstaller: Start menu entry, microphone test, then the
   first-run window. Without a code-signing certificate, Windows warns about an unknown publisher.
3. **Free channels:** GitHub Releases (with SHA-256 hashes), a GitHub Pages site
   (`aryanlanke.github.io/Red`), `winget` (`winget install AryanLanke.Red`), itch.io, and SourceForge.

### Phases
- **Phase 1, core reliability:** tasks 1–5 and 7 above.
- **Phase 2, personality and mascot:** persona switcher in `red/chat.py`; chimes; the PySide6 state widget
  and optional mascot.
- **Phase 3, plugins:** a drop-in folder `RED_HOME\plugins\`; tools as plain Python files with the standard
  `Tool` schema; Spotify control (media keys first).
- **Phase 4, public release:** `install.ps1`, the GitHub Pages site, `Red-Setup.exe`, the `winget` manifest.

### For the user to decide (these clash with the Rules below)
- **Spotify Web API** needs a Spotify account and key. The Rules allow only the user's Google account.
  Media keys need no account.
- **Plugins and "custom shell macros":** the Rules say never run model text as a command. Plugins must be
  code the user installed, and the model may only pick a plugin tool and fill its checked arguments.
- **Mascot shape:** the Rules forbid rounded edges and an outline on the glow. Does that apply to the
  mascot too?

## Later: more for the Red app

**Sections:**
- **Model:** the current model, a pick from `MODELS` with each one's `best_for` line, downloads, and the
  hardware recommendation.
- **Voice:** Piper voices with a Play sample button (downloaded: female `en_US-amy`, `en_US-lessac`,
  `en_GB-jenny_dioco`, `en_US-libritts_r`; male `en_US-joe`, `en_US-ryan`, `en_GB-alan`), and speed.
- **Wake phrase and listening:** "Hey Red", "Yo Red", "Okay Red", "What's up Red" with voice training,
  sensitivity, hotkey, microphone, voice match on/off and re-recording.
- **Speech-to-text:** Whisper model (`base.en` / `small.en`) and device.
- **Personality:** the persona modes in Roadmap 2.0 (and the opt-in casual banter that swears back).
- **Browser:** `RED_BROWSER` and the search engine.
- **Web search:** on or off, with the privacy note (task 7), and whether SearXNG is running.
- **Accounts:** Google sign-in and sign-out.
- **General:** start with Windows (`red/startup.py`).

Also later:
- The one-click installer and the glow that reacts to the voice: now in Roadmap 2.0.
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

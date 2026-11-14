# plan.md: Red v1 in 10 days

This is the only plan file. It lists **everything** that has to be done to ship Red v1. A session reads this file and nothing else from the old plans (docs/plan-history.md and D:\RED\cache\overnight\*.md are history only; the plan before this one is in git at `495fda9`).
**Day 1 = Sun 2026-11-15. Day 10 = Tue 2026-11-24: v1.0.0 ships.** `progress.md` is the developer reference (specs, decisions); the to-do list lives here.

**What Red is (the user, 2026-11-14):** "a problem-solving assistant, not a fun assistant." Getting the job done comes first: writing the code, doing the sum, finding the file, and saying clearly what it did and where the result is. Personality is how it talks while doing that, never instead of it.

## The user's to-do (everything else is automated)
| When | What | Why |
|---|---|---|
| ~~Day 1~~ | ✅ **Kaggle: done.** The access token is in `D:\RED\config\secrets\kaggle\access_token.txt` and the GPU is on | Training (Day 7) |
| **Day 1** | **Accounts (all free):** SignPath Foundation application (code signing for open source), SourceForge, itch.io, a Microsoft Partner Center developer account (free for individuals; check when signing up), Chocolatey. The track B session prepares every text | Signed installer and the download sites |
| **Day 3** | Listen to the voice, laugh, whistle and nature-sound sheet (`D:\RED\cache\voice-picks-young\`) and pick | Only you can judge how they sound |
| **Day 4** | Allow "keep clips Red misheard" (stays on this PC, never uploaded or committed) | Misheard voice gets fed back into the tests |
| **Day 8** | Use Red for the day: talk, dictate, drag the companions around; fill the 10-line score sheet | The one day you test by hand |
| **Day 9** | Approve the website text and the store listings | It's your public page |
| **Day 10** | Say "go" | Tagging and releasing v1.0.0 |

## Where things stand (2026-11-14)
- Today the user rates Red **5/10**. It works, but it feels unfinished:
  - it's slow on simple things (4–5 s);
  - it dropped "write a code for me" 5 times;
  - it says stock lines ("I'm searching on the web");
  - the three companions sound and talk alike, and their voices are too old;
  - it can't laugh, or say who or where it is;
  - a new companion continues the old one's topic;
  - it makes noise on hover;
  - it's small on the edge but huge when picked up;
  - there's no real installer;
  - testing depends on the user talking to it.
- **Decisions:**
  - No rewrite: the ~29k lines and 2,660 tests stay and get improved heavily.
  - Main target: NVIDIA 4 GB+ (RTX 3050 class), but it must work on every Windows PC.
  - v1 companions: Red, Remy and Asha. Bruno and Winston come after v1.
  - **The installer is a must for v1.**
- **On main** (`495fda9`):
  - all finished night-1/night-2 work;
  - the simulated user (`red/sim/`, 92 scenarios);
  - the licensed reaction-sound sources and builder;
  - the climbing sprite sets and window rectangles.

  The full suite passes (2660 tests).
- **On branch `night2/motion-wip`:** the unfinished climbing code for the companion window, for Day 6.

---

## How a session works (always the same)
1. The user opens a new session in D:\RED and pastes `You are track A. Read D:\RED\red\plan.md and do the next part.` (or track B). Or nobody pastes: `python D:\RED\red\scripts\run_tracks.py` runs the sessions headless, A and B side by side, and stops a track when it ticks nothing (summary in `D:\RED\cache\tracks\<date>\summary.md`; a `D:\RED\cache\tracks\STOP` file stops it). A headless session can't ask the user anything: do what can be done without them, write the question under the part, and stop without ticking it.
2. Read this whole file. A new line under **Flaws the user noticed** in your track comes first.
3. Take the **first unchecked part of your track** (`- [ ]`) in the day list. Do only that one part.
4. Work in your track's folder: `D:\RED\worktrees\track-a` or `D:\RED\worktrees\track-b` (create it from main if missing: `git -C D:\RED\red worktree add D:\RED\worktrees\track-<x> -b track-<x> origin/main`). Start with `git fetch` and `git rebase origin/main`.
5. **Commit after every small working step** (`type(scope): what`, message written to a file, then `git commit -F <file>`) and push your branch (`git push origin HEAD:track-<x>`).
6. When the part works:
   1. Run `git fetch` and `git rebase origin/main`.
   2. Run the full suite:
      ```
      $env:RED_HOME="D:\RED"; $env:QT_QPA_PLATFORM="offscreen"; $env:QT_QPA_FONTDIR="C:\Windows\Fonts"
      D:\RED\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --basetemp=D:\RED\cache\pytest-tmp-<x>
      ```
   3. Once they exist, also run the replay tests and `python -m red.sim run --limit 10`.
   4. Push to main: `git push origin HEAD:main`.
7. Tick the part and add one line under it: the date, the commits, **the numbers measured against the part's exit check**, and what the user should try. Commit and push that to main.
8. Stop, and say in 3–5 lines what was done and what to try.

If a part is too big for one session, finish a clean piece, commit, and split the rest into a new unchecked part right below it. A day's parts must all be ticked before the next day's parts start; if a day slips, the cut line (below) decides what moves to v1.1.

## Never do these
- Never edit `D:\RED\config\.env`, start a second Ollama, or delete the user's files, memory, recordings or models.
- Never put anything on drive C. Downloads, caches, models and training output go under `D:\RED`. Kaggle: `$env:KAGGLE_CONFIG_DIR = "D:\RED\config\secrets\kaggle"`.
- Never commit secrets, voice recordings (including misheard clips), memory or the wake corpus.
- Never use the Bash tool with heredocs (`python - <<'EOF'`): it crashed Claude Code. Write scripts with the Write tool and run them with PowerShell.
- Never play sound through the speakers or use the real microphone, real windows or real hotkeys in tests. Measure audio instead (length, loudness, pitch). The user listens.
- Never weaken a safety rule (confirmations, allowlists, never running model-written text) to make a test pass.
- Never use an asset without a recorded licence (CC0, CC-BY with credit, Pixabay, Apache/MIT models). No rips, no paid packs.
- Never force-push main, and never touch the other track's files.
- Don't read whole big logs: use `Select-String` and `-Tail`. Keep real-model runs to 10 conversations unless the user has been away 10+ minutes (the nightly run has no cap).
- Only track A restarts the hidden Red, after a part that changed how Red talks or listens: `git -C D:\RED\red pull --ff-only`, then `python -m red stop` and `python -m red background` from D:\RED\red, then check red.log for "listening for".
- Avatar renders run from PowerShell only (Edge exits silently under Git Bash).

## Who owns what
- **Track A, brains and voice:** everything in `red/` except `red/avatar/`, `red/app/`, `red/tray.py`, `red/windows.py`; plus `scripts/` (except `scripts/avatar_render/`), `companions/`, `sounds/`, `training/`, `red/sim/`, and their tests.
- **Track B, body, app and shipping:** `red/avatar/`, `red/app/`, `red/tray.py`, `red/windows.py`, `scripts/avatar_render/`, `installer/`, `site/`, `docs/`, `README.md`, `CHANGELOG.md`, and their tests.

---

## 1. The architecture flow v1 ships with
One path for every sentence. Each stage has a pass/fail number in the Red Score (section 2).

```
 Mic ─► 1 LISTEN ─► 2 FOR ME? ─► 3 HEAR ─► 4 UNDERSTAND ─► 5 ACT ─► 6 SPEAK ─► 7 BODY ─► 8 REMEMBER
        wake/names   gate          Whisper   one model call   tools     voice +    avatar    profile,
        mic modes    (never drop   + clean   (talk or tool),  safety,   laughs,    emotion,  facts, now
        dictation    silently)     up        stream reply     confirm   tags       placement
```
1. **Listen** (`red/listener.py`, `red/wakeword.py`):
   - Hidden companion: "Hey Red" brings it out in ≤1 s.
   - Visible companion: a bare name ("Remy", "Asha", "Red", and spellings like "Raid", "Remi", "Usha") is enough. A name only counts on its own or at the start of a sentence.
   - Mic modes: *Name only* (the default), *Always listening*, *Button only*.
   - **Dictation** branches off here (section 1c).
2. **For me?** (`dictation_like` and `_not_for_me` in `red/conversation.py` and `red/__main__.py`):
   - "for me", "can you", a name, or a repeat / "I said…" always means it's for Red.
   - When unsure, it asks "for me?". It never drops a sentence silently.
3. **Hear** (`red/stt.py`): smart end-of-speech, about 0.5 s when the sentence sounds finished and longer when the user trails off. It never cuts the user off (the user asked for that on 2026-11-08).
4. **Understand** (`red/router.py`, `red/fastpath.py`, `red/chat.py`):
   - **One** streamed model call that is either a reply or a tool call. Today chat waits 1.5–2 s for a separate route call first.
   - It answers from what it knows and searches the web only for recent or unknown things.
   - It never says "I'm searching" or other stock lines.
5. **Act** (`red/executor.py`, `red/tools/`, `red/plugins/`):
   - The safety rules don't change.
   - Every tool ends with a clear "what I did and where it is" (`write_code`: where the code is, what it does, what to do next).
6. **Speak** (`red/speech.py`, `red/tts_kokoro.py`, new `red/expressive.py`; design in docs/architecture.md §7):
   - The model writes tags (`[laugh] [chuckle] [sigh] [hmm] [whistle]`…).
   - Each engine renders what it can, and a tag is never read aloud.
7. **Body** (`red/avatar/`): emotion and laughs in sync with the voice; it knows where it is on screen; fast switching; climbing; reactions (section 1b).
8. **Remember** (`red/memory.py`):
   - **Who the user is:** the profile, filled by the first-run questions.
   - **What they're working on these days.**
   - **What they're doing now:** the window in front, kept for the session only and never saved.

### Tiers (a short benchmark at first run picks one; new `red/bench.py`, extends `red/hardware.py` `recommend()`)
| Tier | PC | Model | Voice | First word |
|---|---|---|---|---|
| Lite | no GPU, 8 GB RAM | qwen2.5-3b on the CPU | Kokoro on the CPU + clip banks | ≤ 2.5 s |
| **Standard (main)** | 4 GB GPU (RTX 3050) | qwen3.5-4b on the GPU | Kokoro on the CPU + expressive clip banks | ≤ 1.0 s |
| Plus | 6 GB+ GPU | qwen3.5-4b or 9b | the live expressive engine, *only if the Day 2 bake-off passes* | ≤ 1.0 s |

### 1a. The companions: three different people, each with its own mind
- **Red:** code and games; dry and quick. **Remy:** music; bright, and whistles. **Asha:** nature and books; warm and curious. (Red no longer loves music: Remy owns it, so they stop overlapping.)
- **They know themselves.** A `[self]` sheet in each `companions/<id>/companion.toml` says:
  - who it is (an AI companion that lives on your screen; no invented body, home or past);
  - its story and taste;
  - what it can do;
  - how it talks.

  The prompt also gets **live self-state**:
  - where it is now ("hanging upside down from the top-left corner");
  - how long it has been awake;
  - its mood;
  - the mic mode;
  - what it last did.

  So "Where are you?" and "Tell me about yourself" get true, in-character answers.
- **Each companion has its own mind.** Today, after the user asked Red about Hades, the next companion carried on about Hades, as if only the outer form had changed. In v1:
  - each companion keeps its own conversation, mood and relationship note (`memory/companions/<id>/`);
  - only the user's profile and facts are shared;
  - on a switch the new one starts its own thread, and at most notes the user was with someone else ("You were with Red? Fine. What's up?").
- **Habits** (`[habits]`, licensed sounds only):
  - Remy whistles a short tune now and then.
  - Asha, after about 15 quiet minutes, makes a bird chirp, a few flute notes, or wind in leaves.
  - Red: soft keyboard tapping, or a quiet "hm".

  At most one habit every 15–20 minutes, never in quiet mode, calls, full screen, or over speech.
- **Proactive chat:** now and then (at most every 20–30 minutes) it asks what the user is doing. During serious work (an editor, a document, a long stretch in one app) it asks once whether to stay quiet, or waits for a break. Never in calls or full screen.

### 1b. The body: how it moves and reacts
- **Climbing, like pulling a rope.** It holds an edge or corner with **both hands** and moves **hand over hand**: along the bottom, up a side, across the top like monkey bars, around corners. It never teleports. A natural pace, never under the cursor, and the spot is saved.
- **Knocking on the screen.** For a reminder or its proactive chat, it turns toward the user and knocks on the glass from inside: a knuckle-tap animation plus a licensed knock sound. At most once per event.
- **Hovering is silent.** It waves hi or shows a small emotion (a smile, a curious tilt, a shy look away), with **no sound**. Sounds play only for poke, pickup and drop, at most one a second.
- **The same size everywhere.**
  - The carried frames are scaled to match the edge frames.
  - The default size is a little smaller (about 85% of today's medium).
  - Hands and feet are never cut while it's carried.
- **More reactions when handled.** Each companion reacts its own way (Red unimpressed, Remy delighted, Asha startled then laughing):
  - picked up: happy, nervous or annoyed (kicking legs, a happy wiggle, folded arms);
  - shaken: dizzy;
  - dropped: a bounce and a pout, or a laugh;
  - flung: an arc that grabs the nearest edge;
  - poked: a squash.
- **"Hey Red" when hidden:** it slides out from its edge and waves, in ≤1 s. Saying another name: the current one waves and slides off as the named one slides in.

### 1c. Dictation: a free Wispr Flow
A mode where Red doesn't answer. It types what the user says into the app in front.
- **Start:**
  - hold the dictation hotkey (push-to-talk);
  - or double-tap it to lock it on, and tap again to stop;
  - or long-press the companion's mic button.
- **What happens:** Whisper writes it, with the existing Wispr-style clean-up (fillers removed, self-corrections fixed, personal vocabulary). Red pastes **exactly what was said** at the cursor, through the clipboard and Ctrl+V, then restores the old clipboard. The companion shows a small "typing" pose.
- **What never happens:** no model rewriting, nothing sent anywhere.
- **Safety:** the user's own words, pasted and never run. The only key press is the fixed Ctrl+V.

### 1d. Learning from what it mishears
When Red mishears, misses a wake, or the user repeats or corrects ("I said…", "no, I meant…"), the clip and what Whisper heard are saved **on this PC only** (`D:\RED\cache\misheard\`; never committed or uploaded; can be turned off).
- Each night they're fed back into the voice simulator as test cases.
- They also feed the personal vocabulary and the wake-name spellings, and the hand-labelled ones join the replay tests.

So every mishearing becomes a test that has to pass from then on.

### 1e. Voice and laughter
- **Day 2 bake-off** (`scripts/voice_bakeoff.py`): Kokoro against 3–4 expressive open models. The candidates' licence (Apache or MIT) and size are checked first. Each is measured on:
  - time to first audio;
  - VRAM, alongside the 4B model in 4 GB;
  - whether it does laughs and sighs;
  - Whisper intelligibility;
  - a listening sheet for the user.
- **Every tier gets clip banks:** laughs, chuckles, sighs, "hmm", whistles and reactions per companion, rendered at build time in a voice matched to that companion and shipped in the installer.
- **The Plus tier gets the live engine** only if it reaches ≤1.0 s to first audio.
- **Voices:** young (20–24) and clearly apart (15+ Hz in pitch, and pace). Asha deeper than now, Remy lighter, Red higher than `am_michael`.

---

## 2. The Red Score (5/10 today → 8/10+ to ship)
`python -m red score` (new, on top of `red/sim/` and `scripts/persona_eval.py`) turns these measurements into one 0–10 number. It runs every night, and Day 1 records the baseline.

| Measure | v1 target |
|---|---|
| First word after you stop (chit-chat), Standard tier | ≤ 1.0 s median |
| First word, Lite tier | ≤ 2.5 s median |
| Real requests done correctly (code, sum, file, mail, reminder) | ≥ 90% |
| Requests dropped silently | 0 |
| Stock lines / invented life / written laughter | 0 |
| Blind "who said this?" across Red, Remy and Asha | ≥ 80% |
| A new companion continues the old one's topic | 0 times |
| Wake: "Hey Red" and names heard | ≥ 95% |
| False wakes in 1 h of other talk | ≤ 1 |
| Companion on screen after "Hey Red" | ≤ 1 s |
| Companion switch | ≤ 1 s on screen, ≤ 2 s to talking |
| Dictation: pasted after you stop (10 s of speech) | ≤ 1 s, exactly what was said |
| Sounds on hover | 0 |
| Carried vs. on-edge size | within 10%; hands and feet never cut |
| Mishearings from the user's real clips that still fail | lower every night |
| Soak: crashes / memory growth over 8 h | 0 / < 10% |
| Clean install → companion talking | ≤ 10 min |

## 3. Automated testing (so the user doesn't have to talk to it)
| Layer | What | When |
|---|---|---|
| Unit | the existing 2,660 tests with fakes | every commit |
| **Replay** | every real sentence in `logs\commands.jsonl` (195 now), labelled once: it reaches Red, goes to the right tool or to talk, and never hits a stock line | every commit |
| **Text simulator** | `red/sim/` grows from 92 to ~200 scenarios, half of them real work; rules plus a judge | quick version every part, full version nightly |
| **Voice simulator** | Kokoro speaks the user's lines into the listener in software, plus the misheard clips: wake, false wakes, hearing, first word, dictation accuracy | nightly |
| **UI sheets** | offscreen renders of every placement, state, size and reaction | every B part; nightly diff |
| **Installer** | build `Red-Setup.exe`, install it silently in Windows Sandbox (`installer/sandbox-test.wsb`), run `red doctor`, uninstall | nightly from Day 1 |
| **Soak** | 8 h with sleep/wake, a mic unplug and a busy GPU | nightly from Day 7 |

**Nightly run:**
- A scheduled task at 03:00, only when the PC is idle; `python -m red nightly on|off` sets it up.
- It writes `D:\RED\cache\nightly\<date>\report.md` with the Red Score, what got worse, and the 5 worst replies.
- The morning greeting says one line about it.

**Gates:**
- A part can't merge unless the unit and replay tests pass.
- A release needs every layer green and every Red Score target met.

## 4. Automated training
`python -m red train` (new). Each stage is checked before the next one starts.
1. **Collect:** the simulator's graded-good conversations, the user's real lines with Red's side rewritten fresh, and ~30 hand-written "perfect" replies per companion.
2. **Scrub:** remove emails, phone numbers, addresses and keys.
3. **Build** a private dataset in `D:\RED\cache\train\`.
4. **Kaggle:** upload, run the Unsloth LoRA notebook on Qwen3.5-4B (`training/kaggle_lora.ipynb`, every cell explained; free 16 GB GPU, about 1–2 h), poll until done, download the GGUF (q4_K_M).
   - **The token** is Kaggle's newer API access token, in `D:\RED\config\secrets\kaggle\access_token.txt` (not the old `kaggle.json`). The training script reads it and hands it to the Kaggle CLI or API **for that process only**: `KAGGLE_API_TOKEN`, or an `access_token` file in `KAGGLE_CONFIG_DIR=D:\RED\config\secrets\kaggle`, whichever the installed `kaggle` package supports (checked on Day 7).
   - The token is never printed, logged or committed.
5. **Import** it into Red's Ollama as a *candidate*. The current model stays.
6. **Eval gate:** the simulator, replay, routing and blind-persona tests, old vs. new. The candidate wins only if it's more human, at least as good at tools, and not slower.
7. **Report**, then the user switches with one click in the app. Never automatically, and `.env` is never touched.

v1 gets one training run (Day 7). If the candidate doesn't win, v1 ships the base model. After v1, training reruns at night whenever 500+ new graded examples exist.

## 5. Shipping
### The installer (a must)
`Red-Setup.exe`, built with Inno Setup from `installer/red.iss` and `installer/build.ps1`. It:
- bundles embedded Python and the pinned packages;
- ships the companion pictures, voices, clip banks and habit sounds;
- downloads the model on first run, with a progress bar, then runs the tier benchmark;
- adds Start menu entries, with start-with-Windows on by default;
- on uninstall, asks whether to keep memory, settings and models.

It's tested automatically in Windows Sandbox every night.

The first-run wizard (`red/app/`):
- pick a companion and hear each voice;
- your name, what you do, and what you'd like help with (into the profile);
- a mic check;
- the mic mode;
- the dictation hotkey;
- the tip "Hey Red calls me; then just say my name".

The tray checks GitHub Releases once a day and shows "Update available".

### Where people download it (free, well-known platforms)
| Platform | What it is | How Red gets there |
|---|---|---|
| **GitHub Releases** | The main home: free, trusted, with checksums | `Red-Setup.exe` + SHA-256 on the v1.0.0 release |
| **Website on GitHub Pages** | Free hosting from the repo (`site/` folder; a custom domain can be added later) | One page: what Red is, a demo GIF, download buttons, privacy, requirements per tier, FAQ, credits |
| **SourceForge** | One of the oldest free hosts for open-source Windows software; mirrors the GitHub release | Project page + the same installer |
| **winget** (Windows Package Manager) | Microsoft's own package manager, built into Windows 10/11 (`winget install Red`) | A manifest pull request to `microsoft/winget-pkgs`, pointing at the GitHub release |
| **Microsoft Store** | Built into Windows; individual developer accounts are free | Submit on Day 9 (review takes days and may land after Day 10). An MSIX package gets signed by Microsoft, which also solves Smart App Control. An EXE submission needs our own signature, so MSIX is the target |
| **Chocolatey** | The biggest community package manager for Windows | A community package pointing at the GitHub release (moderated; may take days) |
| **Scoop** (extras bucket) | A popular developer-focused installer for Windows | A manifest pull request |
| **itch.io** | A well-known free store for indie apps and games, good for desktop companions | A project page with the installer |

### Trust and signing
- Apply to **SignPath Foundation** (free code signing for open-source projects) on Day 1; it takes time.
- Until it's approved, the website and README show the SmartScreen steps ("More info → Run anyway") and the SHA-256 to check.
- The Microsoft Store's MSIX route gives a Microsoft-signed version.

---

## 6. The 10 days
Each day's exit check must pass before the next day starts. The lines under a ticked part record the measured numbers.

### Day 1, Sun 11-15: measure everything, install anywhere
- [ ] **A1.** Replay tests: label all real sentences in `logs\commands.jsonl` (`tests/test_replay.py` + `tests/replay/*.toml`, no private details). Fix the dropped "write a code" requests (`dictation_like`, ask "for me?" instead of dropping, "I said…" always for Red, clear `write_code` feedback). Fix `listener.write_mic_state` dropping mic.json's "zipped". `python -m red score` with the baseline recorded here.
- [ ] **B1.** `Red-Setup.exe` builds; `installer/sandbox-test.wsb` + `sandbox_test.ps1` install it silently, run `red doctor` and uninstall; the nightly scheduled task (`red/nightly.py`, `python -m red nightly on|off`). Prepare the SignPath, SourceForge, itch.io, Partner Center and Chocolatey texts for the user.
- Exit check: baseline score recorded; the installer installs and uninstalls in Sandbox; replay green.

### Day 2: fast answers, the voice decision
- [ ] **A2.** One-call understanding (no separate route call for chat); smart end-of-speech; answer from knowledge first; no "I'm searching" (a short line of the companion's own if a search takes over 2 s).
- [ ] **B2.** `scripts/voice_bakeoff.py` (with track A's engines) + the listening sheet; `red/bench.py` tier benchmark at first run; a full Lite run with the GPU hidden.
- Exit check: first word ≤ 1.0 s median on the 4050 and ≤ 2.5 s on Lite, measured; bake-off decided.

### Day 3: voices, laughs, the right size
- [ ] **A3.** `red/expressive.py` (tags, never read aloud); clip banks per companion; young, distinct voices; build the reaction packs and the habit sounds (whistle, birds, flute, wind, knock, keyboard), all licensed, credits in `THIRD_PARTY.md`.
- [ ] **B3.** Hover is a silent wave or emotion; the same size on the edge and carried (about 85%, hands and feet never cut); the mic button against the body, the zip on the mouth; Asha's whole body while moving; companion switch ≤ 1 s (preloaded pictures).
- Exit check: voices 15+ Hz apart; 0 tags read aloud; 0 hover sounds; size sheet within 10%; switch ≤ 1 s.

### Day 4: listening the way the user wants
- [ ] **A4.** "Hey Red" when hidden, names when visible (with Whisper's spellings), the three mic modes; the voice simulator; the misheard-clip loop (section 1d).
- [ ] **B4.** Coming out when called (≤ 1 s, slide and wave); `foreground_app()` in `red/windows.py` (kind: mail_compose, call, game, editor, full screen); the first-run wizard with the profile questions, mic mode and dictation hotkey.
- Exit check: wake ≥ 95%, false wakes ≤ 1/h (voice simulator); out on screen ≤ 1 s; misheard clips replayed in the nightly run.

### Day 5: three real characters
- [ ] **A5.** Rewrite the 3 personas (Red code and games, Remy music, Asha nature and books); `[self]` sheets + live self-state; a separate mind per companion; memory of the user (who, these days, now).
- [ ] **B5.** Render the climbing frames (both hands on the edge, hand over hand, monkey bars, corners), the knock frames and the handling-reaction frames for all three (`scripts/avatar_render`, `--sets`, `--keep-crop`); look at the sheets.
- Exit check: blind persona ≥ 80%; "where are you?" right in all 6 placements; a new companion never continues the old topic; sheets approved by eye.

### Day 6: real work, dictation, climbing
- [ ] **A6.** Dictation (`red/dictation.py`, section 1c); real work with clear feedback (code write/fix/explain, sums, files, reminders, mail-help offer); the simulator at ~200 scenarios.
- [ ] **B6.** Climbing paths around the screen (start from branch `night2/motion-wip`); knocking on the screen; habits played by the window.
- Exit check: real-work tasks ≥ 90%; dictation ≤ 1 s and exactly what was said in VS Code, a browser and Word; climbs to every corner without teleporting.

### Day 7: training, and a lively body
- [ ] **A7.** Training: dataset → Kaggle run → candidate → eval gate → report (section 4). First a 1-minute check: `kaggle kernels list --mine` works with the token.
- [ ] **B7.** Handling reactions per companion (pickup moods, dizzy, pout, fling-and-grab, poke squash); quiet life and proactive chat timing; the tray update check; the 8 h soak in the nightly run.
- Exit check: training report written; soak with 0 crashes; a reaction sheet for every companion.

### Day 8: release candidate 1, the user's day
- [ ] **A8.** Build RC1 with B; the user uses it for the day and fills the score sheet; fix the worst findings from the sheet and the nightly report.
- [ ] **B8.** Installer RC1 in Sandbox and on the user's PC; fix the worst findings.
- Exit check: user score ≥ 8/10, or a fix list for Day 9.

### Day 9: ready to ship
- [ ] **A9.** Fix RC1 findings; final model choice (base or trained); docs/architecture.md matches what ships.
- [ ] **B9.** README (what it is in 30 seconds, demo GIF, install, privacy, honest numbers from the Red Score, credits), CHANGELOG, `THIRD_PARTY.md`, the website in `site/`, SourceForge and itch.io pages, winget, Chocolatey and Scoop manifests, MSIX + Microsoft Store submission.
- Exit check: the nightly run is all green; every Red Score target met.

### Day 10, Tue 11-24: release
- [ ] **A10.** Final run on a clean Sandbox: install → first run → "Hey Red" through the voice simulator → the companion answers → uninstall asks about data.
- [ ] **B10.** When the user says go: tag v1.0.0, the GitHub Release (installer + SHA-256), the SourceForge upload, the winget/Chocolatey/Scoop pull requests, the itch.io page, the website live.
- Exit check: download → install → companion talking in ≤ 10 min on a clean machine.

### Cut line if a day slips (moves to v1.1)
- sitting on top of app windows;
- games;
- the mail-help offer;
- the Desktop-only mode;
- Bruno and Winston;
- the Chocolatey and Scoop listings.

**Never cut:**
- the installer;
- speed;
- no dropped requests;
- the tests and nightly run;
- distinct young voices with laughs (at least as clips);
- self-knowledge;
- a separate mind per companion;
- dictation;
- silent hover and consistent size;
- climbing with both hands, and knocking;
- the first-run wizard;
- GitHub Releases, the website, SourceForge and winget.

## Flaws the user noticed (new ones go here; they come first in their track)
Put each flaw on its own line with A or B. The flaws from before this plan are folded into the days above.

## Done before this plan (short history)
- **Nights 1 and 2 (2026-11-13/14):**
  - talk skips the router;
  - human replies, with no invented life;
  - the event bus;
  - bubbles that follow the voice;
  - Microphone off;
  - companion packs, emotions, idle life and songs;
  - top corners and idle animations;
  - the right-click menu and the summon hotkey;
  - the Companions page;
  - installer sources and a first-run wizard;
  - the tray icon;
  - the mic button and conversation mode;
  - waking on names.

  Reports in `D:\RED\cache\overnight\`.
- **2026-11-14:**
  - a stuck Ollama restarts itself (`OllamaKeeper`);
  - mic-button fixes;
  - `run_tracks.py`;
  - merged the simulated user, the licensed sound sources and the climbing sprite sets;
  - the old worktrees were removed;
  - this plan.

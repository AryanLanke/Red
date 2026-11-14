# plan.md: the one plan for Red

This is the only plan file. A session reads this file and nothing else from the old plans (the old plan is docs/plan-history.md and D:\RED\cache\overnight\*.md: history only, don't follow them).
Goal: ship **Red v1** around 2026-11-21.

## How a session works (always the same)
1. The user opens a new session (Sonnet 5.5, Medium) in D:\RED and pastes: `You are track A. Read D:\RED\red\plan.md and do the next part.` (or track B).
2. Read this whole file. Then check **Flaws I noticed** below: an open flaw in your track comes before any part.
3. Take the **first unchecked part of your track** (`- [ ]`). Do only that one part. Never start a second part in the same session.
4. Work in your track's folder: track A in `D:\RED\worktrees\track-a`, track B in `D:\RED\worktrees\track-b`. If the folder doesn't exist, create it from main: `git -C D:\RED\red worktree add D:\RED\worktrees\track-<x> -b track-<x> origin/main`. Start with `git fetch` and `git rebase origin/main`.
5. **Commit after every small working step** (`type(scope): what`, message written to a file, then `git commit -F <file>`) and push your branch (`git push origin HEAD:track-<x>`). Many small commits are wanted.
6. When the part works:
   1. Run `git fetch` and `git rebase origin/main`.
   2. Run the **full** test suite:
      ```
      $env:RED_HOME="D:\RED"; $env:QT_QPA_PLATFORM="offscreen"; $env:QT_QPA_FONTDIR="C:\Windows\Fonts"
      D:\RED\.venv\Scripts\python.exe -m pytest tests -q -p no:cacheprovider --basetemp=D:\RED\cache\pytest-tmp-<x>
      ```
   3. Push to main: `git push origin HEAD:main`.
7. In this file, tick the part (`- [x]`) and add one line under it: the date, the commit hashes, what was measured, and anything the user should try. Commit and push that to main too.
8. Stop. Say in 3–5 lines what was done and what the user should try. The user closes the session and opens a new one for the next part.

If a part is too big for one session, finish a clean piece of it, commit, and split the rest into a new unchecked part right below it. Don't leave work uncommitted.

## Never do these
- Never edit `D:\RED\config\.env`, start a second Ollama, or delete the user's files, memory, recordings or models.
- Never put anything on drive C. Project files, downloads, caches, models and training output go under `D:\RED`. Kaggle: `$env:KAGGLE_CONFIG_DIR = "D:\RED\config\secrets\kaggle"`.
- Never commit secrets, voice recordings, memory or the wake corpus.
- Never use the Bash tool with heredocs (`python - <<'EOF'`): it crashed Claude Code. Write scripts with the Write tool and run them with the PowerShell tool.
- Never play sound through the speakers or use the real microphone, real windows or real hotkeys in tests. Measure audio instead (length, loudness, pitch). The user listens.
- Never weaken a safety rule (confirmations, allowlists, never running model-written text) to make a test pass.
- Never use an asset without a recorded licence (CC0, CC-BY with credit, Pixabay). No rips, no paid packs.
- Never force-push main, and never touch the other track's files (see the tracks below).
- Don't read whole big logs: use `Select-String` and `-Tail`. Keep real-model runs short (10 conversations at most) unless the user has been away for 10+ minutes.
- Only track A restarts the hidden Red, at the end of a part that changed how Red talks or listens: `git -C D:\RED\red pull --ff-only`, then from D:\RED\red run `python -m red stop` and `python -m red background`, then check red.log for "listening for".
- Avatar renders run from PowerShell only (Edge exits silently under Git Bash).

## Flaws I noticed (the user writes here, in plain words; these come first)
Put each flaw on its own line, with A or B if you know which track it belongs to. A session fixes the first open one in its track, ticks it, and writes one line on what it changed.
- [x] (A) Red still feels slow to answer.
  - 2026-11-14, e4d3d82 05e2b28: the biggest delay was a hung Ollama. At 03:04 Red's own Ollama stopped handing chat requests to the model (it still answered /api/tags; the last callers were the night-2 eval scripts sharing it), and Red waited 300 s per warm-up and 120 s per reply ("lost my train of thought") until 07:55, which is 118 hung requests. Now `OllamaKeeper` restarts Red's own Ollama on the first timed-out reply or warm-up (warm-up gives up at 90 s, not 300 s), at most every 3 min. Live check with the runner frozen: back in 11.3 s, next reply 0.67 s. Normal chit-chat before the hang was 1.6–2.4 s to the first word (02:34–02:38: text ready 0.33 s, chat 0.8–1.2 s); A2 still owns getting that to 1.0 s. Try: talk to Red after it has sat idle for a long time; it should answer at once.
- [ ] (A) Remy and Asha sound the same; all three should sound younger and different.
- [ ] (A/B) The user feels every night-2 change has small flaws. Ask nothing: try each feature end to end (the simulated user once it exists, or tests and logs), list what's broken here, and fix the worst first.
  - [x] (B) 2026-11-14, b4ae06c b56d903 65ecc30: B's only night-2 change on main is the companion's mic button. Drove the real Red window offscreen in all 6 placements × 7 mic states and looked at the sheet. Fixed: (1) a mouth left zipped by the last run (mic.json) showed an open mic at start; (2) "not for me?" was painted over Red's eyes, and now sits where the bubbles go; (3) `attach_tray` crashed Python (access violation) when no Qt app existed, e.g. `tests/test_avatar_wiring.py` run alone. Try: say something not for Red in conversation mode; the grey tag should appear above his head.
  - [ ] (A) `listener.write_mic_state` overwrites mic.json with only `{"muted": ...}`, so turning the mic off or on drops conversation's `"zipped"`. It should merge, like `conversation.write_state` does.
  - [ ] (B) night-2 motion isn't on main yet; it gets checked the same way when B1 lands it.

## Track A: brains and voice
Owns: everything in `red/` **except** `red/avatar/`, `red/app/`, `red/tray.py`, `red/windows.py`; plus `scripts/` (except `scripts/avatar_render/`), `companions/`, `sounds/`, `training/`, `tests/` for those files.

- [ ] **A1. Land the leftovers.** In `D:\RED\worktrees\n1-voice` there are about 10 unsaved files (the old sounds work), and `night1/testing` has 3 commits not on main. Look at each, keep what works (with tests), commit it to main, and drop the rest. Then remove the old worktrees `n1-voice`, `n1-testing`, `n2-conversation`, `n2-personality` (after checking that nothing unsaved is left).
- [ ] **A2. Speed check.** Measure the first word after the user stops talking, from red.log Timing lines and a short real-model run. The target is 1.0 s or less for chit-chat (last measured 1.7–3 s). Find the biggest delay and fix that one thing. Record the numbers.
- [ ] **A3. Young, different voices.** Red, Remy and Asha should sound about 18–22 and clearly different from each other: by voice, pitch (15+ Hz apart) and pace. Use Kokoro voices, or a blend of two. Measure them, save samples in `D:\RED\cache\voice-picks-young\` for the user to hear, and set them in `companions/*/companion.toml`.
- [ ] **A4. Real reaction sounds.** Download real recorded clips with licences (Freesound CC0/CC-BY using the key in `D:\RED\config\secrets\freesound.txt` if it exists, OpenGameArt, Pixabay). Make Japanese and English packs, young and playful: pickup, drop, hover, poke, giggle, surprised, "hey!", "hmph", yawn, zip. Record every licence in `pack.toml` and `THIRD_PARTY.md`. `scripts/make_sounds.py` rebuilds them from `sounds/sources.toml`. The old Kokoro clips stay only as the fallback.
- [ ] **A5. Simulated user, text mode.** A script (`red/sim/`) that talks to Red and each companion through the real pipeline, with tools in dry run and a temporary memory copy. It runs 3–8 turn conversations from a scenario file (including the user's real sentences from logs\commands.jsonl), grades the replies with rules (invented life, written laughter, wrong tool, a literal "whatever", too slow) and writes `D:\RED\cache\sim\<date>\report.md`. `python -m red selftest` runs a quick version.
- [ ] **A6. Fix what A5 finds.** Take the worst 3 problems from the report, fix them, re-run, and keep a fix only if it helps and nothing gets worse.
- [ ] **A7. Simulated user, voice mode.** Kokoro speaks the user's lines straight into Red's listener in software. Measure wake misses, false wakes, how well it hears, and the first word.
- [ ] **A8. Kaggle training data.** A private dataset under `D:\RED\cache\train\`: the best simulated conversations plus the user's real lines (their side only; Red's side regenerated and graded), with emails, phone numbers, addresses and keys scrubbed. Plus `training/kaggle_lora.ipynb` (Unsloth LoRA on Qwen3.5-4B, T4, GGUF q4_K_M) with every cell explained.
- [ ] **A9. Kaggle run.** Only if `D:\RED\config\secrets\kaggle\kaggle.json` exists. `scripts/kaggle_train.py` uploads the private dataset, runs the notebook on a GPU, and downloads the model to `D:\RED\cache\train\`.
- [ ] **A10. Try the trained model.** Import it into Red's Ollama (only while the user is away), run the simulation and the routing check, and compare. Write the result. Recommend switching only if it is more human, routes as well, and isn't slower; never edit .env.

## Track B: body, app and shipping
Owns: `red/avatar/`, `red/app/`, `red/tray.py`, `red/windows.py`, `scripts/avatar_render/`, `installer/`, `docs/`, `README.md`, and tests for those.

- [ ] **B1. Land the leftovers.** `night2/motion` has 1 commit not on main, and `D:\RED\worktrees\n2-motion` has 3 unsaved files. Look at them, keep what works, commit to main, drop the rest, and remove the n2-motion worktree.
- [ ] **B2. Climbing poses for Red.** New frame sets for Red only: holding a side edge with both hands, climbing hand over hand up a side, moving along the top like monkey bars, and sitting on a window's top edge. Register them in frames.js, page.js, finish.py and window.load(); render with `--sets` and `--keep-crop`. Look at the sheets before committing.
- [ ] **B3. The same poses for Remy and Asha.**
- [ ] **B4. Climbing paths on the screen.** Instead of jumping to another corner, the companion climbs there: along the bottom, up the side, across the top. A natural pace, never under the cursor, and the spot is saved.
- [ ] **B5. Sitting on app windows.** Window rectangles in `red/windows.py`. The companion can climb onto the top edge of the app you're using and follow it when it moves, never covering its buttons. It drops back to a screen edge when the window closes, minimises or goes full screen.
- [ ] **B6. Two modes:** Everywhere (default; on top of apps, hidden in full screen) and Desktop only (shown only when the desktop is in front). A setting, a menu item and the Companions page.
- [ ] **B7. Its own quiet life, and chatting.** When the user has been away 10+ minutes, it climbs, naps and looks around with no sound and no talking. When the user is there, it says something short now and then, in its persona, at most every 20–30 minutes at `companion` chattiness, never in full screen, calls or quiet mode.
- [ ] **B8. Funny reactions with movement:** poke (squash), hover (lean away), fast drag (flailing legs), shake (dizzy), drop (bounce and pout), fling (an arc that grabs the nearest edge). Use track A's sounds when they exist; at most one sound a second.
- [ ] **B9. The installer for real.** Build `Red-Setup.exe`, and write down how to run it with Smart App Control on (signing options: SignPath Foundation, the Store). Ship the companion pictures, or a first-run step that makes them. Check the uninstall question.
- [ ] **B10. 24-hour reliability.** A script that runs Red for hours (sleep and wake, a mic unplug, a full GPU) and reports crashes, memory growth and slowdowns. Fix the worst thing it finds.
- [ ] **B11. README and release.** A README that sells it in 30 seconds (what it is, a demo GIF or video placeholder, install, privacy, an honest comparison with numbers from A2 and A5, credits), CHANGELOG, and the v1.0.0 release steps. Tag only when the user says so.

## Done so far (short history)
- **Night 1 (2026-11-13/14):**
  - talk skips the router; the model-reload bug was fixed; human replies (no invented life)
  - event bus; the bubble follows the voice, and the user's words show in grey
  - Microphone off; the end-of-speech wait is 0.5 s; Wispr-style clean-up
  - a male voice for Red; companion packs, emotions, idle life and temper, a song of its own
  - top corners and idle animations; the right-click menu; the summon hotkey; the Companions page
  - installer sources and the first-run wizard; the tray icon
  - Japanese reaction packs (made with Kokoro, not real recordings)

  Report: `D:\RED\cache\overnight\FINAL-REPORT.md`.
- **Night 2 (2026-11-14):**
  - **Personality:** real, different characters with taste and songs; "play whatever you like" picks from the companion's own songs; persona_eval.py.
  - **Conversation:** the mic button (click to talk, click to zip); conversation mode; follow-ups after actions; echo and "not for me" rules; waking on companion names (fuzzy).

  Reports: `D:\RED\cache\overnight\report-personality.md` and `report-conversation.md`.

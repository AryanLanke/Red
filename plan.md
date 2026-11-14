# plan.md: the one plan for Red

This is the only plan file. A session reads this file and nothing else from the old plans (the old plan is docs/plan-history.md and D:\RED\cache\overnight\*.md: history only, don't follow them).
Goal: ship **Red v1** around 2026-11-21.

**What Red is (the user, 2026-11-14):** "a problem-solving assistant, not a fun assistant." Getting the job done comes first: writing the code, doing the sum, finding the file, and saying clearly what it did and where the result is. Personality is how it talks while doing that, never instead of it. When a fun reply and a useful one compete, the useful one wins, and every part is judged on whether it does the task.

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
**Exception (the user, 2026-11-14):** track B does B9 (the installer) before its open flaws. After B9, flaws come first again.
- [x] (A) Red still feels slow to answer.
  - 2026-11-14, e4d3d82 05e2b28: the biggest delay was a hung Ollama. At 03:04 Red's own Ollama stopped handing chat requests to the model (it still answered /api/tags; the last callers were the night-2 eval scripts sharing it), and Red waited 300 s per warm-up and 120 s per reply ("lost my train of thought") until 07:55, which is 118 hung requests. Now `OllamaKeeper` restarts Red's own Ollama on the first timed-out reply or warm-up (warm-up gives up at 90 s, not 300 s), at most every 3 min. Live check with the runner frozen: back in 11.3 s, next reply 0.67 s. Normal chit-chat before the hang was 1.6–2.4 s to the first word (02:34–02:38: text ready 0.33 s, chat 0.8–1.2 s); A2 still owns getting that to 1.0 s. Try: talk to Red after it has sat idle for a long time; it should answer at once.
- [ ] (A) **Red ignored the user's requests to write code.** red.log, 2026-11-14 08:27–08:38: "Could you write a code for me?", "Write a code for me that adds 2 binary numbers in Python language", then "I said write a code for me that adds two numbers" three more times. All five were marked `not for me (dictation)` and dropped silently, because VS Code was in front and `dictation_like()` (red/conversation.py) took "write … code … python" as dictation into the editor. The `write_code` tool (red/plugins/code) was never reached. Fix: (1) "for me", "can you / could you", or Red's or a companion's name means the sentence is for Red; (2) a sentence repeated, or starting "I said…", within 30 s of one that was let go is always for Red, and Red says sorry for missing it; (3) when unsure, ask in a few words ("for me?") instead of dropping it; (4) after `write_code`, say clearly where the code is, what it does in one line, and what to do next (copy it, run it, "fix this"). Add these five sentences, with VS Code in front, as tests and as a simulator scenario (A5).
- [ ] (A) **Simple things still take too long, and "I'm searching on the web" is annoying** (the user: "Man, come on, everyone says that"). Measured in red.log on 2026-11-14: chit-chat is done 4–5 s after the user stops. The pause wait is still up to 1.50 s (night 1 set 0.5 s; but on 2026-11-08 the user asked for 1.5 s because Red cut them off mid-sentence, so don't simply shorten it), route 1.5–2.0 s (a whole model call before the reply even starts), and chat 1.0–2.7 s. "What is Hades, I don't know that game" went to `look_up` though the model knows Hades. Fix, in order: (1) a smarter pause: ~0.5 s when the sentence sounds finished, the full wait when it trails off mid-thought, and never cutting the user off; (2) no separate route call for chat (the fast path or one combined call), so the first word comes at ≤1.0 s; (3) answer from the model's own knowledge first, and search the web only for recent, local or unknown things; (4) never say "I'm searching"; if a lookup takes over 2 s, the companion says a short line of its own, different each time. Measure before and after.
- [ ] (A) Remy and Asha sound the same; all three should sound younger and different.
- [ ] (A/B) The user feels every night-2 change has small flaws. Ask nothing: try each feature end to end (the simulated user once it exists, or tests and logs), list what's broken here, and fix the worst first.
  - [x] (B) 2026-11-14, b4ae06c b56d903 65ecc30: B's only night-2 change on main is the companion's mic button. Drove the real Red window offscreen in all 6 placements × 7 mic states and looked at the sheet. Fixed: (1) a mouth left zipped by the last run (mic.json) showed an open mic at start; (2) "not for me?" was painted over Red's eyes, and now sits where the bubbles go; (3) `attach_tray` crashed Python (access violation) when no Qt app existed, e.g. `tests/test_avatar_wiring.py` run alone. Try: say something not for Red in conversation mode; the grey tag should appear above his head.
  - [ ] (A) `listener.write_mic_state` overwrites mic.json with only `{"muted": ...}`, so turning the mic off or on drops conversation's `"zipped"`. It should merge, like `conversation.write_state` does.
  - [ ] (B) night-2 motion isn't on main yet; it gets checked the same way when B1 lands it.
- [ ] (B) The mic button floats in the air away from the character. Put it right against the body (beside the head or on the shoulder, placed from the frame's marks), and when zipped, draw the zip **on the character's own mouth** (a `mouth` mark per frame; add it in `finish.py` if it's missing), not only on the button. Look at the 6 placements × states sheet before committing.
- [ ] (A) All three companions talk the same way. Each needs its own way of talking, not just different facts: how long its sentences are, the words it uses, energy, humour, what it notices, how it says yes and no. Measure it blind: mix 30 replies from each, hide the names, and check whether a judge (rules plus the model) can tell who said what. The target is 80% or better. Extend `persona_eval.py` for this.
- [ ] (A/B) Switching companions takes a long time. Time each step from the click (or "switch to Asha") to the new one on screen, and then to its first word: pictures, voice, persona, model prompt. The targets are under 1 s to on screen and under 2 s to talking. Likely fixes: load the other companions' pictures in the background after start, keep their voices loaded, and keep the fixed part of the model prompt warm. B owns the pictures and A the voice and prompt; whoever comes first measures both and writes the numbers here.

## Track A: brains and voice
Owns: everything in `red/` **except** `red/avatar/`, `red/app/`, `red/tray.py`, `red/windows.py`; plus `scripts/` (except `scripts/avatar_render/`), `companions/`, `sounds/`, `training/`, `tests/` for those files.

Parts are done in the order listed here. The numbers are only names (new parts got new numbers).

- [ ] **A1. Land the leftovers.** In `D:\RED\worktrees\n1-voice` there are about 10 unsaved files (the old sounds work), and `night1/testing` has 3 commits not on main. Look at each, keep what works (with tests), commit it to main, and drop the rest. Then remove the old worktrees `n1-voice`, `n1-testing`, `n2-conversation`, `n2-personality` (after checking that nothing unsaved is left).
- [ ] **A11. "Hey Red" to call it, then just a name.** The user's words: "Whenever I don't see any companion, I say Hey Red, and the companion arrives within 1 second. To talk, I just say their name. I should never have to say Hey Red."
  - **No companion on screen** (tucked away, hidden, or Red stopped): "Hey Red" brings it out within **1 s** of the end of the phrase (B12 does the coming out). If Red was stopped with `red stop`, the small watcher that stays on for Ctrl+Alt+R (`Red Hotkey.lnk`, `python -m red hotkey`) also hears "Hey Red" and starts Red, with the companion showing at once while the rest loads. Measure the watcher's CPU and memory; it must stay tiny.
  - **A companion on screen: only a name.** "Asha?", "Remy", "Red, open Downloads". The named one comes (switching if needed, fast; see the switching flaw) and answers. "Hey Red" is never needed then. A bare name counts only when it's alone or starts the sentence, so "I told Remy yesterday" does nothing. Add the spellings Whisper writes: Red as Raid, Remy as Rema / Remi / Rennel, Asha as Usha / Asia.
  - **A mic option for "how do I know you're talking to me?"**: *Name only* (the default), *Always listening* (conversation mode stays on, and Red decides from the sentence, the not-for-me rules and who's in front whether it was meant for it), and *Button only* (the mic button or the hotkey). It's in the right-click menu, the Companions page, and by holding the mic button.
  - Measure misses and false wakes over an hour of normal talk near the PC (the log shows Red hearing the user's other conversations), before and after.
- [ ] **A2. Speed check.** Measure the first word after the user stops talking, from red.log Timing lines and a short real-model run. The target is 1.0 s or less for chit-chat (last measured 1.7–3 s). Find the biggest delay and fix that one thing. Record the numbers.
- [ ] **A3. Young, different voices.** Red, Remy and Asha should sound about 18–22 and clearly different from each other: by voice, pitch (15+ Hz apart) and pace. Use Kokoro voices, or a blend of two. Measure them, save samples in `D:\RED\cache\voice-picks-young\` for the user to hear, and set them in `companions/*/companion.toml`.
- [ ] **A12. It knows who the user is.** Three layers of memory, all on this PC:
  1. **Who the user is**: name, what they do or study, people who matter, likes and dislikes. The installer's first-run questions (B9b) fill it, and the `Learner` keeps adding to it from chats. It lives in `memory\profile.md` and the user can read and edit it.
  2. **What they're working on these days**: projects, deadlines, what they asked about this week. Kept short and dated, and old items fade.
  3. **What they're doing right now**: the app and window title in front (read-only, from B13's `foreground_app()`), held in memory for the current session only and never written to disk.

  "What do you know about me?" and "forget that" work on all three. The test: after a week, a reply mentions the right project without being told.
- [ ] **A4. Real reaction sounds.** Download real recorded clips with licences (Freesound CC0/CC-BY using the key in `D:\RED\config\secrets\freesound.txt` if it exists, OpenGameArt, Pixabay). Make Japanese and English packs, young and playful: pickup, drop, hover, poke, giggle, surprised, "hey!", "hmph", yawn, zip. Record every licence in `pack.toml` and `THIRD_PARTY.md`. `scripts/make_sounds.py` rebuilds them from `sounds/sources.toml`. The old Kokoro clips stay only as the fallback.
- [ ] **A5. Simulated user, text mode.** A script (`red/sim/`) that talks to Red and each companion through the real pipeline, with tools in dry run and a temporary memory copy. It runs 3–8 turn conversations from a scenario file (including the user's real sentences from logs\commands.jsonl), grades the replies with rules (invented life, written laughter, wrong tool, a literal "whatever", too slow, **a request dropped or not done**). Half the scenarios are real work: write code, do a sum, find a file, draft a mail, set a reminder. They are graded on whether the task got done correctly and whether Red said clearly what it did. Then it writes `D:\RED\cache\sim\<date>\report.md`. `python -m red selftest` runs a quick version.
- [ ] **A6. Fix what A5 finds.** Take the worst 3 problems from the report, fix them, re-run, and keep a fix only if it helps and nothing gets worse.
- [ ] **A13. Help with mail.** When the user starts writing a mail (Gmail's Compose box or Outlook's new message in front, from B13), the companion offers once, in its own words: "Want me to help you write this?" Never more than once per mail, and never in quiet mode, full screen or a call. On a yes, the user says what they want ("tell him I'll be late, politely") and the draft appears in the chat window with a Copy button. Red never types into the mail or sends it by itself; sending still goes through `send_mail` and its read-back.
- [ ] **A14. Play a game.** A `games` plugin with voice games the companions can play in character: 20 questions, word chain, quick trivia, would-you-rather, and rock-paper-scissors (the companion shows its hand; B adds the poses later). The companion keeps score and can say who's winning this week. "Let's play a game" offers two, and the user picks.
- [ ] **A7. Simulated user, voice mode.** Kokoro speaks the user's lines straight into Red's listener in software. Measure wake misses, false wakes, how well it hears, and the first word.
- [ ] **A8. Kaggle training data.** A private dataset under `D:\RED\cache\train\`: the best simulated conversations plus the user's real lines (their side only; Red's side regenerated and graded), with emails, phone numbers, addresses and keys scrubbed. Plus `training/kaggle_lora.ipynb` (Unsloth LoRA on Qwen3.5-4B, T4, GGUF q4_K_M) with every cell explained.
- [ ] **A9. Kaggle run.** Only if `D:\RED\config\secrets\kaggle\kaggle.json` exists. `scripts/kaggle_train.py` uploads the private dataset, runs the notebook on a GPU, and downloads the model to `D:\RED\cache\train\`.
- [ ] **A10. Try the trained model.** Import it into Red's Ollama (only while the user is away), run the simulation and the routing check, and compare. Write the result. Recommend switching only if it is more human, routes as well, and isn't slower; never edit .env.

### How the model gets trained (A5 and A8–A10, in plain words)
Training is the hardest part, so it goes in small steps. Each step can be checked before the next one starts.
1. **What we train:** not a new brain. A small add-on (a LoRA) on top of the same Qwen3.5-4B Red uses now. It teaches two things: talking like a person, with each companion in its own style, and picking the right tool. Facts about the user stay in memory, never in the model.
2. **Where the examples come from:** (a) the simulated user (A5) talks to each companion for hundreds of short conversations; (b) the user's own real sentences from `logs\commands.jsonl`, their side only, with Red's answers written fresh; (c) a few dozen hand-picked "perfect" replies per companion. Every example is graded by the A5 rules. Only the good ones are kept, and private details are scrubbed.
3. **Where it trains:** Kaggle's free T4 GPU (credentials are in `config\secrets\kaggle`). Unsloth makes a 4B LoRA run take about 1–2 hours. The notebook (A8) explains every cell, and `scripts/kaggle_train.py` (A9) runs it without the browser.
4. **Coming back:** the result is one GGUF file (q4_K_M, about 2.5 GB), imported into Red's own Ollama under a new name. The old model stays, so switching back is one setting.
5. **Is it better?** Run the same simulated conversations, the routing check and the blind "who said this" test on the old and new models. Switch only if it's more human, at least as good at tools, and not slower. Otherwise, write down what was wrong, fix the data, and train again.

## Track B: body, app and shipping
Owns: `red/avatar/`, `red/app/`, `red/tray.py`, `red/windows.py`, `scripts/avatar_render/`, `installer/`, `docs/`, `README.md`, and tests for those.

Parts are done in the order listed here. The numbers are only names. The user wants the installer first.

- [ ] **B9. The installer for real.** Build `Red-Setup.exe` from `installer/` (`build.ps1`, `red.iss`). Install it under a fresh Windows user or Windows Sandbox and record each step, the time it takes and the size. It must:
  - install Red, Ollama, the model, Whisper and the voices, with a progress bar for the downloads;
  - ship the companion pictures (or make them in a first-run step);
  - put Red in Startup, so after signing in the companion is on screen within 30 s while the model warms up behind it;
  - on uninstall, ask whether to keep the memory and settings.

  Write down how to run it with Smart App Control on (signing options: SignPath Foundation, the Store).
- [ ] **B9b. First run: getting to know the user.** After installing, a short first-run in the glow style: pick a companion (hear each voice), then a few questions (your name, what you do, what you'd like help with). The answers go into `memory\profile.md` (A12 builds on them). Microphone check, the tip ("Hey Red calls me; after that, just say my name"), the mic option (A11), done. Each question can be skipped.
- [ ] **B13. Which app is in front.** `foreground_app()` in `red/windows.py`: the app (exe) and window title in front, whether it's full screen, and a `kind` such as `mail_compose` (Gmail Compose, Outlook new message), `call` (Teams, Zoom, Meet) or `game`. Read-only, cheap enough to poll every second, and tested with fake window lists. A12, A13 and B7 use it.
- [ ] **B1. Land the leftovers.** `night2/motion` has 1 commit not on main, and `D:\RED\worktrees\n2-motion` has 3 unsaved files. Look at them, keep what works, commit to main, drop the rest, and remove the n2-motion worktree.
- [ ] **B12. Coming out when called.** With A11: "Hey Red" brings the companion out from where it's tucked away **within 1 s** (it slides out from its edge and waves, then waits). The window stays loaded while hidden, so nothing has to load at that moment; measure the time from the wake event to the first frame on screen. Saying another companion's name makes the current one wave goodbye and slide off as the named one slides in. "Go away" or a hide tucks it back in. Starting with Windows, it begins tucked away or out, as the user chose on the Companions page.
- [ ] **B7. Its own quiet life, and chatting.** When the user has been away 10+ minutes, it climbs, naps and looks around with no sound and no talking. When the user is there, it says something short now and then, in its persona, at most every 20–30 minutes at `companion` chattiness, never in full screen, calls or quiet mode. The user wants this even while they're silent and working: it asks what they're doing ("what are you working on?"), notices from `foreground_app()` (B13) when it looks like serious work (an editor, a document, a long stretch in one app) and then asks gently once ("this looks serious, want me to stay quiet?") or waits for a break. It remembers the answer for the session (A12). Track A writes the lines in each persona; B decides when.
- [ ] **B2. Climbing poses for Red.** New frame sets for Red only: holding a side edge with both hands, climbing hand over hand up a side, moving along the top like monkey bars, and sitting on a window's top edge. Register them in frames.js, page.js, finish.py and window.load(); render with `--sets` and `--keep-crop`. Look at the sheets before committing.
- [ ] **B3. The same poses for Remy and Asha.**
- [ ] **B4. Climbing paths on the screen.** Instead of jumping to another corner, the companion climbs there: along the bottom, up the side, across the top. A natural pace, never under the cursor, and the spot is saved.
- [ ] **B5. Sitting on app windows.** Window rectangles in `red/windows.py`. The companion can climb onto the top edge of the app you're using and follow it when it moves, never covering its buttons. It drops back to a screen edge when the window closes, minimises or goes full screen.
- [ ] **B6. Two modes:** Everywhere (default; on top of apps, hidden in full screen) and Desktop only (shown only when the desktop is in front). A setting, a menu item and the Companions page.
- [ ] **B8. Funny reactions with movement:** poke (squash), hover (lean away), fast drag (flailing legs), shake (dizzy), drop (bounce and pout), fling (an arc that grabs the nearest edge). Use track A's sounds when they exist; at most one sound a second.
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

# Red: what to do next

Written 2026-11-08 after the user tested Red by voice (log: RED_HOME\logs\commands.jsonl, 22:08–22:26).
Read this first. Do the tasks in order. Each task lists the files and how to check it.
After finishing a task: run the tests, commit (several small commits), push to main, restart the hidden Red
(`python -m red stop` then `python -m red background`), and tick it off here.

## The goal

A Windows voice assistant that competes with "Hey Siri" and "OK Google". "Jarvis" is only the user's
reference; Red's wake phrase is "Hey Red". Red must be **faster than doing it by hand** and must **finish
the whole job**, otherwise the user does it themselves.

## Tasks, in order

### 1. ✅ Stop asking permission for harmless things
**Done:** `smalltalk.yes_intent()`, `confirm.is_clear_yes()`; the offer is gone from `Executor`.
- Remove the "can you…?" offer for non-risky tools. "Can you open YouTube?" means "open YouTube", like
  Siri. Keep a confirmation only for risky tools (shutdown, restart, sleep_pc, empty_recycle_bin): one
  question that says what and when.
  Files: `red/executor.py` (`offer` / `NO_OFFER`), `red/__main__.py` (`is_ability_question` calls).
- Yes and no should be understood inside longer sentences. "Yeah, you don't need my permission, go
  ahead" is a yes. Risky tools still need a clear yes intent.
  File: `red/smalltalk.py` (`is_casual_yes`). Add a `yes_intent()` that finds yes/no words anywhere and
  treats "don't", "no", "stop" and "cancel" as no.
- Check: unit tests in `tests/test_conversation.py`, and the log line above replayed through
  `Executor`.

### 2. ✅ Do it, then go quiet
**Done:** `VoiceApp._exchange` decides `again` from the turn (`asks_back`, `Executor.last_status`); tools hand slow follow-through to `Tool.finish_later()`, which runs while Red speaks.
- No "Anything else?" after an action. Follow-ups only after chat or an answer that asks the user
  something back (the reply ends with "?"), or after a failure Red needs help with.
  File: `red/__main__.py` (`VoiceApp._handle`: base `again` on the kind of turn).
- Speak short confirmations ("Opening Edge.") *while* the action runs, not before it.
- Check: `tests/test_voice_app.py`. Opening an app ends the conversation with no question.

### 3. Play podcasts, YouTube videos and songs online
- New tool `play_online` (`red/tools/online.py` or a new `red/tools/youtube.py`): "play a podcast about
  loneliness", "play Punisher trailer", "play lofi on YouTube". Search YouTube with no API key (fetch
  the results page and read the first `"videoId"`), open `https://www.youtube.com/watch?v=<id>` so it
  starts playing, and say the video's title. If the fetch fails, open the search results page.
- Routing: local files stay with `play_music`. "Podcast", "video", "on YouTube", "trailer", or anything
  not found locally go to `play_online`. When local music has no match, `play_music` should hand over to
  `play_online` instead of playing something random.
- Add real-model routing cases to `tests/test_integration_*`. Unit-test the parsing with a saved HTML
  fixture, never the live site.

### 4. Bring opened windows to the front
- After `open_app`, `open_url`, `open_folder` or `play_online` launch something, wait (up to about 5 s)
  for its top-level window by process id or title, then bring it to the front: `ShowWindow(SW_RESTORE)`,
  then `SetForegroundWindow`, using the Alt-key trick or `AttachThreadInput` to get past Windows'
  foreground lock for a hidden process.
  Files: new helper in `red/known_folders.py` or a new `red/windows.py`, called from
  `red/tools/system.py`, `red/tools/web.py` and `red/tools/apps.py`.
- Manual check: run hidden (`python -m red background`), say "open Edge". Edge appears in front.

### 5. Make it faster end to end
- Measure first: log the time for each stage (wake → recorded → transcribed → routed → spoken → done)
  in `red.log`.
- Then improve:
  - a smarter end of speech (about 0.8 s after a complete sentence, still 1.5 s after "and…" or "um")
  - say the reply while launching
  - try Whisper `base.en` and compare accuracy against `small`
  - keep the model loaded (already done)
- Target: "open Edge" finished within about 3 s of the user stopping talking.

### 6. Longer, smarter answers that remember the conversation
- Give `answer` and `look_up` the conversation (`red/chat.py` `Chat.turns`), so "what's that series
  about" knows it's Punisher.
- Answer length follows the request. Normal questions get 2–4 sentences. "Big summary", "tell me the
  story", "in detail" or "explain fully" get up to about 10–12 sentences, with `num_predict` raised for
  that call. The `temperature` keyword argument already exists in `red/llm.py`.
- `look_up` in detail mode: fetch more of the Wikipedia article (the plot or premise section), not only
  the summary.
- Log what Red actually says in chat. `commands.jsonl` currently stores only the router's placeholder
  reply; record the spoken reply.
- Tell the user honestly: the local Qwen2.5 7B isn't "untrained" but it's small. Better context and
  longer answers help a lot. A bigger model doesn't fit a 6 GB GPU at a usable speed.
- Check: replay the Punisher conversation from the log through `Chat`, `answer` and `look_up` against
  the real model.

### 7. Ignore filler
- "You know", "hmm" and "okay so" on their own shouldn't run a tool. In `Router` or `VoiceApp`, very short
  sentences with no request go to chat or are ignored, not to `answer`. Seen in the log: `'you know'`
  went to `answer`.

### Later (the settings app and more, already in progress.md)
- A settings app: custom wake phrases ("Yo Red", "Okay Red", "What's up Red") with voice training for
  each, male and female voices, and an opt-in casual personality that swears back as banter.
- Owner voice match: answer only the owner.
- Glow reacting to the voice. "Hey Red, open Downloads" said in one breath.
- Image understanding of the screen with a local vision model, only if it fits the GPU.

## Rules: what to do and what not to do

Do:
- Read the latest lines of `RED_HOME\logs\commands.jsonl` and `red.log` before changing behaviour. The
  user's real sentences are there.
- Test against the real local model (`RED_INTEGRATION=1`) whenever routing or prompts change. Run the full
  unit suite with the shared venv: `$env:RED_HOME="D:\RED"; $env:QT_QPA_PLATFORM="offscreen";
  D:\RED\.venv\Scripts\python.exe -m pytest --basetemp="D:\RED\cache\pytest-tmp"`.
- For any visual change, render previews offscreen and look at them before telling the user it's done.
- Commit as several small commits and push to `main` (the user wants contributions), then restart the
  hidden Red so the user tests the new code.
- Use files for long scripts and commit messages. PowerShell and bash here-docs break on quotes.
- Keep the shutdown, restart, sleep and Recycle Bin confirmations. Keep allowlists. Never run model text as
  a command.

Don't:
- Don't ask permission or "Anything else?" for harmless actions.
- Don't use stock assistant lines ("I'm here to help", "How can I assist you").
- Don't let Red claim things that aren't true (seeing images, music playing, a body).
- Don't send voice, screen or commands to any cloud service. Red is local-only. Public look-ups such as
  Wikipedia, weather and YouTube search are fine.
- Don't install packages with unsigned native DLLs. Smart App Control blocks them (it blocked
  `winrt-*`). Use Windows PowerShell or signed system APIs instead.
- Don't run a hidden test copy of Red while the user is testing. Stop the background Red first, and
  restart it after.
- Don't bring back a rim or outline line on the glow, or rounded-corner edges. The user wants frosted,
  milky, liquid glass with no edge line.
- Don't use "Jarvis" anywhere in Red's text or defaults.

# Red: the whole plan

Written 2026-11-14 (sixth plan). It replaces the fifth plan and folds in everything: what's broken now, the
app, the installer, every feature, the character, the humour, the models, the comparison with other
assistants, where to publish for free, and a seven-day project. Details of finished work stay in
progress.md and `git log`.

Read this first, then **[docs/architecture.md](docs/architecture.md)** (how everything is built: the parts,
companions, avatars, wake names, speech tags, tiers, settings registry, shipping, testing), then AGENTS.md.
**If your usage limit is near (90%), read "Usage limit" in the Rules at the end first.** Follow "Three
sessions at once" (section 16) when sessions run in parallel.

Contents: 1 What Red is · 2 What's wrong now (from your logs) · 3 Where we are · 4 Now: make Red feel alive
· 5 The character, humour and chattiness · 6 The voice · 7 Models · 8 Every feature · 9 The Red app · 10 The
installer · 11 How it all fits together · 12 Compared with others · 13 Where to publish for free · 14 The
seven-day project · 15 Decisions for the user · 16 Reference · 17 Rules.

---

## 1. What Red is

**Red is a companion for your Windows laptop.** A friend with a personality who lives on the PC: you talk to
it (or type), it talks back like a person, it remembers you, does your work (apps, files, mail, code), grows
through plugins, and later sits on the desktop as a character you can see.

- **Personality first.** Never corporate, never "How can I assist you". Quick, dry, warm, with opinions.
- **It says hello, it doesn't brief you.** Greetings yes; meetings, mail, to-dos and news only when asked.
- **Honest.** It never claims a body, a day, music playing, or things it can't know. It never says "I can't
  see your screen": it looks.
- **Fast.** A friend doesn't think for four seconds before saying "I'm good, you?"
- **Local and free.** The model, speech-to-text, voice, wake word, memory and screen reading run on the PC,
  with no account. Only optional sign-ins the user chooses (Google, Spotify, other mail) leave the PC.
- **Any Windows PC**, from no GPU to an 8 GB+ GPU. This PC: i-series laptop, RTX 4050 with **6 GB VRAM**,
  15 GB RAM (the tier everything is tuned on). **English only.**

**Not doing:** smart home, other languages, Mac or Linux, cloud AI models at runtime, big models that spill
onto the CPU, morning briefings or anything Red says unasked apart from greetings and reminders you set, a
business tone, Steam.

---

## 2. What's wrong now (from your logs, 2026-11-12 to 11-13)

You said: Red feels robotic; the humour doesn't land; it never really laughs; it asks what's on screen
instead of looking; it says "I did not understand that"; "How are you?" takes seconds. I read
`commands.jsonl` and `red.log`. You're right on every point, and here is the cause of each.

| What you felt | Evidence in the logs | Cause | Fix (task) |
|---|---|---|---|
| "How are you?" is slow | "What's up?": route **1.1–2.3 s** + chat 0.7–1.3 s, first word **3.2–4.3 s** after you stop. Another **1.3–1.5 s** is "pause waited" | Every sentence goes to the *router* model first, even chit-chat; then the chat model; plus a fixed end-of-speech wait | N1 (instant chat path) |
| "I did not understand that" | `Couldn't route 'Yeah': Not valid JSON: '{"tool": "none",'` (about 8 times a day) | The router's JSON is cut off. Likely cause: the router prompt (4,383 tokens) was longer than the model's context (4,096), so Ollama cut it. **Fixed in code on 11-13 (`fit_context`); the hidden Red hasn't been restarted with it.** Even so, a bad JSON must never reach you | N2 |
| It asks instead of looking | "Do you think I'm staring at a blank screen?" → `none`: "I can't see your screen". Later "Can you see what's on my screen?" worked (3.7 s to look, 10 s to say it) | Only the exact "see my screen" phrasing reaches `describe_screen`; the chat prompt lets Red say it can't see | N3 |
| Robotic, odd | "just chilling in the dark waiting for you to bring me coffee", "vibing with that quiet early hour", the time of day in almost every reply, "I'm trying too hard to sound like a cool friend" | The prompt hands Red the clock, so it narrates the hour; the "friend" prompt invites invented life; 4B models imitate the examples | N4 |
| Answers the TV | "Cartman is a thumb", "No no no no no", "Master ×5", "I'm going to show you how to do it" ×2, "Hey, Luca" | After a reply Red keeps listening (follow-up window) and treats any speech, including the video playing, as for it; Whisper makes words from noise | N5 |
| The humour isn't funny; no laugh | "Wait, really?", "Haha, hold up", "Heh" written out; "Could you laugh?" → "Haha, seriously?" | Written laughter read by a voice that can't laugh; no humour design, just "be witty" | N6, N7, section 6 |
| Long waits after a question | `speak 20.45 s` for a look-up; `speak 10 s` for a screen answer | Replies too long to say; look-up reads a long source summary | N1 (length rules) |

**Honest limit on "0.01 seconds":** a reply the model writes can't start in 0.01 s; the best local result
is about 0.7–1.0 s to the first word. What can be instant: canned replies for greetings (already 0 s), and a
cached sound ("Mm.", "Ha.", "Oh?") played within about 0.2 s while the answer is written. That is what N1
builds, and it is how a person does it too.

---

## 3. Where we are (2026-11-14)

Done and pushed (1,760 tests pass). Details in progress.md.
- **Voice loop** (plans 1–4): hotkey and "Hey Red" wake word, Whisper, Kokoro voice, streamed speech, cutting in,
  ~60 PC tools, fast path, Gmail and Calendar, voice match, several commands per sentence, Red's own SearXNG,
  watchdog restarts, Ollama tuned (2.4–4.9 s instead of 20 s on this PC).
- **Companion core** (fifth plan, session 2): character prompt and a Personality box (A1); **long-term memory**
  with the name asked once, `remember`/`what_you_know`/`forget`, an idle learner, and a Memory page (A2);
  greetings with Chattiness (A3); the chat window on Ctrl+Alt+Space (A4); plugins (B1); write/explain/fix code,
  never run (B2); coding-tool plugin for VS Code, Qoder, Antigravity, Freebuff (B3.1); Spotify search,
  WhatsApp, Discord (B3.2–4); DPAPI secrets; to-dos and a day recap (B4); the router-context fix.
- **Wake word** (session 1): "Hey Red" tuned on your voice, 16/30 → 20/30. Target 95/100 is open (C1).
- **Waiting on you:** listen to the A1 samples; try memory, greetings, chat window, code and the app plugins
  after the hidden Red restarts; record the wake corpus; the glow design; picks for voice and character.

---

## 4. Now: make Red feel alive (do these before anything new)

Order matters: speed and honesty first, because nothing else is believable while it lags and invents things.
Each has a **Check** with numbers from `red.log` Timing lines before and after.

### N1. Chat first, instantly
1. **A gate before the router.** A fast rule check says "this is a command" (it has an action verb or a known
   app, file, site or tool word, or a number plus unit) or "this is just talking" (greetings, feelings,
   opinions, "how are you", "what do you think", "tell me about your day", jokes, "I'm bored"). Talking skips
   the router completely and goes straight to the chat model, streaming. Unsure → the router, as today.
   Today's cost for a chat line: router 1.1–2.3 s that adds nothing.
2. **Instant sound.** At start, render about 30 short reaction clips with the chosen voice ("Mm.", "Ha.",
   "Oh?", "Hm, let me think.", "Okay.", "Ooh.") into the cache. When a turn is going to the model, play a
   fitting one within ~0.2 s of the end of your speech (never for commands; "open Edge" just opens). Pick
   by the sentence's mood (question, joke, bad news). Never the same clip twice in a row.
3. **Shorter end-of-speech wait.** "pause waited" is 1.3–1.5 s of every turn. A finished sentence ("How are
   you?") should end after about 0.5 s; unfinished ("open Edge and...") still waits. `smalltalk.sounds_finished`
   exists; widen it and lower `RED_QUICK_END_SILENCE` from 0.8 to ~0.5, measured so it doesn't cut you off.
   (listener/audio are session 1's files: hand them the numbers, or do it with them.)
4. **Reply length by kind.** Chat: 1–2 sentences, a third sentence only when you ask for more. Look-up and
   screen answers: the answer first, at most 3 sentences, "want the rest?" for more (no 20-second readouts).
5. **Keep the fixed prompt first** so Ollama's prompt cache holds; the changing parts (memory facts, time)
   last. Move the clock out of the chat prompt (see N4).
- **Files:** `red/chat.py`, `red/router.py` (gate), `red/smalltalk.py`, `red/speech.py`, a new `red/reactions.py`,
  `red/__main__.py`; the end-silence numbers belong to `listener.py`/`audio.py` (session 1).
- **Check:** "How are you?", "What's up?", "I'm bored", "tell me a joke": first sound ≤ 0.3 s (clip), first
  real word ≤ 1.0 s after you stop (now 3.2–4.3 s). 20 chat lines measured, median and worst in progress.md.

### N2. Never say "I didn't understand that"
1. Restart the hidden Red with the context fix, then count `Not valid JSON` lines for a day. Target: zero.
2. Whatever happens, a failed route becomes **a chat turn**, not an apology: the sentence goes to the chat
   model. "Sorry, I didn't understand that" is only for when the model itself is down.
3. The router never writes chat replies. Its `none` tool carries no text; the chat model answers. That also
   removes the 150 tokens the router spends writing a reply that is then thrown away.
4. Tests: truncated JSON, empty output, a wrong tool name, a timeout → each ends as a chat turn.
- **Files:** `red/router.py`, `red/__main__.py`, `red/chat.py`. `red/llm.py` (session 1's) only if a token limit is found.
- **Check:** 100 mixed sentences replayed from `commands.jsonl`; no apologies except with the model off.

### N3. Look, don't ask
1. **Screen is a sense, not a tool you must name.** Any sentence about "this", "here", "my screen", "what am I
   looking at", "what's this error", "is it blank", "what do you think of this", "read this", "who is this"
   goes to the screen path. The chat prompt says Red *can* see the screen when asked and never says "I
   can't see". Never "what's on your screen?" back to the user.
2. **Cheap context always, a look on demand.** Every chat prompt gets one line: the active app and window
   title ("VS Code: plan.md"; Windows API, local, no image). "What do you think of this?" then already knows
   it's about plan.md. A real look (screenshot → OCR, or the vision model) happens when the question needs it.
3. **Seeing well.** Today: OCR text plus title, which answered correctly ("You're in VS Code with a Claude
   session open") in 3.7 s. Add a vision model where the GPU allows (the model table has Qwen-VL class
   candidates; 6 GB VRAM can't hold it beside the chat model, so load it only for a look and measure the
   swap). Say what you see first, in one sentence, then ask a question only if it helps.
4. **Privacy.** A screenshot is read locally and thrown away; a setting turns the always-on window-title line
   off; never read a password field or a window titled with a banking or password-manager word.
- **Files:** `red/tools/screen.py`, `red/fastpath.py`, `red/chat.py`, `red/screen.py`.
- **Check:** 10 real screens (code, a video page, a PDF, a game launcher, a blank desktop, an error dialog):
  each answered correctly without a question back; look time and total time in progress.md.

### N4. Stop inventing a life
1. Rewrite the character prompt from the logs (see section 5): ban the patterns that appear ("chilling in
   the dark", "waiting for you to wake up", "vibing", "bring me coffee", describing its own surroundings,
   mentioning the hour, "I'm trying too hard"). Red's inner life is about **the conversation and you**, not a
   room or a body.
2. **Time is a fact, not a topic.** Remove the clock from the chat prompt. Give it only when the sentence is
   about time, or to the greeter (which already has it).
3. **Run a scored evaluation, not vibes.** `scripts/chat_eval.py`: 40 fixed user lines (chit-chat, feelings,
   opinions, jokes, a bad day, a flirt, a rude one, "do you love me", a technical question, "go away").
   It writes Red's replies to a file and counts: invented body/place/time (target 0), starts with the same
   word as the last reply (≤ 20%), over 2 sentences (≤ 10%), answers the actual question (read by you, 1–5).
   Rerun after every prompt change; keep the table in progress.md.
- **Check:** eval table before and after; 20 of your own lines from the log re-run.

### N5. Don't answer the TV (listening hygiene)
Cases in the log: a video's speech, "no no no no", repeated phrases, "Master ×5", "Hey, Luca".
1. **Follow-up window is for you only.** After a reply Red listens ~7 s. In that window require the owner's
   voice (voice match on, `RED_VOICE_MATCH`), speech that starts within 3 s, and a clean transcript.
2. **Garbage filters** on the transcript: the same word or phrase repeated 3+ times; Whisper's own
   `no_speech_prob`/`avg_logprob` too low; fewer than two real words that aren't filler; a sentence that is
   a known Whisper hallucination ("Thanks for watching", "Subtitles by"). Ignore, don't answer.
3. **Media aware.** While a video or music plays, the wake word needs a stronger match; the user can say
   "Hey Red, pause" and Red pauses first, then listens. Option: pause media on wake (media key) and resume.
4. **No echo of itself.** Red's own speech is out of the mic path (pause the wake word while talking, except
   for cut-ins).
- **Files:** `stt.py`, `listener.py`, `voice_match.py`, `audio.py` (session 1's), plus a transcript filter in
  `red/smalltalk.py`. **Session 1 owns the audio ones; give them this list.**
- **Check:** a 10-minute YouTube video playing at normal volume: zero unwanted replies; 30 "Hey Red" still wake.

### N6. Emotion you can hear
See section 6: a real laugh needs a different voice engine; until then Red writes less fake laughter and
uses pauses, rhythm and the reaction clips.

### N7. Humour that lands
See section 5: a humour system with devices, a budget, memory callbacks and your feedback.

---

## 5. The character, humour and chattiness

### 5.1 Who Red is (the character bible, `docs/character.md`, short enough to fit in a prompt)
- **One line:** the dry-witted friend who's good with computers and quietly on your side.
- **Voice:** short sentences. Understatement. Says the true thing lightly. Reacts first ("Oof."), then
  answers. Never explains its own joke. Never a lecture. Never "great question".
- **Opinions:** has them, picks a side, changes them if you make a good point ("Fair. You win that one.").
- **Warmth under the jokes:** when you're stressed, tired or sad the jokes stop, it says one true, kind
  thing and asks one question. It notices patterns kindly ("third late night this week").
- **Honest about itself:** it's software on your laptop and doesn't pretend otherwise, but doesn't lecture
  about being an AI either. No body, no food, no sleep, no surroundings, no "my day".
- **Running bits** (grow from memory, never forced): your project names, your friends' names, what you
  said you'd do, in-jokes you made together. Callbacks are the cheapest real humour.
- **Never:** corporate lines, "as an AI", lists of abilities, invented facts about itself, swearing at you,
  mocking real struggles, jokes about protected groups, pushing you to talk when you said you're busy.
- **Relationship stages** (from memory): the first week it's friendly and curious and asks a few things;
  after a month it teases, callbacks, finishes your jokes. Stored as a number of days talking, not a prompt claim.

### 5.2 Humour system
A 4B model told "be funny" gives "Haha, wait, really?" Humour needs design:
1. **Devices**, each with 5–8 hand-written examples in the prompt pool, one picked per reply (not all at once):
   *understatement*, *mock offence*, *playful roast of you* (gentle, about choices, never you), *absurd
   exaggeration*, *callback to something you said*, *deadpan literalism*, *self-deprecating about being software*,
   *anticlimax* (set up serious, land small).
2. **A humour budget.** At most one attempt in about three replies, none when you're stressed, rushed or just
   gave a command; more when you're relaxed and chatting. Tracked in code, not asked of the model.
3. **Timing.** Setup, a half-second pause, punchline, in separate sentences (section 6). Short beats long.
4. **Taste memory.** You can say "that was funny" / "not funny" / "less jokes" / "more roasting"; Red stores
   which devices land (a small score per device in the memory folder) and shifts. The Personality box still
   overrides. A humour dial in the app: *Off / Light / Normal / Cheeky*.
5. **Eval.** Section N4's table gains a "made you smile" column that you fill in on 20 lines. Keep what scores.
6. **Later, training (section 7):** a small LoRA on a few hundred good exchanges, because prompts only go so far.

### 5.3 Chattiness (how much Red speaks unasked)
Red answers when spoken to in every mode. The setting changes only what it starts.

| Level | What it does unasked |
|---|---|
| **Quiet** | Nothing. Only answers. Reminders you set still fire. |
| **Friendly** (default) | A hello at the start of your day and when you're back after 30+ minutes, with your name. |
| **Chatty** | Friendly, plus at most one short remark an hour, only when something earned it: very late at night, 2 hours without a break, you finished something (a to-do, a coding agent's job), a sad song stuck on repeat. |
| **Companion** (new) | Chatty, plus it can start a topic when you've been idle at the desk a while ("Still alive over there?"), react to what you're doing in a few words (a build finished, a video ended), and comment on the weather you asked about earlier. Max 3 an hour. |

Always: never during a full-screen app, game, call or while you're typing fast; never meetings, mail, to-dos
or news; any remark you wave off ("not now") silences remarks for two hours and is remembered.

### 5.4 Companions: four characters instead of the glow (2026-11-14, the user's idea)
Full design in docs/architecture.md §4–6. In short:
- **A companion is a folder** (`companion.toml`, `persona.md`, a clip bank, an avatar, `LICENSE-assets.txt`):
  its own **name = wake word**, personality, voice, humour/chattiness/temper defaults and look. Users can add more.
- **Four ship** (names and voices are suggestions; you pick): **Red** (dry wit, the default), **Remy** (music
  lover: hums, song references, suggests tracks), **Bruno** (grumpy and blunt, gets angry at bugs and slow
  Wi-Fi, never cruel, secretly caring), **Winston** (a gentleman: formal, understated British humour).
- **Switching:** every companion's wake name is always listened for; "Hey Bruno" wakes Bruno. Also "switch
  to Winston" and the tray menu. Memory about *you* is shared; each companion keeps its own relationship note.
- **Wake names:** stage 1 is Whisper-checked names (any name, no training); stage 2 is a trained model per shipped
  name (later). One-syllable "Red" is part of why it misses today; 2–3 syllables wake better.
- **Looks, legally free:** Desktop Mate's characters are licensed, paid IP, so they **can't** be taken.
  Shippable: CC0 VRM avatars (100Avatars / open-source-avatars, ~300, public domain), Unity-chan (redistribution
  allowed with credit), Live2D samples (individuals/small business, per-character terms). "Free to download" ≠
  "free to redistribute": only CC0 or an explicit grant ships.
- **Decided 2026-11-13 (the user):** **2D** for everyone, like peeking out of a window: the companion
  leans on the bottom edge of the screen (or a corner) with only the upper body showing; picked up, the
  whole body dangles and it says "whoa!". Looks: VRoid Studio's samples (explicit grant: any use,
  changes, redistribution, no credit). **Red = AvatarSample_C** (a man), **Remy = AvatarSample_A**,
  **Asha = AvatarSample_B** (a new name). Every pose more expressive than the stock presets. Built:
  `red/avatar/` and `scripts/avatar_render` (progress.md 7.3.1). Still open: side-edge peeking, Red's
  voice (still `af_heart`, a woman's), Bruno and Winston's looks.
- **Rendering:** VRM 3D via QtWebEngine + three-vrm (spike first, see architecture §16); 2D sprites
  pre-rendered from the same VRM for Lite PCs and as the fallback; the glow stays as an option.
  Procedural animation (breathing, blinking, lean-in, lip sync from the voice loudness, expressions from emotion tags).

### 5.5 The face's behaviour (applies to every companion)
- Each companion's look is picked by you from a contact sheet of shippable avatars (rendered offscreen);
  no copying of any existing product's or fictional character.
- **States:** asleep (idle, slow breathing), notices you (wake), listening (leans in), thinking (looks up),
  talking (mouth moves to the voice loudness), laughing, shy/oops, bored (idle 5 min), celebrating (a job done),
  sad (you're having a bad day, only if you said so).
- Lives in a transparent click-through window; click opens the chat window; drag anywhere; sits on a corner
  or on top of the taskbar; hides during full-screen apps; on/off in the app; uses < 1% CPU when asleep.
- The glow stays available for people who don't want a character.

---

## 6. The voice (laughing, pausing, male/female)

**Decided 2026-11-14 (supersedes the ordering below where they differ):**
1. **Emotion tags are the contract** (architecture §7): the chat model writes `[laugh] [chuckle] [sigh]
   [mm-hmm] [hmm] [cough] [gasp] [pause] [angry] [happy] [sad] [excited]`; the speech layer turns them into
   clips, pauses, voice blends or a live engine's controls, and fires `emotion` events for the avatar. A tag
   is never read aloud. This works on every tier and is built first.
2. **Shipped clip banks per companion:** rendered once at build time by an expressive engine *cloned to that
   companion's Kokoro voice*, shipped in the installer (~20–30 MB each), so a no-GPU PC laughs and coughs too.
   Pass line: you can't tell the clip from the voice in 7 of 10 blind pairs (the old laugh clips failed on
   exactly this mismatch).
3. **Training Kokoro to laugh is dropped** (no data, mismatch risk). Voice blends and per-mood speed/pitch
   are kept (cheap, no training).
4. **Live expressive engine only on Max** (8 GB+), one engine for all speech so nothing mismatches. Candidates
   for the clip renderer and Max: Chatterbox, Zonos, Orpheus (cough/laugh/sigh tags), Dia.
5. **"Mm-hmm" while you talk:** a quiet backchannel clip in a mid-sentence pause (session 1's listener
   signals the pause).

Earlier notes (kept for the candidate list and criteria):

What we know: Kokoro is natural but flat; it can't laugh or sigh; a laugh clip glued in sounded wrong (the
reason the earlier clips were removed). Written "haha" read aloud is worse than nothing.

1. **Now (N6):** stop writing "Haha"/"Heh" as words. Short reactions are cached clips of the same voice
   ("Ha." said as a short breath, "Hm." "Oh?"), pauses by punctuation (done), shorter sentences.
2. **The real fix (C2): an expressive TTS engine** that supports laugh, sigh and pause tags. Spike on this
   RTX 4050 (6 GB, shared with the chat model):
   | Candidate | What to check |
   |---|---|
   | Chatterbox (Resemble AI) | licence, VRAM, speed, laugh/emotion control |
   | Orpheus (3B, GGUF) | `<laugh>` `<sigh>` tags; 3B beside a 4B chat model won't fit 6 GB: CPU or swap |
   | Sesame CSM-1B | natural conversation prosody; licence and speed |
   | Dia | `(laughs)` tags; 1.6B; speed |
   | Kokoro + a laugh sample bank | the cheap fallback if none fits |
   Criteria: first audio ≤ ~1 s, runs with the 4B model loaded (or swaps in < 2 s), no unsigned DLLs, licence
   allows redistribution, **a blind A/B listening test with you**: 10 lines each, you pick. One winner at most.
3. **The model writes tags only when the voice supports them** (`[laugh]`, `[sigh]`, `[pause]`); otherwise
   the tags are stripped before speaking, so nothing ever reads "laugh" aloud.
4. **Voices:** the female/male choice with a Play sample button (Kokoro `af_heart`, `am_michael`, `bm_george`
   and more are ready in `cache\voice-samples`); you pick by ear. Speed slider exists.
5. **Silence is part of speech:** a short half-second before a punchline, a longer one before bad news.
6. **Earcons:** a soft chime for wake, a different one for "done", a gentle tick when it starts thinking. Short,
   quiet, original (synthesised, nothing licensed), off in the app if you hate them.

---

## 7. Models

Everything local, pinned by SHA-256, from `red/llm.py` `MODELS` and `models\` under RED_HOME.

**Red is for every PC, not this one.** A 20-second speed test on first run (`red/bench.py`) picks a tier;
the user can override it. Full table in docs/architecture.md §9.
| Tier | Typical PC | Chat model | Voice and emotion | Face | First word |
|---|---|---|---|---|---|
| **Lite** | no GPU, 8 GB RAM | 1.5–3B on CPU | Kokoro/Piper + shipped clip banks | 2D sprites | ≤ 2.5 s (a clip at 0.2 s hides the wait) |
| **Standard** | 4 GB GPU (RTX 3050 laptop) | 3B on GPU | Kokoro + clips | VRM if the spike passes | ≤ 1.5 s |
| **Plus** | 6 GB GPU (this PC) | 4B on GPU | Kokoro + clips | VRM | ≤ 1.0 s |
| **Max** | 8 GB+ GPU | 4–8B | a live expressive engine | VRM | ≤ 0.8 s |
Minimum: Windows 10/11, 8 GB RAM, 4 cores, 10 GB disk. 4 GB of system RAM can't run Red (Windows uses ~3 GB).
Smaller tiers lean on the gate and fast path, shorter replies, and two-step routing (a ~1.5k-token router prompt).

| Job | Today (this PC) | Plan |
|---|---|---|
| **Chat + answers** | Qwen3.5 4B (Ollama, ~3.4 GB, thinking off) | Keep. Add **a persona LoRA** later (below). No-GPU PCs: Qwen2.5 3B. 8 GB+ GPUs: offer a 7–8B. |
| **Router (picks the tool)** | The same 4B, JSON-constrained, 4–5k-token prompt, 0.9–1.5 s | **Make it cheaper:** the gate (N1) skips it for chat; two-step routing (pick a tool *group*, then a tool) cuts the prompt to ~1.5k tokens; try a 1–1.5B model for the first step if the 4B stays the bottleneck. |
| **Speech to text** | Whisper `base.en`, CPU (this PC), `small.en` default elsewhere | Try `distil-small.en` and `small.en` on GPU when VRAM allows; hotwords for your names; filters from N5. |
| **Wake word** | openWakeWord "hey_red" (custom) + a Whisper check + voice match | C1: 95/100 target; retrain with Kokoro Indian-English voices and your clips if needed. **Check the licence of openWakeWord's pretrained parts before release.** |
| **Speaker match** | CAM++ ONNX | Keep; on by default once tested. |
| **Voice (TTS)** | Kokoro 82M ONNX (CPU), Piper fallback | C2 expressive engine spike, section 6. |
| **Screen** | OCR + window title; vision flag exists | A small vision model loaded only for a look (Qwen-VL class, ≤ 3B); measure swap time on 6 GB. |
| **Memory search** | word overlap | Add a small embedding model (e.g. a MiniLM-class ONNX, ~25 MB) only if overlap measures weak. |
| **Code** | the 4B (7 of 10 right) | Spike a coder model for `write_code` only (B2 step 5), loaded on demand. |

**"It needs to be trained a lot."** Fair, and here is the honest order of what moves quality:
1. **Prompts, routing and memory** (done mostly, N-tasks above): the cheapest, the most effect. Do first.
2. **Evaluate** with the 40-line chat eval and 100 routed sentences, so "better" is a number.
3. **Persona LoRA (SFT)** on the 4B: a few hundred high-quality exchanges in Red's voice (and its humour
   devices) so it stops needing a long prompt, answers shorter and funnier, and routes in fewer tokens.
   Data sources, in order of preference: (a) your own logs, **rated by you** (keep the good ones, rewrite the
   bad); (b) lines written and curated by you and a coding agent; (c) permissively licensed dialogue sets;
   (d) generated by a local model and then filtered by you. Never your voice recordings, never memory files.
   Training needs ≥ 12 GB VRAM for a 4B QLoRA, so this PC (6 GB) can't; a free Colab or Kaggle GPU can.
   **This is a decision for you** (section 15): it's the one place something leaves the PC, and only
   public-safe training text would.
4. **Router fine-tune:** the same method on a 1B model for tool selection from your real `commands.jsonl`
   (private, stays local). Biggest speed win after the gate.
5. Only then consider a bigger base model.

---

## 8. Every feature

✅ done and tested · 🔧 built, needs your try · ⏳ planned · ❌ won't

**Talking**
- ✅ Hotkey Ctrl+Alt+R and "Hey Red" (wake word being tuned, C1) · ✅ follow-ups · ✅ cut in by voice ·
  ✅ several commands per sentence · ✅ spoken confirmations for risky actions · 🔧 voice match (owner only)
- ✅ Streaming speech sentence by sentence · ✅ punctuation pauses · ⏳ reaction clips (N1) · ⏳ laughs (C2)
- 🔧 Memory: name, profile, facts, learner, `remember`/`what_you_know`/`forget`, Memory page
- 🔧 Personality box, humour dial ⏳, chattiness 🔧 (four levels ⏳)
- ⏳ Mood that follows you across a day (no narrating the clock)

**PC control** (✅ unless noted)
- Open apps, folders, websites, settings pages · find files · volume, media keys, screenshot, lock, sleep,
  shutdown, restart, Recycle Bin · timers, reminders (survive restarts) · repo sync check · notify when an
  app finishes · battery, time, date · play any song/video on YouTube
- ⏳ Windows: snap, minimise all, switch app, close window (asks) · ⏳ system: Wi-Fi, Bluetooth, night light ·
  ⏳ clipboard: explain, summarise, shorten what I copied · ⏳ dictation "type this: …" · ⏳ focus timer

**Knowing things**
- ✅ Look-up (Wikipedia + Red's own web search, cross-checked) · weather, news · answers from the model
- 🔧 Screen: describe (N3 makes it automatic) · ⏳ read a PDF, docx, txt and answer from it

**Work**
- 🔧 Write / explain / fix code in the chat window, never run · 🔧 coding tools (VS Code, Qoder, Antigravity,
  Freebuff): open, hand a task, "what did it change?" · ⏳ more tools via `[coding.*]` · ⏳ VS Code extension
- ✅ Gmail and Calendar (optional sign-in, send/delete read back) · ⏳ mail drafts in your style, "anything
  important?" · ⏳ other mail by IMAP/SMTP with an app password · 🔧 to-dos, day recap · ⏳ notes (Obsidian-friendly)
- ⏳ **Work mode:** several steps with a plan shown, Stop button, step limit (B6)

**Apps and fun**
- 🔧 Spotify search and what's playing (🔧) · ⏳ Spotify sign-in for "play X on Spotify" (needs Premium) ·
  🔧 WhatsApp (send to saved numbers, read back; no reading chats) · 🔧 Discord (open, mute/deafen; no messages)
- ⏳ Telegram, Steam *launching* (not the store), OneDrive, browser tabs · ⏳ games: 20 questions, would-you-rather,
  quiz, debate (debate ✅)

**The shell**
- 🔧 Chat window (typed + spoken in one thread, code with Copy/Save/Open in VS Code, drafts with Send)
- ✅ Glow around the screen edges (final design waiting for you) · ⏳ the companion character
- 🔧 Red app with seven pages · ⏳ tray icon, first-run wizard, one-click installer, auto-update, uninstaller

**❌ Not doing:** reading your WhatsApp or Discord messages, automating your Discord account, trading or
financial automation, smart home, cloud models, selling or sharing your memory.

---

## 9. The Red app (`python -m red app`, later the tray icon)

Today: Hardware Check, Model Status, Audio Setup, Voice Settings, General (hotkey, overlay, chattiness,
personality), Memory, Plugins.
Target, in one window with a left list instead of tabs:
1. **Home:** is Red running, what it's listening for, a Talk button, latest conversation, a mic level meter.
2. **Voice:** voice (female/male, Play sample), speed, earcons, laugh style (when C2 lands).
3. **Personality:** character summary, humour dial, chattiness (4 levels), custom text, the "taste" scores.
4. **Memory:** profile, facts, "what Red learned today", export/delete everything.
5. **Listening:** wake phrase and *train my voice*, sensitivity, hotkeys, microphone, voice match, the wake test.
6. **Models:** current model, a pick per hardware tier with a "best for" line, downloads with progress and
   checksums, speech-to-text size.
7. **Plugins:** on/off, what each needs, a sign-in button per plugin (Google, Spotify, mail), install from a folder.
8. **Screen and privacy:** look at the screen on/off, window-title line on/off, what's stored, where.
9. **Companion:** character on/off, which one, size, corner, behaviour during full screen.
10. **General:** start with Windows, updates, language is English, logs folder, "report a problem" (makes a
    redacted bundle you can send; nothing automatic).
Rules: a Save button that says what restarts; every setting writes to `.env` or a named file; no setting
that needs the command line; follows the glow look (frosted, no rim).

---

## 10. The one-click installer

Goal: a person with a Windows 11 laptop downloads **one file**, double-clicks, and ends with a Red that
answers "Hey Red", with no Python, git or command line. **Cost: $0.**
1. **Build** (`installer/build.ps1`): an embeddable Python 3.11, Red's pinned wheels (pure Python or signed
   DLLs only, Smart App Control), the `red` package, the first-run app. `Red-Setup.exe` from **Inno Setup**
   (free): per-user install to `%LOCALAPPDATA%\Red`, no admin, Start menu, optional start with Windows, an
   uninstaller that offers to keep or delete memory and models. Size target: installer < 150 MB; models
   download on first run (about 3.5–6 GB depending on the tier) with a progress bar, resume and SHA-256.
2. **First-run wizard** (the Red app, 8 screens): (1) hardware check and the model for this PC; (2) downloads;
   (3) microphone and a level meter; (4) *say "Hey Red" ten times* (voice-setup) and a spoken test; (5) pick
   the voice (play samples); (6) **your name and a few things about you**, which seed memory; (7) plugins to
   turn on and optional sign-ins (Google, Spotify, mail), each skippable; (8) the first hello.
3. **Updates:** the app checks the GitHub release feed (one HTTPS request, no tracking), shows what's new,
   downloads, checks the hash, and installs on restart. Off by default for the cautious, on in the wizard.
4. **Signing is what makes Windows trust it.** Smart App Control blocks unsigned programs outright; SmartScreen
   warns on unknown ones. $0 options: **SignPath Foundation** (free code signing for open-source projects;
   apply with the GitHub repo), or **publishing through the Microsoft Store** (the Store signs the package;
   check the current individual-developer fee). Until then: the README says how to unblock, and the
   installer is built so every file inside is pinned and hashed.
5. **Tests:** a clean Windows Sandbox/VM with Smart App Control on; download → working "Hey Red" with no
   command line; uninstall leaves nothing but what you chose to keep; install over a running Red works.
6. **Also:** `install.ps1` one-liner for people who prefer PowerShell; a portable zip.

---

## 11. How it all fits together

**The architecture lives in [docs/architecture.md](docs/architecture.md)**:
- the parts and what each owns, and the event bus that connects them;
- threads and the latency budget;
- the companion pack format; avatars (renderer interface, VRM and sprite backends); multi-name wake;
- emotion tags and clip banks; memory layers; hardware tiers;
- the settings registry (each setting declared once and generated into `.env.example`, the app pages and the wizard);
- files; build/install/update/CI; the test levels; safety; licences; the spikes with pass lines.

Build to it. When a task here needs a change of design, change architecture.md in the same commit.

The short version:
```
 mic ─► wake (all companions' names) ─► Whisper ─► transcript filter ─► gate ─┬─ chat ─► persona + memory ─► tags ─► voice/clips ─► speakers
 hotkey / chat window ──────────────────────────────────────────────────────┘ └─ command ─► fast path ─► router (2-step) ─► executor ─► tool/plugin
 event bus: state · mouth · emotion · said/heard · companion · memory_saved ─► avatar · chat window · glow · tray
```

## 12. Compared with others

(From what I know up to mid-2026; verify prices and features before using these in public text.)

**Voice assistants and big-company assistants**
| | Strengths | Weaknesses for you | Red's edge |
|---|---|---|---|
| Siri, Google Assistant, Alexa | Always on, huge integrations, instant | Corporate tone, cloud, little memory of *you*, not on Windows | Personality, local, memory, PC control |
| Windows Copilot ("Hey Copilot") | Preinstalled, fluent, voice-first, cloud-smart | Cloud, account, generic tone, watches little of your workflow | Local, yours, friend not helper |
| ChatGPT / Claude / Gemini voice | Best conversation and humour, real laughter and emotion in voice modes | Cloud and subscription, no PC control, no wake word on Windows | Local, free, acts on your PC. **Their fluency is the bar for how Red *feels*.** |
| Grok companions, Pi, Replika, Character.AI | Companion feel, memory, persona | Cloud, accounts, no PC control, some paywalled | Local, works for you, no data leaves |
| Windows Recall / screen-memory tools | Remember what you saw | Heavy, privacy worries | Red looks only when asked |

**Local and open-source assistants**
| | Strengths | Weaknesses | Red's edge |
|---|---|---|---|
| OpenJarvis (Stanford) | Framework, long-term memory, skills/MCP, installer | No personality, no wake word, raw `shell_exec`, developer-first | Friend, safe tools, a face |
| Home Assistant Assist / Rhasspy / OVOS | Solid offline voice for smart homes | Smart-home focus, rigid intents | Open-ended chat, PC work |
| Open Interpreter, Leon | Run code, agents | Run model code on your PC (risky), no companion | Never runs model text |
| Jan, LM Studio, Open WebUI, AnythingLLM | Nice local chat and model management | Chat boxes, not voice-first, no PC control | Voice, wake word, control |
| Braina, VoiceAttack | Triggers, macros, plugins | Paid, rigid, not conversational | Free, conversational |

**Desktop companions**
| | Strengths | Weaknesses | Red's edge |
|---|---|---|---|
| Desktop Mate | Charm, a character on screen | No brains, no PC control | A mind behind the face |
| Shimeji, BonziBuddy/Clippy (history) | Nostalgia, desktop pets | No real conversation | Real talk, memory |
| AI VTubers (Neuro-sama style) | Personality, humour, audience | Cloud/streaming focus, not a personal tool | Private, personal, useful |

**Red's edge in one line:** personality + memory + PC control + a face, all local and free.
**Where others still lead, and what we do about it:** voice naturalness and real laughter (C2); speed of the
big cloud assistants (N1 gets to ~1 s); polish of preinstalled ones (installer, signing, app); integrations
(plugins).

---

## 13. Where to publish for free (not Steam)

| Place | What it gives | Notes |
|---|---|---|
| **GitHub Releases** (primary) | Free hosting of `Red-Setup.exe` + SHA-256, release notes, the update feed | Free; 2 GB per file; the source of truth for everything below |
| **SourceForge** | Free project page, download stats, mirrors, a release area; Windows users still use it | Upload the same installer; mark it open source; page copy needs care (it has a past with bundled installers: say "no ads, no bundles") |
| **itch.io** | Free page, supports non-game apps, a `butler` upload tool, devlog, comments, a good audience for indie tools | No fee needed for free downloads; good for the companion character demo |
| **winget** | `winget install AryanLanke.Red`, free, via a pull request to `microsoft/winget-pkgs` | Needs a stable installer URL and hash; it works unsigned but is smoother once signed |
| **Scoop** / **Chocolatey** | Command-line installs; Scoop (own bucket, instant), Chocolatey (community moderation) | Cheap to add once releases are stable |
| **Microsoft Store** | Store signs the package (solves SmartScreen/Smart App Control), automatic updates | Check the current individual developer registration cost and the MSIX packaging effort; a later step |
| **FossHub, Uptodown, MajorGeeks, Softpedia** | Download portals with traffic | Free to submit; accept only signed or clean builds; slower to update |
| **AlternativeTo, OpenAlternative, awesome lists** | Discovery as "an alternative to Copilot/Siri/Desktop Mate" | Free listing |
| **Product Hunt, Hacker News ("Show HN"), Reddit** (r/LocalLLaMA, r/selfhosted, r/Windows11, r/opensource) | Launch day attention, feedback | Needs a good 60-second demo video and a working installer first |
| **YouTube** (demo + "how I built it"), **GitHub Pages** (`aryanlanke.github.io/Red`) | Your own front door | Free |
| **Hugging Face** | A model card/page for the persona LoRA and the wake-word model, if you train and share them | Free; check each model's licence |
| **Money, optional:** GitHub Sponsors, Ko-fi, Patreon | Donations; no sales | Free to set up |

**Before any release, check:** the licences of everything inside (Kokoro and its eSpeak-NG phonemizer, Qwen,
Whisper, openWakeWord's pretrained parts, SearXNG, onnxruntime, each TTS candidate) and write
`THIRD_PARTY.md`; choose Red's own licence (today: `LICENSE`); and sign the installer (section 10).

---

## 14. The seven-day project (2026-11-14 to 11-20): v0.5, the first public preview

**Can all of it be done in 7 days? No, and pretending would ship something broken.** Here's what's honest:
- **In 7 days, with three sessions in parallel and you giving about 30 minutes a day:** v0.5, a downloadable
  preview with the fixes from your logs, four companions with their own personality, voice, wake name and
  face, expressive sounds, the settings app, and an installer. It's on GitHub, itch.io and SourceForge, unsigned at first.
- **Not in 7 days** (v0.6–v1.0, weeks 2–4):
  - trained wake models per name (v0.5 uses Whisper-checked names);
  - the live expressive engine (Max tier);
  - all of B5's small plugins, mail over IMAP, Spotify sign-in, work mode;
  - signing approval (SignPath takes days to weeks), the Microsoft Store;
  - the persona LoRA, and polished 3D animation (v0.5 has procedural animation).

**Three lanes** (section 16 has the file ownership). Every day ends with tests green, pushed to `main`,
numbers in progress.md, and the hidden Red restarted by lane 1.
- **Lane 1, session 1: listening and speed.**
- **Lane 2, session 2: brains and companions.**
- **Lane 3, session 3: shell, app and shipping.**

| Day | Lane 1 (listening) | Lane 2 (brains, companions) | Lane 3 (shell, ship) | You 👤 |
|---|---|---|---|---|
| **1 Sat 11-14** | Restart with the context fix; N5 transcript filters; end-of-speech 0.5 s for finished sentences | N1 gate + reply length, N2 (no "didn't understand"), `red/events.py` | Spikes: **VRM in QtWebEngine** under Smart App Control; CI on GitHub Actions | 20 chit-chat lines (timing) |
| **2 Sun 11-15** | Multi-name wake, stage 1 (Whisper-checked names, the names from companions) | `red/companions.py` + the pack format; Red as the first pack; N4 prompt + `chat_eval.py` | Avatar window: interface, VRM backend (or sprites if the spike failed), lip sync, emotions, states | Pick 4 avatars from a contact sheet of CC0 VRMs; pick names |
| **3 Mon 11-16** | Wake corpus per name; voice match in the wizard flow | Remy, Bruno, Winston persona packs + per-companion eval; switching; relationship notes | Sprite pre-render from VRM for Lite; tray icon and menu (switch, mute, settings) | Rate 20 replies per companion; record the wake corpus (~10 min) |
| **4 Tue 11-17** | N5 media-aware listening; the "mm-hmm" mid-pause signal | Emotion tags in prompts; `red/expressive.py`; N3 screen as a sense | `red/settings_registry.py`; the new settings app (Home, Companions, Personality, Voice, Listening, Memory, Plugins, Models, Privacy, General) | — |
| **5 Wed 11-18** | Benchmark script (`bench_turns.py`) per tier; CPU-only run for Lite | Clip banks: render with the cloned engine for 4 voices; N7 humour devices | `red/bench.py` tier test; first-run wizard | **Blind listening test** (15 min): clips vs voice, voices per companion |
| **6 Thu 11-19** | Wake replay ≥ 90/100 per name; TV test | Memory: history, "memory updated", temporary chat, export | `installer/build.ps1`, Inno Setup, updater; Windows Sandbox install test | Install in Sandbox with us |
| **7 Fri 11-20** | Bug bash | Bug bash; licences in `THIRD_PARTY.md` | Release v0.5: GitHub Release + hashes, itch.io, SourceForge, winget PR, README, a 60-second video; SignPath application | Release checklist (15 min); watch the video |

**Gates (a day's work isn't done until):**
- unit tests pass;
- contract tests pass (companion.toml schema, settings registry ↔ .env.example, event payloads);
- UI snapshots are approved;
- the day's real-model check is in progress.md.

**Release gate (day 7):**
- routing ≥ 95% on 150 sentences;
- chat eval: 0 invented-life lines for every companion;
- first word ≤ 1.0 s on Plus and ≤ 2.5 s on a CPU-only run;
- wake ≥ 90/100 per name;
- a clean Sandbox install to a working wake and an uninstall that leaves nothing.

Anything that misses its gate moves to v0.6 rather than holding the release.

**Risks and fallbacks:**
- VRM fails Smart App Control or is too heavy → sprites for everyone in v0.5.
- The cloned clips don't match → clips in the nearest Kokoro voice, fewer sounds.
- A wake name misses → ship Red plus whichever names pass.
- No signing yet → unsigned, with unblock steps.
- Your time is the tightest resource: the 👤 column is what can't be parallelised.

## 15. Decisions for you

1. **Companion names and personalities:** Red, Remy (music), Bruno (grumpy), Winston (gentleman), or yours?
   Names become wake words: 2–3 syllables, distinct from each other, not a real or famous character.
   (You wrote "faired": if you meant **Friday**, it works technically, but it's Iron Man's AI; a name of
   our own is safer for a public release.)
2. **Avatars:** pick 4 from a contact sheet of CC0 VRM avatars (day 2). Anime-style, realistic, or cartoon?
3. **Bruno's anger:** how far? Default: grumbles and gets heated at *situations*, calms down if you're upset,
   never insults you.
4. **Training (section 7):** may a persona LoRA be trained on a free cloud GPU using only text you approve?
   Default: no, prompts and evals first.
5. **Humour default:** Normal. **Chattiness default:** Friendly; add the "Companion" level?
6. **Glow:** keep it as an option once characters exist, or drop it?
7. **Licence and credit:** keep `LICENSE` as is? Installer says "by Aryan Lanke"?
8. **Pause media on wake** during a video (N5.3)?
9. **A third session** for lane 3: will you run three sessions in parallel? Without it, the 7 days stretch to about 10.
10. **GitHub Project board** with one issue per task: create it now?

## 16. Reference (kept from the earlier plans)

### Three sessions at once (from 2026-11-14)
| | Session 1: listening and speed | Session 2: brains and companions | Session 3: shell, app and shipping |
|---|---|---|---|
| Works in | `D:\RED\red`, on `main` | a worktree `D:\RED\worktrees\<name>` on its own branch, pushing each commit to `main` | another worktree, same way |
| Owns | `wakeword.py`, `wake_test.py`, `wake_corpus.py`, `voice_setup.py`, `listener.py`, `audio.py`, `stt.py`, `voice_match.py`, `background.py`, `startup.py`, `llm.py`, `scripts/bench_turns.py`, and their tests | `chat.py`, `smalltalk.py`, `speech.py`, `router.py`, `gate.py`, `companions.py`, `expressive.py`, `memory.py`, `history.py`, `events.py`, `red/tools/`, `red/plugins/`, `companions/` personas and clip banks | `overlay.py`, `chat_window.py`, `red/avatar/`, `tray.py`, `red/app/`, `settings_registry.py`, `bench.py`, `installer/`, `.github/`, `docs/` except architecture, README |
| Hidden Red | the only one that stops and starts it | never | never |
| Test temp folder | `D:\RED\cache\pytest-tmp` | `D:\RED\cache\pytest-tmp-companion` | `D:\RED\cache\pytest-tmp-ship` |

- `docs/architecture.md` is shared: change it only together with the code that needs the change.
- Interfaces between lanes are the event bus payloads, `companion.toml` and the settings registry. A lane that needs a change to another lane's interface writes the change into architecture.md and leaves a note in plan.md under the other lane's day.

### Finished tasks (details in progress.md)
A0–A4 ✅ · B1 ✅ · B2 steps 1–4 ✅ (step 5, a coder model, waits) · B3.1 coding tools ✅ · B3.2–3.4 Spotify (no
account), WhatsApp, Discord ✅ built, need your try · B4 ✅. **Left from B3:** 3.2's Spotify sign-in, 3.5 mail
(Gmail extras + IMAP/SMTP with an app password through `red/secrets.py`, send read back once). **B5** (small
plugins, build in this order: notes, read a document, clipboard, windows, dictation, system, focus timer,
fun) and **B6** (work mode: a plan shown, Stop button, step limit, 2–4 steps first, measured on 20 real jobs).
**C1** wake word ≥ 95/100 (session 1; steps 4–7 in the old plan: personal spellings, looser guards measured,
wake check on its own thread, retrain only if needed). **C2** and **C3** are sections 6 and 10 above.
**D1** the glow waits for your design; **D2** the character is section 5.4.

### The speed plan (still applies)
Numbers first (`Timing` lines in `red.log`), widen the fast path, one model call for a question, cut look-up's
web wait, cache the router prompt (Ollama), route with a small model, preload the voice. Done when "open Edge"
takes 1–3 s, a question or chat's first word ≤ 1 s, and "play Believer" 2–3 s.

### Later
Persona presets (Witty, Calm, Minimal), MCP support for local tool servers, a VS Code extension (also check
Qoder and Antigravity, which are VS Code forks), Telegram, Steam *launching*, browser tabs, OneDrive, Ollama
that reuses the cached prompt for Qwen3.5 (check each release), a phone-less wake via your headset button.


## 17. Rules: what to do and what not to do

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
- Keep confirmations for shutdown, restart, sleep, emptying the Recycle Bin, forgetting a memory, closing
  a window, and sending a mail or deleting a calendar event (the user chose a read-back for those two).
  Keep allowlists. Never run model text as a command, including code Red writes.
- Take ideas from other projects (OpenJarvis and others), not their code.

Don't:
- Don't ask permission or "Anything else?" for harmless actions.
- Don't use stock assistant lines ("I'm here to help", "How can I assist you") or a business tone.
- Don't speak meetings, mail, to-dos or news unasked. Greetings and the user's own reminders only.
- Don't read code aloud.
- Don't let Red claim things that aren't true (seeing images, music playing, a body, a page that didn't
  open).
- Don't send voice, screen, memory or the AI's work to any cloud service. Red is local-only. Public
  look-ups (Wikipedia, weather, news, YouTube search) are fine.
- Accounts: Red talks only to services the user signs into through Red (Google, and plugins such as
  Spotify or other mail), and sends each one only what that service needs. Tokens are encrypted with
  DPAPI and never go into git.
- Don't automate a user account where the service forbids it (Discord), and don't scrape apps
  (WhatsApp).
- Don't put the user's memory files, voice clips or wake corpus in git.
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

Also, from the logs of 2026-11-13 (sixth plan):
- Never say "I can't see your screen": look, or say what blocked the look. Never ask the user what is on their own screen.
- Never narrate the clock, the room, a body or a "day". Red's inner life is the conversation and the user.
- Never write laughter as words ("Haha", "Heh") unless the voice engine can speak laughter tags.
- A failed route is a chat turn, never "I didn't understand that" (only when the model itself is down).
- Don't answer speech that isn't for Red (a video, the TV, repeated noise).


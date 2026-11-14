# Red: architecture

How Red is built: the parts, what each owns, the formats between them, how it's tested and shipped.
plan.md says *what to do and when*; this file says *how it's built*. When the two disagree, fix this file
first, then the plan. Written 2026-11-14 for v0.5 (the first public preview) and kept current after.

Contents: 1 Goals and limits · 2 The parts · 3 Runtime and threads · 4 Companions · 5 Avatars ·
6 Wake words · 7 Speech and emotion · 8 Memory · 9 Hardware tiers · 10 Settings · 11 Files ·
12 Shipping · 13 Testing · 14 Safety and privacy · 15 Licences · 16 Spikes and risks

---

## 1. Goals and limits

| Goal | Measured as |
|---|---|
| Feels like a person | First sound ≤ 0.3 s after you stop; first real word ≤ 1 s (Plus tier); chat eval: 0 invented body/place/time lines |
| Several companions | 4 shipped companions, each with its own name (= wake word), personality, voice, look; switch by voice or the tray |
| Any Windows PC | Lite (no GPU, 8 GB RAM) to Max (8 GB+ GPU); a feature that doesn't fit a tier turns off, nothing breaks |
| Local and private | No cloud model at runtime; memory, voice, screen never leave the PC; optional sign-ins only |
| Installable by anyone | One download, double-click, a working companion, no command line; uninstaller leaves nothing unasked |
| Safe | Model text never reaches a shell; risky actions read back; keys pressed only from fixed combos |

**Hard limits:**
- Windows 10/11 only, English only.
- Smart App Control: no unsigned native DLLs, so the code is pure Python, signed Windows APIs, signed Qt, and Ollama.
- $0 budget.
- The minimum is 8 GB RAM. 4 GB of system RAM is not supported (Windows itself uses ~3 GB).

---

## 2. The parts

```
┌──────────────────────────── Red process (python -m red, one per user) ───────────────────────────────┐
│                                                                                                       │
│  SHELL (Qt main thread)        COMPANION RUNTIME            CORE                    SERVICES            │
│  ├ tray icon                   ├ active companion pack ──►  ├ listener (wake/hotkey)  ├ memory          │
│  ├ avatar window  ◄── events ──┤ persona prompt            ├ STT + transcript filter ├ history         │
│  ├ chat window                 ├ voice profile + clip bank ├ gate → fast path →      ├ reminders       │
│  ├ glow (optional)             ├ wake names                │   router → executor     ├ greeter         │
│  └ settings app (same exe)     └ avatar spec               ├ chat (persona+memory)   ├ learner (idle)  │
│                                                            ├ speech (tags→voice)     └ plugins         │
│        ▲                                                   └ senses (screen)                          │
│        └──────────────── event bus (red/events.py): state, mouth level, emotion, reply text ─────────┘
│  PLATFORM: desk (keys, clipboard, windows), secrets (DPAPI), config (settings registry), logs        │
└───────────────────────────────────────────────────────────────────────────────────────────────────────┘
   children (Job Object, die with Red): Ollama · Red's SearXNG · (Max tier) expressive TTS worker
```

| Part | Modules (✅ exists, ⏳ new) | Owns | Must not |
|---|---|---|---|
| Listener | `listener.py` ✅, `wakeword.py` ✅, `audio.py` ✅, `voice_match.py` ✅ | mic, wake names, hotkey, end of speech | know about companions beyond their wake names |
| STT | `stt.py` ✅, transcript filter ⏳ in `smalltalk.py` | text from audio, dropping noise and loops | route |
| Gate | ⏳ `red/gate.py` | chat vs command in < 5 ms, no model | call a model |
| Router | `router.py` ✅, `fastpath.py` ✅ | picking a tool; two-step groups ⏳ | write chat replies (N2) |
| Executor | `executor.py` ✅ | confirm, run, log | speak by itself |
| Chat | `chat.py` ✅ | the reply in the companion's character | pick tools |
| Companion runtime | ✅ `red/companions.py` | loading packs, the active one, switching | render anything |
| Speech | `speech.py` ✅, `tts*.py` ✅, ⏳ `red/expressive.py` | turning tagged text into sound; clips; engines | decide what to say |
| Senses | `screen.py` ✅, `tools/screen.py` ✅ | window title always, a look on demand | keep screenshots |
| Memory | `memory.py` ✅, ⏳ `red/history.py` | facts, profile, relationship notes, past chats | leave the PC |
| Shell | `overlay.py` ✅, `chat_window.py` ✅, ⏳ `red/avatar/`, ⏳ `red/tray.py` | everything on screen | block the voice loop |
| Settings | `config.py` ✅, ⏳ `red/settings_registry.py`, `red/app/` ✅ | every setting's type, default, page, label | be edited in two places |
| Setup | `hardware.py` ✅, ⏳ `red/bench.py`, ⏳ `installer/` | the tier, downloads, first run, updates | run without the user seeing it |
| Plugins | `plugins.py` ✅, `red/plugins/*` ✅ | extra tools | bypass the Executor |

**One rule for all of them:** parts talk through function calls on one thread, or through the **event
bus** across threads. Nothing reaches into another part's private state. That's what lets three sessions
build in parallel without breaking each other.

### The event bus (`red/events.py`, new, ~80 lines)
A thread-safe publish/subscribe in one process. Producers never block on a slow subscriber; Qt subscribers
get the event delivered on the Qt thread.

| Event | From | Used by |
|---|---|---|
| `state(name)`: idle, listening, thinking, speaking, confirm, error | voice loop | glow, avatar, tray |
| `mouth(level 0–1)` 30×/s | speech player | avatar lip sync |
| `emotion(name, strength)`: happy, laugh, angry, sad, surprised, thinking, shy | speech (from tags) | avatar face |
| `said(text)` / `heard(text)` | voice loop | chat window, history, the companion's bubble (`heard`: grey italic "you: ..."; `said`: a piece of Red's reply, shown when its audio starts) |
| `mic(muted)` | `Listener.mute` (or `avatar.mic_control`) | the companion's crossed-mic badge |
| `companion(id)` | companion runtime | everything (voice, avatar, prompt, wake names) |
| `memory_saved(fact)` | memory | chat window ("Memory updated") |
| `notice(text)` | anything | tray balloon |

Today the overlay and chat window are fed ad hoc (`overlay.set_state`, `VoiceApp.out` mirroring). v0.5 moves
both to the bus; old calls stay as thin adapters until they're gone.

---

## 3. Runtime and threads

| Thread | Does | Never |
|---|---|---|
| Qt main | tray, avatar, chat window, glow, settings | wait on audio or a model |
| Listener | mic stream, VAD, wake check | run a tool |
| Turn worker (one at a time, `VoiceApp._turn`) | transcribe → gate → route → act → speak | overlap another turn |
| Speech stream | synthesise next sentence while one plays; mouth levels | decide content |
| Idle workers | greeter, learner, avatar idle animations | run while a turn is active |
| Children | Ollama, SearXNG, expressive TTS (Max) | outlive Red (Job Object) |

**Latency budget per turn (Plus tier):**
- End of speech: ≤ 0.5 s.
- Whisper: ≤ 0.5 s.
- Gate: ≤ 5 ms.
- Reaction clip: ≈ 0.2 s.
- Chat first token: ≤ 0.6 s (prompt cached).
- First sentence voice: ≤ 0.3 s.
- **Result:** first real word ≤ 1.0 s.

Every turn logs a `Timing` line, and the benchmark (§13) fails the build if the median regresses by > 20%.

---

## 4. Companions

A companion is **data, not code**: a folder that the companion runtime loads. Red ships four; users can add
more by dropping in a folder (same idea as plugins).

```
companions/
  red/
    companion.toml      name, wake names, voice, personality, defaults, avatar, credits
    persona.md          the character bible: who they are, how they talk, 6 example exchanges
    clips/              reaction and expressive clips in this companion's voice (laugh, sigh, mm-hmm, cough…)
    avatar/             model.vrm  (or sprites/  for 2D), thumbnail.png
    LICENSE-assets.txt  the licence and credit of every asset in this folder
```

```toml
# companions/remy/companion.toml (example)
id = "remy"
name = "Remy"
wake = ["hey remy", "remy"]              # the name is the wake word; 2–3 syllables wake best
tagline = "Lives for music. Will judge your playlist."
voice = { engine = "kokoro", id = "af_bella", speed = 1.05, blend = { af_nova = 0.3 } }
humour = "normal"                        # off | light | normal | cheeky
chattiness = "chatty"                    # quiet | friendly | chatty | companion
temper = "low"                           # how quickly they get annoyed (for the grumpy one: "high")
likes = ["music", "concerts", "playlists"]
avatar = { kind = "vrm", file = "avatar/model.vrm", scale = 1.0 }   # or kind = "sprites"
tools_first = ["play_online", "spotify_search", "whats_playing"]    # hints for the gate and suggestions
```

**The four shipped companions** (names, looks and voices are suggestions; the user picks, see plan.md §15):
| Companion | Personality | Voice (Kokoro, picked by ear) | Wake |
|---|---|---|---|
| **Red** (default) | dry wit, warm underneath, the friend good with computers | `af_heart` | "Hey Red" |
| **Remy** | music lover: hums, drops song references, suggests tracks, gets excited about concerts | `af_bella` + a brighter blend | "Hey Remy" |
| **Bruno** | grumpy and blunt: complains, gets angry *at bugs, slow Wi-Fi and bad decisions*, never cruel to you, secretly caring | `am_fenrir` or `am_onyx`, slower | "Hey Bruno" |
| **Winston** | a gentleman: polite, formal, understated British humour, calls you by name, never rushes | `bm_george` | "Hey Winston" |

**Rules for every companion:**
- Same safety and honesty rules as Red.
- Anger is a style: it's aimed at situations, never at protecting groups or at the user's real struggles. It stops the moment the user is upset.
- Each persona.md must pass the chat eval (§13).
- No companion copies a real, trademarked or fictional character (no Jarvis, Friday-from-Marvel, Alfred, Miku…).

**What's shared and what's per companion:**
- **Shared (it's about the user):** user memory (facts, profile), reminders, to-dos, plugins, settings.
- **Per companion:**
  - persona, voice, clip bank and avatar;
  - wake names;
  - humour, chattiness and temper defaults;
  - a short **relationship note** in `memory/companions/<id>.md` (in-jokes, how long you've talked, what landed).

**Switching:** "Hey Bruno" wakes Bruno directly (all companions' wake names are always listened for; the one
you call becomes active). "Switch to Winston" or the tray menu also switches. One companion is on screen at a
time; the user can pin one.

---

## 5. Avatars (the face, instead of the glow)

**Sources, legally.**
- Desktop Mate's characters are licensed IP sold per character, so they can't be taken.
- Shippable sources, in order:
  1. **CC0 VRM avatars**: the 100Avatars / open-source-avatars collections (about 300 avatars, public domain, VRM format).
  2. **Unity-chan**, which allows redistribution under its guideline, with credit.
  3. **Live2D sample characters**: free for individuals and businesses under ¥10M a year, with per-character terms. The Cubism SDK has its own licence, and its native core needs a Smart App Control check.
  4. Assets commissioned or made later.
- Every asset gets a line in `LICENSE-assets.txt` and in the app's About page.
- "Free to download" is not the same as "free to redistribute": only CC0 or an explicit redistribution grant gets shipped.

**Renderer interface** (`red/avatar/__init__.py`), so the backend can change without touching the rest:
```python
class AvatarView(Protocol):
    def load(self, spec: AvatarSpec) -> None: ...
    def set_state(self, state: str) -> None: ...            # idle, listening, thinking, speaking, sleeping
    def set_emotion(self, name: str, strength: float) -> None: ...
    def set_mouth(self, level: float) -> None: ...          # 0..1, from the speech loudness, 30 Hz
    def look_at(self, x: float, y: float) -> None: ...      # the cursor, softly
    def show(self) -> None: ... ; def hide(self) -> None: ...
```

**Backends:**
| Backend | How | Tier | Status |
|---|---|---|---|
| **VRM 3D** | a frameless, transparent, click-through Qt window hosting QtWebEngine with **three-vrm** (MIT) and a tiny local HTML page; Python drives it over a `QWebChannel` | Standard and up | ⏳ spike first (Smart App Control with PySide6-Addons, GPU/CPU use, transparency, click-through) |
| **Sprites 2D** | PNG frame sets per state/emotion, drawn with QPainter | Lite, and the fallback | ⏳ frames **pre-rendered from the same VRM at build time**, so every companion has both |
| Glow | today's screen-edge glow | any | ✅ kept as an option |

**Animation without licensed animation files:**
- All movement is procedural: breathing, blinking, idle sway, head turn toward the cursor, lean-in when listening, look-up when thinking.
- Mouth open follows the speech loudness.
- Expressions come from VRM blendshapes (joy, angry, sorrow, surprised, relaxed) driven by `emotion` events.
- No Mixamo files are bundled (their licence forbids standalone redistribution).
- Free VRMA motion packs only if their licence allows.

**Behaviour:**
- Sits on the taskbar or in a corner, and can be dragged anywhere.
- Click opens the chat window; right-click gives the menu (switch companion, mute, settings, hide).
- Hides during full-screen apps and games; sleeps after 5 minutes of idle.
- Budget: < 2% CPU idle, < 150 MB RAM, GPU only while animating; under 1% when asleep (frames paused).

---

## 6. Wake words (several names)

- **Today:** "Hey Red" = openWakeWord custom model, then a Whisper check, then voice match. One-syllable "Red" is part of why it misses; 2–3-syllable names wake better.
- **v0.5: names come from companions.** The listener gets the set of wake names from every installed companion, plus custom names from settings.
  1. **Stage 1 (cheap, always on):** VAD finds a short burst, Whisper `tiny.en` transcribes it with the names as hotwords, and a fuzzy match against all wake names follows. This works for any name the user types, with no training. Personal spellings from voice-setup ("Headed" → Red) apply.
  2. **Stage 2 (shipped companions only, later):** an openWakeWord model per shipped name, trained with the existing `scripts/train_hey_red` pipeline on Kokoro voices and the user's clips. It runs first as a fast filter, so the Whisper check runs less often.
  3. **Voice match** (CAM++) on every wake when it's on: owner only.
- Result: `wake(name)` decides which companion answers.
- **Owner:** session 1 (`wakeword.py`, `listener.py`). The companion runtime only hands over the names.

---

## 7. Speech and emotion

**Tags are the contract.** The chat model writes inline tags from a fixed list; nothing else in Red cares
which voice engine is underneath.
```
[laugh] [chuckle] [sigh] [mm-hmm] [hmm] [cough] [gasp] [pause] [whisper] [angry] [happy] [sad] [excited]
```
- `red/expressive.py` parses a sentence into segments: `("text", "No way."), ("clip", "laugh"), ("pause", 0.4)`, with an emotion for the text.
- **Per voice engine, a capability set:**
  - Kokoro: text plus emotion as voice blend, speed and pitch; clips for the sounds.
  - An expressive engine (Max tier): renders the tags live.
- Unsupported tags become a clip, then a pause, then nothing. **A tag is never read aloud.**
- Each tag also fires an `emotion` event, so the avatar laughs, frowns or sighs in time.
- **Clip banks** (per companion, about 20–30 MB):
  - Contents: laughs, chuckles, sighs, "mm-hmm", "hmm", a cough, a gasp, short reactions.
  - Rendered **once, at build time**, by an expressive engine cloned to the companion's Kokoro voice, and shipped in the installer. So every tier gets real expressive sounds at no runtime cost.
  - A listening test decides if the match is good enough. The user's earlier laugh clips failed on voice mismatch; this is exactly what the test checks.
- **Backchannel:** during a long user turn, when a pause of 0.6–1.2 s isn't the end of the sentence, the companion may play a quiet "mm-hmm" (at most every 8 s). Owner: session 1's listener sends `pause_mid_turn`; speech plays the clip.
- **Live expressive engine** (Max tier only, plan.md §6): one engine for all speech, so there's no mismatch; it runs as a child process so a crash can't take Red down.

---

## 8. Memory (like ChatGPT's, but local)

| Layer | File | Exists |
|---|---|---|
| Profile (name, people, projects, likes) | `memory/profile.md` | ✅ |
| Facts in the user's voice | `memory/facts.jsonl` | ✅ |
| Learned in the background when idle | the learner | ✅ |
| Relationship note per companion | `memory/companions/<id>.md` | ⏳ |
| **Past conversations** (searchable) | `memory/history/YYYY-MM.jsonl` | ⏳ |
| "Memory updated" shown in the chat window | `memory_saved` event | ⏳ |
| Temporary chat (nothing saved) | a chat-window toggle and "don't remember this" | ⏳ |
| Edit, delete, export everything | the Memory page | ✅ edit/delete, ⏳ export |

**Recall order for a reply:**
1. The profile (system prompt).
2. The companion's relationship note (system prompt).
3. The top 5 facts by word overlap.
4. On "remember when…" / "last time…", the top 3 matching past-chat snippets (word overlap; a small local embedding model only if overlap measures weak).

The fixed prompt always comes first, for Ollama's cache.

---

## 9. Hardware tiers

`red/bench.py` (⏳) runs on first launch and from Settings → Models → Re-test (about 20 s). It measures LLM
tokens/s on a fixed prompt, Whisper real-time factor, Kokoro real-time factor, free VRAM and RAM, and then
picks a tier. The user can override it.

| Tier | Typical PC | Chat model | STT | Voice | Avatar | Screen | Target first word |
|---|---|---|---|---|---|---|---|
| **Lite** | no GPU, 8 GB RAM | 1.5–3B, CPU | Whisper tiny/base, CPU | Kokoro or Piper, CPU + clips | sprites | title + OCR | ≤ 2.5 s (clip at 0.2 s) |
| **Standard** | 4 GB GPU (RTX 3050 laptop), 8–16 GB RAM | 3B, GPU, small context | base, CPU | Kokoro + clips | VRM if the spike passes, else sprites | title + OCR | ≤ 1.5 s |
| **Plus** | 6 GB GPU (RTX 4050) | 4B, GPU | small/base, CPU | Kokoro + clips | VRM | + vision on demand (swap) | ≤ 1.0 s |
| **Max** | 8 GB+ GPU | 4–8B | small, GPU | live expressive engine | VRM | vision | ≤ 0.8 s |

What scales with the tier:
- The model, the context size and the number of tool groups the router sees (two-step routing keeps the router prompt about 1.5k tokens, which small models need).
- How much the gate and fast path answer without a model (more on Lite).
- The avatar backend, and whether vision and the live engine are offered.

The tier is shown on the Home page with the reason. Whatever doesn't fit a tier turns off cleanly.

---

## 10. Settings (one registry, many pages)

Today a setting lives in `config.py`, `.env.example`, a page in `red/app/pages.py` and sometimes a test,
written by hand in each. v0.5 adds `red/settings_registry.py`: **each setting is declared once.**
```python
Setting("RED_CHATTINESS", kind="choice", choices=("quiet", "friendly", "chatty", "companion"),
        default="friendly", page="Personality", label="Chattiness",
        help="How often your companion speaks without being asked.", restart=False)
```
From the registry:
- `load_settings()` validates.
- `.env.example` is generated (a test checks it's current).
- Most app pages are generated: a choice becomes a combo box, a bool a switch, a path a picker.
- The first-run wizard uses the same entries.

Hand-made pages remain only where generated ones can't do the job: Memory, Plugins, Companions, the mic meter, voice samples.

**Settings app pages (v0.5):** Home (status, tier, talk button) · Companions (pick, preview voice, preview the avatar, wake names) · Personality (humour, chattiness, temper, custom text) · Voice (voice per companion, speed, earcons, expressive sounds) · Listening (mic, wake test, train my voice, voice match, hotkeys) · Memory · Plugins (on/off, sign-ins) · Models (tier, re-test, downloads) · Screen and privacy · General (start with Windows, updates, logs, about and credits).

---

## 11. Files (`RED_HOME`, default `%LOCALAPPDATA%\Red`)

```
bin\           Ollama, llama.cpp (pinned, hashed)
models\        llm, whisper, kokoro, piper, wakeword, speaker, (vision, expressive on Max)
companions\    the user's own companions (the shipped ones load from the install folder)
plugins\       the user's plugins (+ _examples)
config\        .env, allowlist.toml, contacts.toml, repos.toml, plugins.json, personality.txt, secrets\ (DPAPI)
memory\        profile.md, facts.jsonl, todo.json, greetings.json, companions\, history\
cache\         rendered clips, voice samples, wake corpus, downloads, pytest temp folders
logs\          red.log, commands.jsonl (rotated at 10 MB, kept 5)
```

The install folder (read-only to Red) holds the embedded Python, `red`, the shipped companions and plugins.
**Never in git or sent anywhere:** `memory\`, `config\secrets\`, `logs\`, the wake corpus, voice clips.

---

## 12. Shipping

**Build** (`installer/build.ps1`, run by CI and by hand):
1. Embeddable Python 3.11 and pinned wheels (hash-checked).
2. The `red` package, companions (with clip banks and avatars), plugins.
3. A compile check, then the unit tests run on the built tree.
4. **Inno Setup** makes `Red-Setup-<version>.exe`: per user, no admin.
5. SHA-256 of every artefact.
6. Signing (SignPath for open source, once approved).

**Install:**
- Copies the files, adds Start menu entries, offers start with Windows.
- Launches the first-run wizard: tier test → downloads (resume, hashes) → mic → companion pick (voice and avatar preview) → "say the wake name ten times" → your name and a few facts → plugins and sign-ins (skippable) → first hello.

**Update:** the app checks the GitHub releases feed (one request, no tracking), downloads, verifies the hash, installs on the next restart. Memory and settings are untouched.

**Uninstall:** removes the program; asks whether to keep memory, settings and downloaded models.

**CI** (GitHub Actions, free for public repos, `windows-latest`):
- `.github/workflows/installer.yml` (by hand, and on main when `installer/**` or `requirements*.txt` change): build the installer, then `installer/sandbox_test.ps1 -Mode guest` on the clean VM; the result is an artifact. This is the clean-machine install check, because the PC Red is built on can't run one (Windows 11 Home has no Sandbox; Smart App Control blocks the unsigned exe).
- Planned: unit tests on every push; on a tag, attach the installer and hashes to a GitHub Release.
- Models aren't downloaded in CI; tests use fakes.

**Install test** (`installer/sandbox_test.ps1`, result in `result.json`): silent install with the start-with-Windows task → program files, Start menu and Startup shortcuts → `red doctor` on the embedded Python (Python, core, voice and overlay packages and RED_HOME must be ok; the missing models are expected) → `plugins list`, the wizard/companion/tray imports → uninstall keeping memory (program and shortcuts gone, memory kept) → install again over it → uninstall with `/DELETEDATA=1` (folder gone). Modes: `guest` (any clean Windows), `host` (starts Windows Sandbox from `installer/sandbox-test.wsb`: offline, no GPU, no mic, results folder the only writable mapping), `staged` (copies the build's staged tree into a test folder instead of running the exe; never touches the Start menu, Startup folder or registry), `auto` (host if Sandbox exists, else staged).

**Nightly** (`red/nightly.py`, `python -m red nightly on|off|run`): a Task Scheduler task "Red nightly" at 03:00 that starts only after 10 idle minutes (waits up to 4 h), never on battery, never wakes the PC, runs as the signed-in user without admin, at most 12 h. A run fetches origin and tests origin/main in a detached worktree (`RED_HOME\worktrees\nightly`), so the user's checkout and the hidden Red are untouched. Steps, each logged to `RED_HOME\cache\nightly\<date>\<step>.log`: `unit`, `replay`, `score`, `sim` (no cap when the user is away, else 10), `installer-build` (work and output in `RED_HOME\cache\installer`), `installer-test` (`-Mode auto`). A step whose file doesn't exist yet is skipped. Then `results.json` and `report.md` (step table, what got worse since the last run, the 5 worst simulator conversations); `morning_line(home)` is the one line the morning greeting says. Contract for `python -m red score`: print `Red Score: <n>/10`; the nightly folder is in `RED_NIGHTLY_DIR`. New layers (voice simulator, soak) are new entries in `STEPS`.

**Publish:** GitHub Releases (source of truth) → SourceForge, itch.io, winget, Scoop, later Chocolatey and the Microsoft Store (plan.md §13).

---

## 13. Testing

| Level | What | Where | When it must pass |
|---|---|---|---|
| **Unit** | every module with fakes (no mic, speakers, windows, keys, network) | `tests/`, `pytest` | every commit (1,760 today) |
| **Contract** | event bus payloads; companion.toml schema; settings registry ↔ .env.example ↔ pages; plugin manifests; the voice loop's printed lines (the chat window reads them) | `tests/test_contracts_*.py` | every commit |
| **UI snapshots** | offscreen renders of every page, the chat window, each companion's avatar in each state, compared to approved PNGs within a tolerance | `tests/snapshots/` | every commit (Qt offscreen, Windows fonts) |
| **Real-model** | routing on 150 real sentences from `commands.jsonl` (≥ 95% right); chat eval of 40 lines per companion (0 invented-life lines, ≤ 10% over 2 sentences, persona checks: Bruno grumpy, Winston formal…); learner extraction | `RED_INTEGRATION=1`, `scripts/route_eval.py`, `scripts/chat_eval.py` | before a release; after any prompt or model change |
| **Speech** | wake corpus replay per name (≥ 95% hits, 0 false wakes on 10 min of talk and a TV clip); STT on recorded clips; tag→segment parsing; no tag ever spoken | `red wake-test --replay`, unit | before a release |
| **Performance** | `scripts/bench_turns.py`: 20 scripted turns through the real pipeline with recorded audio, Timing medians per tier; fails on > 20% regression | real models | nightly on this PC; before a release |
| **Listening tests** | blind A/B of voices and clip banks, 10 lines each; humour ratings | the user, 15 min | per voice/persona change |
| **Install** | silent install → `red doctor` → uninstall keeping data → reinstall → uninstall deleting data (§12 Install test); later the wizard, a wake and a reply, and an upgrade over a running Red | `installer/sandbox_test.ps1`: Windows Sandbox, the CI VM, or staged on this PC | nightly (staged here), the CI VM when the installer changes; before a release |
| **Manual checklist** | 30 steps the user does in 15 minutes (wake each companion, switch, ask the screen, a reminder, a code request, memory story) | `docs/release-checklist.md` | before a release |

Tests never touch the user's memory, plugins, secrets or real windows (`tests/conftest.py` guards, kept current).

---

## 14. Safety and privacy

- **Model text never reaches a shell:**
  - Tools take schema-checked arguments.
  - Launches use argument lists.
  - Links use fixed schemes with quoted parts.
  - Keys come from fixed combos, pressed only when the right window is in front.
- **Read back before:** sending anything as the user (mail, WhatsApp, an agent task), deleting, shutting down, forgetting memory.
- **Screen:**
  - The window title is always available, but there's an off switch.
  - A screenshot is read locally and discarded.
  - Password managers, banking pages and password fields are never read.
- **Companions can't change the rules:** a persona file adds tone only; the safety lines are appended after it and win.
- **Secrets:** DPAPI, per plugin, deleted on sign-out.
- **Logs:** local, rotated; "report a problem" makes a *redacted* bundle the user sends themselves.
- **Children:** in a Job Object; ports bound to 127.0.0.1 only.

---

## 15. Licences (check before every release; record in `THIRD_PARTY.md`)

| Thing | Licence (as understood; verify) | Note |
|---|---|---|
| Red's code | `LICENSE` in the repo | the user decides (plan.md §15) |
| Qwen models | per model card | check each tier's model |
| Whisper / faster-whisper | MIT | |
| Kokoro weights | Apache-2.0 | its phonemizer path (eSpeak-NG data) is GPL: check how it's bundled |
| Piper voices | per voice | |
| openWakeWord | code Apache-2.0; **pretrained models CC BY-NC-SA** | only our own trained models ship |
| SearXNG | AGPL-3.0 | downloaded at setup, run separately, not modified beyond the documented patch |
| Expressive engine (if any) | per engine | weights and output terms both matter (clip banks are its output) |
| Avatars | CC0 (100Avatars), Unity-chan guideline, Live2D terms | credit even when not required |
| three-vrm, Qt | MIT; LGPL (PySide6) | LGPL: ship Qt as separate DLLs (it already is) |

---

## 16. Spikes and risks (each has a deadline and a pass/fail line)

| Spike | Pass when | If it fails |
|---|---|---|
| **VRM in QtWebEngine** | runs under Smart App Control; transparent and click-through; < 2% CPU idle and < 15% while talking on a 4 GB 3050-class GPU; mouth follows audio | sprites for everyone in v0.5, VRM in v0.6 |
| **Clip bank by a cloned expressive engine** | the user can't tell the clip from Kokoro's voice in 7 of 10 blind pairs | clips from the user's choice of the closest Kokoro voice, fewer sound types |
| **Multi-name wake via Whisper tiny** | ≥ 90/100 per name, 0 false wakes on 10 min of TV, CPU < 15% on Lite | ship with Red + one more name; trained models in v0.6 |
| **Lite tier (no GPU)** | first word ≤ 2.5 s median on a 4-core laptop CPU with the 3B model | Lite uses a 1.5B model and more canned replies |
| **Two-step routing** | ≥ 95% on the 150-sentence set, router prompt ≤ 1.5k tokens | keep one-step with merged tools |
| **SignPath approval** | a signed installer | ship unsigned with unblocking steps in the README |

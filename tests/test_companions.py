"""Companion packs (red/companions.py): the shipped five, the user's edits winning field by field,
the active one, switching, and the persona in the chat prompt."""

import json

import pytest

from red import chat as chatmod
from red import companions, events

SHIPPED = ["asha", "bruno", "red", "remy", "winston"]


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    events.clear()
    monkeypatch.delenv("RED_COMPANION", raising=False)
    yield
    events.clear()


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# --- the shipped packs ---------------------------------------------------------------------

def test_the_five_shipped_packs_exist(tmp_path):
    assert sorted(companions.available(tmp_path)) == SHIPPED


@pytest.mark.parametrize("cid", SHIPPED)
def test_shipped_pack_matches_the_schema(cid):
    import tomllib
    data = tomllib.loads((companions.SHIPPED_DIR / cid / "companion.toml").read_text(encoding="utf-8"))
    assert companions.problems(data) == []
    assert data["id"] == cid
    assert data["wake"] and all(w == w.lower() for w in data["wake"])
    assert data["voice"]["id"] in data["voices"], "the default voice is one of the choices"


@pytest.mark.parametrize("cid", SHIPPED)
def test_shipped_voices_are_real_kokoro_voices(cid, tmp_path):
    from red.tts_kokoro import VOICES
    c = companions.load(cid, tmp_path)
    assert c.voice_id in VOICES
    assert set(c.voices) <= set(VOICES)


@pytest.mark.parametrize("cid", SHIPPED)
def test_every_persona_is_written_and_short_enough_to_stay_fast(cid, tmp_path):
    c = companions.load(cid, tmp_path)
    text = chatmod.persona_prompt(c)
    assert c.name in text, "the persona says who they are"
    assert "A:" in text and "B:" in text, "with example exchanges, labelled as other people's chats"
    assert "other people's chats" in text.lower()
    # Every 1000 characters of system prompt cost ~0.14 s before the first word (night 1 measurement).
    assert len(text) < 1100
    assert not chatmod.invented_life(text) and not chatmod.written_laughter(text)


def test_red_is_the_man_remy_and_asha_have_their_looks_bruno_and_winston_are_text_only(tmp_path):
    loaded = companions.load_all(tmp_path)
    assert loaded["red"].voice_id.startswith(("am_", "bm_")) and loaded["red"].avatar == "red"
    assert loaded["remy"].avatar == "remy" and loaded["remy"].likes_music()
    assert loaded["asha"].avatar == "asha" and loaded["asha"].voice_id == "af_kore"
    assert loaded["bruno"].text_only and loaded["winston"].text_only
    assert loaded["red"].chattiness == "companion" and loaded["red"].likes_music()
    assert loaded["bruno"].temper == "high" and loaded["remy"].temper == "low"


def test_the_five_voices_and_personas_differ(tmp_path):
    loaded = companions.load_all(tmp_path)
    assert len({c.voice_id for c in loaded.values()}) == 5
    assert len({c.persona for c in loaded.values()}) == 5


# --- schema ---------------------------------------------------------------------------------

def test_problems_names_what_is_wrong():
    good = {"id": "x", "name": "X"}
    assert companions.problems(good) == []
    assert companions.problems({"id": "Bad Id", "name": "X"})
    assert companions.problems({**good, "humour": "savage"})
    assert companions.problems({**good, "voice": {"speed": 3}})
    assert companions.problems({**good, "wake": "hey x"})
    assert companions.problems({**good, "idle": {"fly": True}})
    assert companions.problems({**good, "idle": {"sleep": "yes"}})


# --- the user's edits win, field by field ------------------------------------------------------

def test_user_toml_overrides_only_the_fields_it_names(tmp_path):
    write(tmp_path / "companions" / "red" / "companion.toml",
          'humour = "cheeky"\nvoice = { id = "am_onyx" }\nidle = { music = false }\n')
    c = companions.load("red", tmp_path)
    assert c.humour == "cheeky"
    assert c.voice_id == "am_onyx" and c.voice["speed"] == 1.0 and c.voice["engine"] == "kokoro"
    assert c.allows("music") is False and c.allows("sleep") is True
    assert c.name == "Red" and c.temper == "medium" and c.avatar == "red"


def test_user_persona_replaces_the_shipped_one(tmp_path):
    write(tmp_path / "companions" / "red" / "persona.md", "# Red\nYou are Red, and you only speak in haiku.")
    c = companions.load("red", tmp_path)
    assert "haiku" in c.persona and "bassline" not in c.persona
    write(tmp_path / "companions" / "red" / "persona.md", "   \n")
    assert "bassline" in companions.load("red", tmp_path).persona, "an empty file doesn't wipe the persona"


def test_a_bad_field_is_ignored_and_the_rest_still_applies(tmp_path):
    write(tmp_path / "companions" / "remy" / "companion.toml", 'humour = "savage"\ntemper = "high"\n')
    c = companions.load("remy", tmp_path)
    assert c.humour == "normal" and c.temper == "high"


def test_a_broken_toml_is_skipped(tmp_path):
    write(tmp_path / "companions" / "remy" / "companion.toml", "this is = = not toml [")
    assert companions.load("remy", tmp_path).name == "Remy"


def test_a_companion_the_user_adds_is_a_companion(tmp_path):
    write(tmp_path / "companions" / "zed" / "companion.toml", 'id = "zed"\nname = "Zed"\nwake = ["Hey Zed"]\n')
    write(tmp_path / "companions" / "zed" / "persona.md", "You are Zed.")
    assert "zed" in companions.available(tmp_path)
    c = companions.load("zed", tmp_path)
    assert (c.name, c.wake, c.persona) == ("Zed", ("hey zed",), "You are Zed.")


def test_an_id_with_no_pack_still_loads(tmp_path):
    c = companions.load("kira", tmp_path)
    assert c.name == "Kira" and c.persona == ""


# --- the active companion -------------------------------------------------------------------

def test_active_is_red_by_default(tmp_path):
    assert companions.active_id(tmp_path) == "red"


def test_active_comes_from_the_setting_then_the_saved_choice(tmp_path):
    write(tmp_path / "cache" / "companion.json", json.dumps({"x": 5, "side": "left", "companion": "asha"}))
    assert companions.active_id(tmp_path) == "asha"
    assert companions.active_id(tmp_path, {"RED_COMPANION": "Remy"}) == "remy"
    assert companions.active(tmp_path, {}).name == "Asha"


def test_set_active_saves_keeps_the_avatars_spot_and_emits_the_event(tmp_path):
    write(tmp_path / "cache" / "companion.json", json.dumps({"x": 82.4, "side": "left", "companion": "red"}))
    seen = []
    events.on("companion", lambda id: seen.append(id))
    c = companions.set_active("Remy", tmp_path)
    assert c.name == "Remy" and seen == ["remy"]
    saved = json.loads((tmp_path / "cache" / "companion.json").read_text(encoding="utf-8"))
    assert saved == {"x": 82.4, "side": "left", "companion": "remy"}
    assert companions.active_id(tmp_path) == "remy"


def test_set_active_beats_the_env_setting_for_this_run(tmp_path, monkeypatch):
    monkeypatch.setenv("RED_COMPANION", "red")
    companions.set_active("asha", tmp_path)
    assert companions.active_id(tmp_path) == "asha"


def test_set_active_rejects_nonsense(tmp_path):
    with pytest.raises(ValueError):
        companions.set_active("../etc", tmp_path)


# --- "switch to Remy" -----------------------------------------------------------------------

@pytest.mark.parametrize("said, who", [
    ("Switch to Remy", "remy"), ("switch to Remy.", "remy"), ("Hey Red, switch to Asha please", "asha"),
    ("let me talk to Bruno", "bruno"), ("go back to Red", "red"), ("talk to Winston", "winston"),
    ("change to remy", "remy"), ("can you switch to Asha", "asha"), ("switch companion to Remy", "remy"),
])
def test_switch_phrases(said, who, tmp_path):
    assert companions.switch_target(said, tmp_path) == who


@pytest.mark.parametrize("said", [
    "switch to dark mode", "talk to my mom", "go to Remy's house", "open Chrome", "switch off the lights",
    "I like Remy", "what's up", "switch to", "be quiet",
])
def test_other_sentences_are_not_switches(said, tmp_path):
    assert companions.switch_target(said, tmp_path) is None


def test_handle_switch_changes_the_companion_and_answers_in_their_words(tmp_path):
    seen = []
    events.on("companion", lambda id: seen.append(id))
    reply = companions.handle_switch("switch to Remy", tmp_path)
    assert reply == "Remy here. Got a song in mind?" and seen == ["remy"]
    assert companions.active_id(tmp_path) == "remy"
    assert companions.handle_switch("switch to Remy", tmp_path) == "I'm already Remy."
    assert seen == ["remy"], "no second event when nothing changed"
    assert companions.handle_switch("open Chrome", tmp_path) is None


# --- chat uses the active persona ----------------------------------------------------------------

def test_chat_prompt_keeps_the_rules_first_and_unchanged_then_the_persona(tmp_path):
    plain = chatmod.Chat(None).system()
    assert plain.startswith(chatmod.CHAT_SYSTEM)
    for cid in SHIPPED:
        system = chatmod.Chat(None, persona=lambda cid=cid: companions.load(cid, tmp_path)).system()
        assert system.startswith(chatmod.CHAT_SYSTEM), "Ollama's prompt cache matches on this prefix"
        assert chatmod.persona_prompt(companions.load(cid, tmp_path)) in system[len(chatmod.CHAT_SYSTEM):]


def test_persona_comes_before_the_users_tuning_and_the_profile(tmp_path):
    chat = chatmod.Chat(None, personality=lambda: "Be extra brief.",
                        persona=lambda: companions.load("asha", tmp_path))
    system = chat.system()
    assert system.index("You are Asha") < system.index("Be extra brief.")


def test_history_lines_carry_the_companions_name(tmp_path):
    chat = chatmod.Chat(None, persona=lambda: companions.load("remy", tmp_path))
    chat.remember("hi", "Hey you.")
    prompt = chat.prompt("what's up")
    assert "Remy: Hey you." in prompt and "Red: Hey you." not in prompt
    assert "Red: Hey you." in chat.history(), "the router's context keeps the stored role"


def test_switching_changes_the_next_prompt(tmp_path):
    chat = chatmod.Chat(None, persona=lambda: companions.active(tmp_path, {}))
    assert "bassline" in chat.system()
    companions.set_active("winston", tmp_path)
    assert "gentleman" in chat.system() and "bassline" not in chat.system()


def test_a_companion_without_a_persona_still_gets_its_name(tmp_path):
    chat = chatmod.Chat(None, persona=lambda: companions.load("kira", tmp_path))
    assert "Your name is Kira, not Red." in chat.system()


def test_a_broken_persona_callable_does_not_break_chat():
    def boom():
        raise RuntimeError("disk")
    assert chatmod.Chat(None, persona=boom).system().startswith(chatmod.CHAT_SYSTEM)


def test_make_chat_follows_the_active_companion(tmp_path):
    from red.config import load_settings
    settings = load_settings(tmp_path)
    chat = chatmod.make_chat(None, settings, learn=False)
    assert chat.my_name() == "Red"
    companions.set_active("bruno", tmp_path)
    assert chat.my_name() == "Bruno"

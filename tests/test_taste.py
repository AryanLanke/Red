"""A companion's own taste and songs (red/taste.py), and how much it says (red/chat.py levels)."""

import json
import random

import pytest

from red import chat as chatmod
from red import companions, speech, taste
from red.chat import Chat, LEVELS, MAX_SENTENCES, invented_life

SHIPPED = ["red", "remy", "asha", "bruno", "winston"]
MAIN = ["red", "remy", "asha"]


# --- the packs ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("cid", SHIPPED)
def test_every_companion_has_fifteen_real_varied_songs(cid, tmp_path):
    c = companions.load(cid, tmp_path)
    assert len(c.songs) >= 15
    assert len({s.title for s in c.songs}) == len(c.songs), "no song twice"
    assert len({s.artist for s in c.songs}) >= 8, "varied, not one artist"
    assert len({m for s in c.songs for m in s.moods}) >= 4, "for more than one mood"
    for s in c.songs:
        assert s.title and s.artist and s.why and s.moods, s
        assert "whatever" not in s.query.lower()
        assert not invented_life(s.why), s.why


@pytest.mark.parametrize("cid", SHIPPED)
def test_taste_is_opinions_never_a_life(cid, tmp_path):
    c = companions.load(cid, tmp_path)
    assert {"music", "hates", "games", "films", "food", "takes"} <= set(c.taste)
    for kind, lines in c.taste.items():
        assert kind in companions.TASTE_KINDS
        for line in lines:
            assert not invented_life(line), line
            assert not chatmod.written_laughter(line)


def test_the_three_have_different_taste(tmp_path):
    loaded = {cid: companions.load(cid, tmp_path) for cid in MAIN}
    titles = {cid: {s.title for s in c.songs} for cid, c in loaded.items()}
    for a in MAIN:
        for b in MAIN:
            if a < b:
                assert len(titles[a] & titles[b]) <= 1, (a, b)
    assert len({loaded[cid].taste["games"] for cid in MAIN}) == 3


def test_songs_and_taste_pass_the_schema_and_bad_ones_are_dropped(tmp_path):
    good = {"id": "x", "name": "X"}
    assert companions.problems({**good, "songs": [["A", "B", "why", "calm"]], "taste": {"food": ["Tea."]}}) == []
    assert companions.problems({**good, "songs": [["only a title"]]})
    assert companions.problems({**good, "songs": "Believer"})
    assert companions.problems({**good, "taste": {"cars": ["Fast."]}})
    assert companions.problems({**good, "taste": {"food": "Tea."}})
    folder = tmp_path / "companions" / "red"
    folder.mkdir(parents=True)
    (folder / "companion.toml").write_text('songs = "Believer"\n[taste]\nfood = ["Tea, always."]\n', encoding="utf-8")
    red = companions.load("red", tmp_path)
    assert len(red.songs) >= 15, "a broken songs field falls back to the shipped list"
    assert red.taste["food"] == ("Tea, always.",), "the user's taste wins, kind by kind"
    assert red.taste["games"], "the other kinds stay"


# --- "play whatever you like" ------------------------------------------------------------------------

@pytest.mark.parametrize("query", [
    "whatever you like", "whatever", "anything you want", "something you like", "your favourite song",
    "your favorites", "surprise me", "something calm", "some music", "music", "something", "anything",
    "a song you'd pick", "you pick", "dealer's choice", "something to study to", "songs for the gym",
    "something upbeat", "a random song", "Something you love.", "one of yours",
])
def test_the_companion_chooses(query):
    assert taste.wants_own_pick(query)


@pytest.mark.parametrize("query", [
    "Believer", "something by Queen", "anything from Arijit Singh", "lofi beats", "the Punisher trailer",
    "my liked songs", "it", "the next song", "a podcast about loneliness", "Your Song by Elton John",
    "something like Daft Punk", "", "Imagine Dragons",
])
def test_the_user_chooses(query):
    assert not taste.wants_own_pick(query)


@pytest.mark.parametrize("cid", SHIPPED)
def test_a_pick_is_one_of_its_songs_with_a_reason_and_never_whatever(cid, tmp_path):
    c = companions.load(cid, tmp_path)
    pick = taste.own_pick("whatever you like", c, home=tmp_path, rng=random.Random(3))
    assert pick.song in c.songs
    assert pick.query == f"{pick.song.title} {pick.song.artist}" and "whatever" not in pick.query.lower()
    assert pick.song.title in pick.line and pick.song.artist in pick.line and pick.song.why in pick.line
    assert "\n" not in pick.line and not pick.line.rstrip().endswith("?"), "one line, not a question (Red would wait)"


def test_a_different_song_each_time_even_after_a_restart(tmp_path):
    c = companions.load("remy", tmp_path)
    titles = [taste.own_pick("surprise me", c, home=tmp_path, rng=random.Random(i)).song.title for i in range(30)]
    for i in range(1, len(titles)):
        assert titles[i] not in titles[max(0, i - taste.RECENT):i], "none of the last ten again"
    saved = json.loads((tmp_path / "cache" / "taste.json").read_text(encoding="utf-8"))
    assert saved["recent"]["remy"][-1] == titles[-1]


def test_the_mood_picks_a_fitting_song(tmp_path):
    c = companions.load("red", tmp_path)
    for i in range(6):
        pick = taste.own_pick("something calm", c, home=tmp_path, rng=random.Random(i))
        assert "calm" in pick.song.moods
    assert taste.mood_of("something to study to") == "focus"
    assert taste.mood_of("Believer") is None


def test_a_companion_without_songs_has_no_pick(tmp_path):
    assert taste.own_pick("whatever", companions.load("kira", tmp_path), home=tmp_path) is None


def test_the_lines_sound_like_each_companion(tmp_path):
    song = companions.Favourite("Song", "Band", "Because.", ("calm",))
    leads = {cid: {taste.pick_line(companions.load(cid, tmp_path), song, random.Random(i)) for i in range(20)}
             for cid in MAIN}
    assert all(line.endswith("Because.") for lines in leads.values() for line in lines)
    assert not (leads["red"] & leads["remy"]) and not (leads["remy"] & leads["asha"])
    assert any("!" in line for line in leads["remy"]) and not any("!" in line for line in leads["red"])


# --- taste in the prompt --------------------------------------------------------------------------------

def test_a_music_question_brings_a_few_songs_and_opinions(tmp_path):
    c = companions.load("red", tmp_path)
    text = taste.for_prompt(c, "What's your favourite song?", random.Random(1))
    lines = [x for x in text.splitlines() if x.startswith("- ")]
    assert 3 <= len(lines) <= taste.MAX_LINES
    assert any(s.title in text for s in c.songs)
    assert "not things you did" in text


def test_each_topic_brings_its_own_taste(tmp_path):
    c = companions.load("asha", tmp_path)
    assert any(g in taste.for_prompt(c, "I started a new game", random.Random(1)) for g in c.taste["games"])
    assert any(f in taste.for_prompt(c, "what should I eat?", random.Random(1)) for f in c.taste["food"])
    assert any(a in taste.for_prompt(c, "any anime worth it?", random.Random(1)) for a in c.taste["anime"])


def test_no_favourites_while_they_hurt_unless_they_ask(tmp_path):
    c = companions.load("remy", tmp_path)
    assert taste.for_prompt(c, "I'm feeling lonely.", random.Random(1)) == ""
    assert taste.for_prompt(c, "I'm sad, play me your favourite song", random.Random(1))


def test_plain_chat_gets_at_most_one_stray_opinion(tmp_path):
    text = taste.for_prompt(companions.load("red", tmp_path), "What's up?", random.Random(1))
    assert text.count("\n- ") == 1 and "only if it fits" in text


def test_help_with_a_mood_brings_songs_for_it(tmp_path):
    c = companions.load("remy", tmp_path)
    text = taste.for_prompt(c, "I need help, I can't focus on my homework.", random.Random(1))
    focus = [s for s in c.songs if "focus" in s.moods]
    assert any(s.title in text for s in focus)


def test_the_chat_prompt_carries_taste_but_the_system_prompt_stays_fixed(tmp_path):
    chat = Chat(None, persona=lambda: companions.load("red", tmp_path), rng=random.Random(2))
    first = chat.system()
    prompt = chat.prompt("What music do you like?")
    assert "Your own taste" in prompt and prompt.index("Your own taste") < prompt.index("Conversation so far")
    chat.prompt("Do you like anime?")
    assert chat.system() == first, "taste goes after the cached system prompt"
    chat.begin_debate("cats")
    assert "Your own taste" not in chat.prompt("music?")


# --- how much they say --------------------------------------------------------------------------------

class StreamLLM:
    def __init__(self, text):
        self.text = text
        self.systems = []

    def stream_json(self, system, user, schema, **kw):
        self.systems.append(system)
        raw = json.dumps({"reply": self.text})
        for i in range(0, len(raw), 9):
            yield raw[i:i + 9]


class Recorder:
    cancelled = False

    def __init__(self):
        self.spoken = []

    def say(self, text):
        self.spoken.append(text)


SEVEN = "Oh nice. One. Two. Three. Four. Five. Six?"


@pytest.mark.parametrize("level, said", [("companion", 5), ("chatty", 4), ("friendly", 3), ("quiet", 2)])
def test_the_level_sets_how_much_is_said(level, said, tmp_path):
    llm = StreamLLM(SEVEN)
    chat = Chat(llm, persona=lambda: companions.load("red", tmp_path), chattiness=lambda: level)
    rec = Recorder()
    with speech.speaking_to(rec):
        chat.reply("I got a new keyboard.")
    assert len(rec.spoken) == said == MAX_SENTENCES[level]
    assert LEVELS[level] in llm.systems[0]


def test_the_packs_level_applies_unless_the_user_set_one(tmp_path, monkeypatch):
    chat = Chat(None, persona=lambda: companions.load("asha", tmp_path))
    assert chat.level() == "companion" and LEVELS["companion"] in chat.system()
    assert companions.load("winston", tmp_path).chattiness == "friendly"
    chat.chattiness = lambda: "friendly"
    assert chat.level() == "friendly" and LEVELS["friendly"] in chat.system()
    chat.chattiness = lambda: "nonsense"
    assert chat.level() == "companion"


def test_make_chat_follows_red_chattiness_only_when_it_is_set(tmp_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.delenv("RED_CHATTINESS", raising=False)
    monkeypatch.delenv("RED_COMPANION", raising=False)
    chat = chatmod.make_chat(None, SimpleNamespace(home=tmp_path, chattiness="friendly"), learn=False)
    assert chat.level() == "companion"          # Red's own pack
    monkeypatch.setenv("RED_CHATTINESS", "quiet")
    chat = chatmod.make_chat(None, SimpleNamespace(home=tmp_path, chattiness="quiet"), learn=False)
    assert chat.level() == "quiet"


def test_the_main_three_keep_the_conversation_going(tmp_path):
    for cid in MAIN:
        assert companions.load(cid, tmp_path).chattiness == "companion"


def test_a_debate_uses_the_companions_name(tmp_path):
    chat = Chat(None, persona=lambda: companions.load("asha", tmp_path))
    chat.begin_debate("cats")
    assert chat.system().startswith("You are Asha,")
    assert Chat(None).system() == chatmod.CHAT_SYSTEM


@pytest.mark.parametrize("line", [
    "I listened to Nujabes this morning.", "I've been playing Hades all week.", "I played it twice.",
    "I've watched that film three times.",
])
def test_taste_told_as_a_life_is_dropped(line):
    assert chatmod.human(line) == ""


@pytest.mark.parametrize("line", ["I'd put on Nujabes for this.", "Hades is tight, fair and fast.",
                                  "I've heard good things about it."])
def test_taste_told_as_an_opinion_is_kept(line):
    assert chatmod.human(line) == line

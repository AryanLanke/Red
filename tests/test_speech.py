"""red.speech: reading the streamed JSON, cutting sentences, speaking them in turn. No audio."""

import json
import threading

import numpy as np
import pytest

from red import speech as sp


def feed(key, pieces):
    reader = sp.JsonFieldReader(key)
    return "".join(reader.feed(p) for p in pieces), reader.done


def test_reads_the_field_as_it_arrives():
    raw = json.dumps({"answer": 'Line one.\nShe said "hi" \\ ok. Café \U0001F600 done.'})
    for size in (1, 2, 3, 7, 50):
        pieces = [raw[i:i + size] for i in range(0, len(raw), size)]
        text, done = feed("answer", pieces)
        assert text == 'Line one. She said "hi" \\ ok. Café \U0001F600 done.' and done


def test_stops_at_the_closing_quote_and_ignores_junk_after():
    text, done = feed("reply", ['{"reply": "Hi there."}', '\n```json\n{"reply": "again"'])
    assert text == "Hi there." and done


def test_nothing_until_the_field_starts():
    reader = sp.JsonFieldReader("answer")
    assert reader.feed('{"ans') == "" and reader.feed('wer": "Yes') == "Yes"


@pytest.mark.parametrize("pieces, expected", [
    (["Hello there. How", " are you? Fine!"], ["Hello there.", "How are you?", "Fine!"]),
    (["Mount Everest is 8,848.86 m", " tall. It's in Nepal."], ["Mount Everest is 8,848.86 m tall.", "It's in Nepal."]),
    (["Mr. Smith met Dr. Jones in the U.S. last year. Then", " they left."],
     ["Mr. Smith met Dr. Jones in the U.S. last year.", "Then they left."]),
    (["e.g. this one. ", "And that."], ["e.g. this one.", "And that."]),
    (["One line\nAnother line"], ["One line", "Another line"]),
    (["No end"], ["No end"]),
    ([], []),
])
def test_sentences(pieces, expected):
    assert list(sp.sentences(pieces)) == expected


def test_a_sentence_comes_out_before_the_rest_is_written():
    seen = []

    def pieces():
        for p in ["First one. ", "Second", " one. ", "Third."]:
            seen.append(p)
            yield p
    it = sp.sentences(pieces())
    assert next(it) == "First one."
    assert seen == ["First one. "]                    # out before the next piece is even written


class StreamLLM:
    def __init__(self, raw, size=4):
        self.raw, self.size, self.closed, self.kwargs = raw, size, False, None

    def stream_json(self, system, user, schema, **kw):
        self.kwargs = kw
        try:
            for i in range(0, len(self.raw), self.size):
                yield self.raw[i:i + self.size]
        finally:
            self.closed = True


def test_stream_field_streams_and_closes():
    llm = StreamLLM(json.dumps({"answer": "Yes. Really."}) + "junk junk junk")
    assert "".join(sp.stream_field(llm, "s", "u", {}, "answer", images=None, temperature=0.5)) == "Yes. Really."
    assert llm.closed and llm.kwargs == {"temperature": 0.5}


def test_stream_field_without_streaming_asks_once():
    class Plain:
        def complete_json(self, system, user, schema, **kw):
            return json.dumps({"reply": "Hi."})
    assert list(sp.stream_field(Plain(), "s", "u", {}, "reply")) == ["Hi."]


class Player:
    def __init__(self, log):
        self.log = log

    def play(self, audio, rate):
        self.log.append(f"play {int(audio[0])}")

    def wait(self):
        self.log.append("wait")

    def stop(self):
        self.log.append("stop")


class Voice:
    """synthesize() and player, like tts.Speaker."""

    def __init__(self):
        self.log = []
        self.player = Player(self.log)
        self.gate = None

    def synthesize(self, text):
        if self.gate is not None:
            self.gate.wait(2)
        self.log.append(f"make {text}")
        return np.full(10, len(self.log), dtype=np.float32), 22050

    def stop(self):
        self.log.append("stop")


def test_the_next_sentence_is_made_while_the_last_one_plays():
    voice = Voice()
    stream = sp.SpeechStream(voice, clock=lambda: 42.0)
    stream.say("One.")
    stream.say("Two.")
    stream.finish(timeout=5)
    assert voice.log == ["make One.", "play 1", "make Two.", "wait", "play 3", "wait"]
    assert stream.spoken == ["One.", "Two."] and stream.first_word_at == 42.0


def test_cancel_stops_at_once():
    voice = Voice()
    voice.gate = threading.Event()
    stream = sp.SpeechStream(voice)
    stream.say("One.")
    stream.say("Two.")
    stream.cancel()
    voice.gate.set()
    stream.finish(timeout=5)
    assert stream.cancelled and "play 3" not in voice.log and "stop" in voice.log
    stream.say("Three.")                              # ignored after cancel
    assert stream.spoken == ["One.", "Two."]


def test_a_speaker_without_synthesize_says_each_sentence():
    said = []

    class Simple:
        def say(self, text, block=True):
            said.append(text)

        def stop(self):
            pass
    texts = []
    stream = sp.SpeechStream(Simple(), on_text=texts.append)
    stream.say("One.")
    stream.say(" Two. ")
    stream.finish(timeout=5)
    assert said == ["One.", "Two."] and texts == ["One.", "One. Two."]


@pytest.mark.parametrize("text, pause", [
    ("Done.", sp.SENTENCE_PAUSE),
    ("Really?", sp.SENTENCE_PAUSE),
    ("Well,", sp.COMMA_PAUSE),
    ("some people do...", sp.LONG_PAUSE),
    ("I mean…", sp.LONG_PAUSE),
    ("and then -", sp.LONG_PAUSE),
    ('He said "wait..."', sp.LONG_PAUSE),
])
def test_the_pause_follows_the_punctuation(text, pause):
    assert sp.pause_after(text) == pause


def test_short_sentences_stay_whole():
    assert sp.speech_pieces("Okay, sure, why not.") == ["Okay, sure, why not."]


def test_a_trail_off_is_its_own_piece():
    assert sp.speech_pieces("Rust if you enjoy arguing with a compiler... some people really do.") == [
        "Rust if you enjoy arguing with a compiler...", "some people really do."]


def test_a_long_sentence_is_cut_at_its_commas():
    long = ("If you want to ship something this month, pick Go, because the tooling is simple "
            "and the builds are fast, and you can always learn Rust later.")
    pieces = sp.speech_pieces(long)
    assert len(pieces) == 3 and " ".join(pieces) == long
    assert pieces[0].endswith("month,") and pieces[1].endswith("fast,")


def test_no_scraps_from_cutting():
    pieces = sp.speech_pieces("Well, " + "this sentence is long enough to be cut at its commas " * 2 + "ok.")
    assert all(len(p) >= 20 for p in pieces)


def test_pieces_are_spoken_with_their_own_pauses():
    voice = Voice()
    slept = []
    stream = sp.SpeechStream(voice, sleep=slept.append)
    stream.say("Rust if you enjoy arguing with a compiler... some people really do.")
    stream.say("Two.")
    stream.finish(timeout=5)
    made = [line for line in voice.log if line.startswith("make")]
    assert made == ["make Rust if you enjoy arguing with a compiler...",
                    "make some people really do.", "make Two."]
    assert slept == [sp.LONG_PAUSE, sp.SENTENCE_PAUSE]


def test_kokoros_own_breath_counts_toward_the_pause():
    from red.tts_kokoro import PAUSE_SECONDS
    voice = Voice()
    voice.using_fallback = False                     # like KokoroSpeaker with Kokoro loaded
    assert sp.breath_of(voice) == PAUSE_SECONDS and sp.breath_of(Voice()) == 0.0
    slept = []
    stream = sp.SpeechStream(voice, sleep=slept.append)
    stream.say("One.")
    stream.say("Two.")
    stream.finish(timeout=5)
    assert slept == [pytest.approx(sp.SENTENCE_PAUSE - PAUSE_SECONDS)]


def test_speaking_to_is_per_thread_and_restored():
    stream = sp.SpeechStream(Voice())
    assert sp.current() is None
    with sp.speaking_to(stream):
        assert sp.current() is stream
        other = []
        t = threading.Thread(target=lambda: other.append(sp.current()))
        t.start()
        t.join()
        assert other == [None]
    assert sp.current() is None

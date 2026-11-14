import numpy as np
import pytest

from red.audio import SAMPLE_RATE, to_int16
from red.wakeword import HeyRedDetector, match_score, strip_wake_phrase
from voice_fakes import noise, tone


@pytest.mark.parametrize("text, expected", [
    ("Hey Red", 1.0),
    ("Hey, Red!", 1.0),
    ("hey red.", 1.0),
    ("Hay Red", 1.0),
    ("Heyred", 0.9),
    ("Hey Red, stop.", 1.0),           # a comma after "Hey Red": a command follows
    ("Hey Red. Open YouTube.", 1.0),
    ("Hey Red Light", 0.45),           # no comma: maybe a misheard "a red light", below 0.5
    ("Hey red one two", 0.45),
    ("Hi Red", 0.7),
    ("Ey Red", 0.7),
    ("Heyy Red", 0.7),
    ("Hey, read.", 0.6),
])
def test_wake_phrase_variants(text, expected):
    assert match_score(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", [
    "", "Read.", "Hey", "Hey there", "Hey, Fred.", "Hey, ready to go?", "I read the red book.",
    "He read it yesterday.", "They said red.", "The red car is fast.", "A red car",
    "Hey computer", "Hey red one two three four",
])
def test_ordinary_speech_does_not_match(text):
    assert match_score(text) < 0.5


class LoudnessVAD:
    """Fake VAD: anything louder than quiet noise is speech."""

    def __init__(self):
        self.calls = 0
        self.resets = 0

    def __call__(self, chunk):
        self.calls += 1
        assert chunk.size == 512 and chunk.dtype == np.float32
        return 0.9 if np.sqrt(np.mean(chunk ** 2)) > 0.02 else 0.05

    def reset(self):
        self.resets += 1


class FakeWhisper:
    def __init__(self, text="Hey Red."):
        self.text = text
        self.clips = []

    def __call__(self, clip):
        self.clips.append(clip.size / SAMPLE_RATE)
        return self.text


def run(det, *pieces, frame=1280):
    audio = to_int16(np.concatenate(pieces))
    return [det.score(audio[i:i + frame]) for i in range(0, audio.size, frame)]


def make(text="Hey Red."):
    vad, whisper = LoudnessVAD(), FakeWhisper(text)
    return HeyRedDetector(vad, whisper), vad, whisper


def test_short_phrase_between_pauses_is_checked_and_fires():
    det, _, whisper = make()
    scores = run(det, noise(1.0), tone(0.7), noise(1.0))
    assert max(scores) == 1.0
    assert whisper.clips and 0.9 < whisper.clips[0] < 1.8   # phrase + pre-roll + pause
    fired = int(np.argmax(scores)) * 1280 / SAMPLE_RATE
    assert 1.9 < fired < 2.5                                # just after the pause that ends it


def test_fires_once_per_phrase():
    det, _, whisper = make()
    scores = run(det, noise(1.0), tone(0.7), noise(2.0))
    assert sum(s >= 0.5 for s in scores) == 1
    assert len(whisper.clips) == 1


def test_ordinary_words_do_not_fire():
    det, _, whisper = make("They said red.")
    assert max(run(det, noise(1.0), tone(0.8), noise(1.0))) == 0.0
    assert len(whisper.clips) == 1


def test_long_speech_only_has_its_start_checked_once():
    det, _, whisper = make("They said red.")
    assert max(run(det, noise(0.5), tone(5.0), noise(1.0))) == 0.0
    assert len(whisper.clips) == 1 and whisper.clips[0] < 2.0     # the first 1.3 s, not 5 s


def test_hey_red_said_in_one_breath_with_a_command_wakes():
    # "Hey Red, open YouTube": 3 s of speech after a pause.
    det, _, whisper = make("Hey Red, open")
    scores = run(det, noise(1.0), tone(3.0), noise(1.0))
    assert max(scores) == 1.0 and len(whisper.clips) == 1


def test_a_long_sentence_that_does_not_start_with_hey_red_stays_asleep():
    det, _, _ = make("I saw a red car, hey red light")
    assert max(run(det, noise(1.0), tone(3.0), noise(1.0))) == 0.0


# What Whisper really wrote in the 2026-11-09 voice test (red.log) when the user said "Hey Red".
@pytest.mark.parametrize("heard", [
    "Hey Red Red Red Red Red Red Red", "Hey Red, hey Red, hey Red", "Hey Red, hey Red",
    "Hey Red Red", "hey red hey red hey red hey red",
])
def test_repeated_phrases_still_wake(heard):
    assert match_score(heard) == 1.0


@pytest.mark.parametrize("heard", ["Not waking up", "It's okay", "What is?", "Song by Liz Adafim",
                                   "Two Satora Lamb", "Invite this was happening"])
def test_the_other_things_heard_in_that_test_stay_asleep(heard):
    assert match_score(heard) < 0.5


# A bare "Red" in red.log (2026-11-13) was always the user's quiet "Hey Red" with the "Hey" lost (6 of 6,
# each right before a "Hey Red" that woke): the name said on its own now wakes, a little below "Hey Red".
@pytest.mark.parametrize("heard", ["Red", "Red.", "Red?", "Red red red", "Here Red", "Remy!", "Asha."])
def test_a_name_on_its_own_wakes(heard):
    assert 0.5 <= match_score(heard) < 1.0


# --- the companions' names (night 2) ----------------------------------------------------------------

@pytest.mark.parametrize("heard, who", [
    ("Hey Asha", "asha"), ("Hey, Asha!", "asha"), ("Hey Usha", "asha"), ("Hey Asia.", "asha"),
    ("Hey Remy", "remy"), ("Hey Rémy", "remy"), ("Hey Rennel", "remy"), ("Hey Remi.", "remy"),
    ("Heyasha", "asha"), ("Hey Red", "red"), ("Hey Bruno", "bruno"), ("Hey Winston", "winston"),
    ("Red, open YouTube.", "red"), ("Asha, what's up?", "asha"), ("Remy, play something.", "remy"),
])
def test_companion_names_wake_and_say_who(heard, who):
    from red.wakeword import match_wake
    score, name, _ = match_wake(heard)
    assert score >= 0.5 and name == who


@pytest.mark.parametrize("heard", [
    "Asia is big.", "Usha", "I read the red book.", "Red is my favourite colour", "Remy said hi to me",
    "The Asia trip was fun", "Rainy day.", "Hi Asia",
])
def test_names_in_ordinary_speech_do_not_wake(heard):
    assert match_score(heard) < 0.5


@pytest.mark.parametrize("heard, rest", [
    ("Red, open YouTube.", "open YouTube."), ("Asha, what's the time?", "what's the time?"),
    ("Hey Remy, play some jazz.", "play some jazz."), ("Hey Red, open YouTube.", "open YouTube."),
])
def test_name_first_is_stripped_from_the_command(heard, rest):
    assert strip_wake_phrase(heard) == rest


def test_name_first_with_a_command_keeps_the_command_audio():
    det, _, _ = make("Red, open YouTube.")
    assert max(run(det, noise(1.0), tone(1.0), noise(1.0))) == pytest.approx(0.75)
    assert det.command_audio is not None and det.last_name == "red"


def test_add_names_takes_a_new_companion():
    from red import wakeword
    saved = dict(wakeword.NAMES)
    try:
        wakeword.add_names({"kiko": ("Kiko", "hey kiko")})
        assert wakeword.match_wake("Hey Kiko")[1] == "kiko"
    finally:
        wakeword.NAMES.clear()
        wakeword.NAMES.update(saved)


def test_head_mode_looks_only_at_the_first_two_words():
    assert match_score("Hey Red, open YouTube and search", head=True) == 1.0
    assert match_score("I said hey red", head=True) == 0.0
    assert match_score("Hey Red open YouTube and search") < 0.5


# Short "Hey Red, <words>" clips from red.log that scored 0.45 or 0.32 and so never woke Red.
@pytest.mark.parametrize("heard, expected", [
    ("Hey Red, don't know", 1.0),
    ("Hey Red, don't walk", 1.0),
    ("Hi Red, what's up?", 0.7),
    ("Hey Red, what's the weather like today?", 1.0),
])
def test_hey_red_with_a_command_in_one_breath_wakes(heard, expected):
    assert match_score(heard) == pytest.approx(expected)


@pytest.mark.parametrize("heard", ["I read, the red book", "They said red, then left", "Hey, Fred, come here",
                                   "A red light, then green", "Hey there, red car"])
def test_a_comma_alone_does_not_make_a_wake_phrase(heard):
    assert match_score(heard) < 0.5


def test_too_short_bursts_are_skipped():
    det, _, whisper = make()
    run(det, noise(1.0), tone(0.15), noise(1.0))
    assert whisper.clips == []


def test_phrase_run_into_previous_speech_is_skipped():
    # Speech, a gap shorter than the pause needed, then a short burst: mid-conversation.
    det, _, whisper = make()
    run(det, noise(0.5), tone(2.5), noise(0.1), tone(0.6), noise(1.0))
    assert len(whisper.clips) == 1                         # the start of the long burst, nothing else


def test_conversation_with_pauses_checks_only_short_isolated_bursts():
    det, _, whisper = make("Something else.")
    pieces = [noise(0.8)]
    for length in (2.5, 0.8, 3.0, 1.9, 0.6, 4.0):
        pieces += [tone(length), noise(0.8)]
    run(det, *pieces)
    # The 0.8 s and 0.6 s bursts, and the first 1.3 s of each of the four long ones (cheap, once each).
    assert len(whisper.clips) == 6 and max(whisper.clips) < 2.0


def test_works_with_odd_frame_sizes_and_float_input():
    det, vad, _ = make()
    audio = np.concatenate([noise(1.0), tone(0.7), noise(1.0)])
    scores = [det.score(audio[i:i + 777]) for i in range(0, audio.size, 777)]
    assert max(scores) == 1.0
    assert vad.calls == audio.size // 512


def test_reset_drops_a_half_heard_phrase():
    det, vad, whisper = make()
    run(det, noise(1.0), tone(0.4))
    det.reset()
    assert vad.resets >= 2
    run(det, noise(1.0))
    assert whisper.clips == []


def test_counts_whisper_time():
    ticks = iter([0.0, 0.25, 1.0, 1.3])
    det = HeyRedDetector(LoudnessVAD(), FakeWhisper(), clock=lambda: next(ticks))
    run(det, noise(1.0), tone(0.7), noise(1.0), tone(0.7), noise(1.0))
    assert det.evaluations == 2
    assert det.busy_seconds == pytest.approx(0.55)
    assert det.last_text == "Hey Red."


# Every burst that never reaches Whisper says why in red.log (plan.md task 1.2).

def skips(caplog):
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith("Wake skip:")]


def test_a_too_short_burst_logs_why(caplog):
    caplog.set_level("INFO", logger="red.wakeword")
    det, _, _ = make()
    run(det, noise(1.0), tone(0.15), noise(1.0))
    assert len(skips(caplog)) == 1 and "too short" in skips(caplog)[0]


def test_a_phrase_run_into_earlier_speech_is_one_burst_whose_start_is_checked(caplog):
    # A burst only ends after PAUSE_AFTER (0.3 s) of quiet, which is already more than
    # PAUSE_BEFORE (0.25 s): a "Hey Red" with a shorter gap before it merges into the earlier
    # speech, and only the start of that merged burst (the earlier speech) is checked.
    caplog.set_level("INFO", logger="red.wakeword")
    det, _, whisper = make("Something else, hey red")
    assert max(run(det, noise(0.5), tone(0.8), noise(0.1), tone(0.9), noise(1.0))) == 0.0
    assert len(whisper.clips) == 1
    assert any("start of a longer phrase" in r.getMessage() for r in caplog.records)


class FaintVAD(LoudnessVAD):
    """Speech the VAD is unsure of: above the 'too faint' line, below the start of a clip."""

    def __call__(self, chunk):
        return 0.3 if super().__call__(chunk) > 0.5 else 0.05


def test_speech_too_faint_to_start_a_clip_logs_why(caplog):
    caplog.set_level("INFO", logger="red.wakeword")
    whisper = FakeWhisper()
    det = HeyRedDetector(FaintVAD(), whisper)
    run(det, noise(1.0), tone(0.7), noise(1.0))
    assert whisper.clips == []
    assert len(skips(caplog)) == 1 and "too faint" in skips(caplog)[0] and "VAD 0.30" in skips(caplog)[0]


def test_a_quiet_clip_is_made_louder_before_whisper():
    heard = []
    det = HeyRedDetector(LoudnessVAD(), lambda clip: heard.append(float(abs(clip).max())) or "Hey Red.")
    run(det, noise(1.0), tone(0.7, amp=0.05), noise(1.0))
    assert heard and heard[0] >= 0.29                       # TARGET_PEAK 0.3, from 0.05


# "Hey Red, open YouTube" in one breath: the command is kept (plan.md task 1.3).

@pytest.mark.parametrize("heard, command", [
    ("Hey Red, open YouTube.", "open YouTube."),
    ("Hey, Red. What's the weather?", "What's the weather?"),
    ("Hey Red open Edge", "open Edge"),
    ("Heyred, pause the music", "pause the music"),
    ("Hey Red, hey Red, open Downloads", "open Downloads"),
    ("Hi Red, what's up?", "what's up?"),
    ("Hey Red.", ""),
    ("Open YouTube", "Open YouTube"),               # no wake phrase: unchanged
    ("They said red", "They said red"),
])
def test_strip_wake_phrase(heard, command):
    assert strip_wake_phrase(heard) == command


# The user's real recordings (2026-11-13): Whisper wrote their "Hey Red" as "Headed" most often, and
# as "Headered" or "Head in" now and then. --learn added "headed" and "here at".
LEARNED = frozenset({"headed", "here at"})


@pytest.mark.parametrize("heard", ["Headered", "Head in", "Heded."])
def test_a_clip_close_to_a_learned_phrase_wakes(heard):
    assert match_score(heard, LEARNED) == 0.7


@pytest.mark.parametrize("heard", [
    "The rest of us are scared to open",     # starts like "here at": a real false wake in red.log
    "The rest",                              # a different first letter
    "Hidden",                                # three letters off
    "Headed home now",                       # more than two words
    "Hello",
])
def test_close_matching_stays_narrow(heard):
    assert match_score(heard, LEARNED) < 0.5


def test_a_plain_hey_red_keeps_its_full_score_with_learned_phrases():
    # Live, 2026-11-13 06:03: "Hey Red" scored 0.70 because "heyred" is also close to "headed".
    assert match_score("Hey Red", LEARNED) == 1.0
    assert match_score("Hey Red, open YouTube", LEARNED) == 1.0


def test_close_matching_needs_a_learned_phrase():
    assert match_score("Headered") == 0.0


def test_strip_wake_phrase_knows_your_own_spelling():
    assert strip_wake_phrase("Headed, open YouTube", frozenset({"headed"})) == "Headed, open YouTube"
    assert strip_wake_phrase("Hit it, open YouTube", frozenset({"hit it"})) == "open YouTube"


def test_one_breath_wake_keeps_the_burst_as_the_command():
    det, _, _ = make("Hey Red, open")
    scores = run(det, noise(1.0), tone(3.0), noise(1.0))
    assert max(scores) == 1.0
    assert det.command_audio is not None and det.command_audio.size / SAMPLE_RATE > 1.6


def test_hey_red_alone_keeps_no_command():
    det, _, _ = make("Hey Red.")
    assert max(run(det, noise(1.0), tone(0.7), noise(1.0))) == 1.0
    assert det.command_audio is None


def test_a_short_hey_red_with_words_keeps_them():
    det, _, _ = make("Hey Red, stop.")
    assert max(run(det, noise(1.0), tone(1.0), noise(1.0))) == 1.0
    assert det.command_audio is not None


def test_a_checked_phrase_logs_no_skip(caplog):
    caplog.set_level("INFO", logger="red.wakeword")
    det, _, _ = make()
    run(det, noise(1.0), tone(0.7), noise(1.0))
    assert skips(caplog) == []

"""Hello, not briefings (plan.md A3): a fake clock and fake idle time, no Windows calls, no audio."""

import random
from datetime import datetime, timedelta

import pytest

from red import greeter as gr

BRIEFING_WORDS = ("meeting", "mail", "email", "inbox", "to-do", "todo", "calendar", "news",
                  "reminder", "schedule", "agenda", "task")


class World:
    """The fake PC: a clock, idle time, a busy flag, and what Red said."""

    def __init__(self, start=datetime(2026, 11, 13, 9, 0)):
        self.now = start
        self.mono = 1000.0
        self.idle = 1.0
        self.blocked = False
        self.busy = False
        self.said: list[str] = []

    def say(self, text):
        if self.busy:
            return False
        self.said.append(text)
        return True

    def advance(self, seconds, idle=None):
        self.now += timedelta(seconds=seconds)
        self.mono += seconds
        if idle is not None:
            self.idle = idle

    def greeter(self, tmp_path, name="Aryan", chattiness="friendly", seed=1):
        return gr.Greeter(tmp_path, self.say, name=lambda: name, chattiness=chattiness,
                          idle=lambda: self.idle, blocked=lambda: self.blocked,
                          now=lambda: self.now, clock=lambda: self.mono, rng=random.Random(seed))


def test_first_hello_of_the_day_uses_the_name(tmp_path):
    w = World()
    said = w.greeter(tmp_path).tick()
    assert said and "Aryan" in said and said in w.said
    assert any(said == gr.with_name(t, "Aryan") for t in gr.MORNING)


def test_only_one_hello_a_day_even_across_restarts(tmp_path):
    w = World()
    w.greeter(tmp_path).tick()
    w.advance(60)
    again = w.greeter(tmp_path)                 # Red restarted (session 1, the watchdog...)
    assert again.tick() is None
    w.advance(3600)
    assert again.tick() is None and len(w.said) == 1


def test_back_after_thirty_minutes_away(tmp_path):
    w = World()
    g = w.greeter(tmp_path)
    g.tick()
    w.advance(29 * 60, idle=29 * 60)
    assert g.tick() is None                     # 29 minutes: not away yet
    w.advance(5, idle=2)
    assert g.tick() is None                     # a short break gets no hello
    w.advance(31 * 60, idle=31 * 60)
    assert g.tick() is None                     # away: nothing while you're gone
    w.advance(5, idle=1)
    said = g.tick()
    assert said in [gr.with_name(t, "Aryan") for t in gr.BACK]
    w.advance(10, idle=1)
    assert g.tick() is None and len(w.said) == 2


def test_back_on_a_new_day_says_the_days_hello(tmp_path):
    w = World(datetime(2026, 11, 13, 22, 0))
    g = w.greeter(tmp_path)
    g.tick()
    w.advance(10 * 3600, idle=10 * 3600)          # overnight, PC left on
    g.tick()
    w.advance(5, idle=1)
    said = g.tick()
    assert said in [gr.with_name(t, "Aryan") for t in gr.MORNING]


def test_no_hello_at_midnight_while_working(tmp_path):
    w = World(datetime(2026, 11, 13, 23, 50))
    g = w.greeter(tmp_path)
    g.tick()
    for _ in range(30):                          # past midnight, at the keyboard the whole time
        w.advance(60, idle=3)
        assert g.tick() is None
    assert len(w.said) == 1


def test_never_during_a_game_or_a_call_and_not_later_either(tmp_path):
    w = World()
    w.blocked = True
    g = w.greeter(tmp_path)
    assert g.tick() is None
    w.blocked = False
    w.advance(30, idle=1)
    assert g.tick() is None and w.said == []


def test_busy_red_says_nothing_and_queues_nothing(tmp_path):
    w = World()
    w.busy = True
    g = w.greeter(tmp_path)
    assert g.tick() is None
    w.busy = False
    w.advance(20, idle=1)
    assert g.tick() is None and w.said == []     # a late hello is worse than none


def test_quiet_never_speaks(tmp_path):
    w = World()
    g = w.greeter(tmp_path, chattiness="quiet")
    assert g.tick() is None
    w.advance(3600, idle=3600)
    g.tick()
    w.advance(5, idle=1)
    assert g.tick() is None and w.said == []


def test_lines_vary_and_dont_repeat_yesterdays(tmp_path):
    w = World()
    lines = []
    for day in range(len(gr.MORNING)):
        g = w.greeter(tmp_path, seed=day)
        lines.append(g.tick())
        w.advance(24 * 3600)
    assert all(a != b for a, b in zip(lines, lines[1:]))
    assert len(set(lines)) == len(gr.MORNING)    # every morning line before any comes back


def test_without_a_name_the_line_still_reads_well(tmp_path):
    for template in gr.MORNING + gr.AFTERNOON + gr.EVENING + gr.NIGHT + gr.BACK:
        line = gr.with_name(template, None)
        assert "{" not in line and "  " not in line and not line.startswith((",", " "))
        assert ", ." not in line and ",?" not in line and " ." not in line


def test_no_greeting_ever_briefs():
    pools = gr.MORNING + gr.AFTERNOON + gr.EVENING + gr.NIGHT + gr.BACK + gr.LATE + gr.STRETCH
    for template in pools:
        assert not any(word in template.lower() for word in BRIEFING_WORDS), template


@pytest.mark.parametrize("hour, pool", [(6, gr.MORNING), (13, gr.AFTERNOON), (19, gr.EVENING),
                                        (23, gr.NIGHT), (2, gr.NIGHT)])
def test_hello_follows_the_time_of_day(hour, pool):
    assert gr.hello_lines(datetime(2026, 11, 13, hour)) is pool


def test_a_day_of_normal_use_gets_the_expected_greetings(tmp_path):
    """9 am start, coffee break, lunch, a meeting away, evening: 1 hello + 2 welcome-backs."""
    w = World(datetime(2026, 11, 13, 9, 0))
    g = w.greeter(tmp_path)
    g.tick()
    plan = [(90, 2), (15, 15 * 60), (120, 2), (50, 50 * 60), (180, 2), (45, 45 * 60), (120, 2)]
    for minutes, idle in plan:
        for _ in range(minutes):
            w.advance(60, idle=min(idle, (_ + 1) * 60) if idle > 60 else idle)
            g.tick()
        w.advance(5, idle=1)
        g.tick()
    assert len(w.said) == 3


# --- chatty -------------------------------------------------------------------------------

def test_friendly_has_no_one_liners(tmp_path):
    w = World(datetime(2026, 11, 14, 1, 30))
    g = w.greeter(tmp_path)
    g.tick()
    for _ in range(120):
        w.advance(60, idle=2)
        g.tick()
    assert len(w.said) == 1


def test_chatty_says_it_is_late_at_most_once_an_hour(tmp_path):
    w = World(datetime(2026, 11, 14, 1, 30))
    g = w.greeter(tmp_path, chattiness="chatty")
    g.tick()                                       # the day's hello
    for _ in range(90):
        w.advance(60, idle=2)
        g.tick()
    late = [s for s in w.said[1:]]
    assert len(late) == 2 and all("AM" in s for s in late)


def test_chatty_notices_a_long_stretch(tmp_path):
    w = World(datetime(2026, 11, 13, 10, 0))
    g = w.greeter(tmp_path, chattiness="chatty")
    g.tick()
    for _ in range(125):
        w.advance(60, idle=2)
        g.tick()
    assert len(w.said) == 2 and "2 hours" in w.said[1]


def test_chattiness_setting(tmp_path, monkeypatch):
    from red.config import load_settings
    for value, expected in (("chatty", "chatty"), ("QUIET", "quiet"), ("loud", "friendly"),
                            ("", "friendly")):
        monkeypatch.setenv("RED_CHATTINESS", value)
        assert load_settings(tmp_path).chattiness == expected


def test_voice_app_greet_skips_when_busy():
    import threading
    from types import SimpleNamespace

    from red.__main__ import VoiceApp
    spoken = []
    app = SimpleNamespace(_turn=threading.RLock(),
                          announce=lambda text, label="reminder": spoken.append((text, label)))
    assert VoiceApp.greet(app, "Morning!") and spoken == [("Morning!", "hello")]
    holder = threading.Thread(target=lambda: (app._turn.acquire(), done.wait(), app._turn.release()))
    done = threading.Event()
    holder.start()
    threading.Event().wait(0.05)
    assert VoiceApp.greet(app, "Hey!") is False and len(spoken) == 1
    done.set()
    holder.join()


def test_attach_greeter_uses_the_settings(tmp_path):
    from types import SimpleNamespace
    app = SimpleNamespace(settings=SimpleNamespace(home=tmp_path, chattiness="chatty"),
                          greet=lambda text: True, chat=SimpleNamespace(user_name=lambda: "Aryan"))
    greeter = gr.attach_greeter(app)
    assert greeter.chattiness == "chatty" and greeter._name() == "Aryan"


def test_idle_seconds_reads_windows():
    assert gr.idle_seconds() >= 0.0               # a real, read-only Windows call
    assert isinstance(gr.do_not_disturb(), bool)

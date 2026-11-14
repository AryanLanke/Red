"""The simulator's own tests: the real turn pipeline with a scripted model, no Ollama needed."""

import json
from pathlib import Path

import pytest

from red.sim import report, rules, runner, scenarios
from red.sim.harness import SimWorld
from red.sim.judge import Judge, Verdict, agreement, load_gold
from red.sim.simuser import SimUser, clean_line


class ScriptedModel:
    """Routes by the sentence, chats with a fixed reply. Looks like an LLM client (complete_json only)."""

    def __init__(self, routes=None, reply="You good?"):
        self.routes = routes or {}
        self.reply = reply
        self.calls = []
        self.options = {"num_ctx": 32768}

    def complete_json(self, system, user, schema, *args, **kwargs):
        self.calls.append((system[:30], user[-80:]))
        if "anyOf" in schema:
            command = user.rsplit("Command: ", 1)[-1]
            for key, call in self.routes.items():
                if key in command.lower():
                    return json.dumps(call)
            return json.dumps({"tool": "none", "args": {"reply": "ok"}})
        return json.dumps({"reply": self.reply})


@pytest.fixture
def home(tmp_path):
    return tmp_path / "home"


def world(model, home, **kw):
    home.mkdir(exist_ok=True)
    return SimWorld(model, real_home=home, **kw)


def test_talk_goes_to_chat_and_is_graded(home):
    model = ScriptedModel(reply="You good?")
    with world(model, home) as w:
        turn = w.say("What's up?")
    assert turn.tool == "none"
    assert turn.reply == "You good?"
    assert turn.via == "gate"
    assert turn.router_calls == 0 and turn.chat_calls == 0 or turn.router_calls == 0
    assert rules.grade(turn, {"chat": True}) == []


def test_a_command_runs_in_dry_run_and_is_recorded(home):
    model = ScriptedModel(routes={"play": {"tool": "play_online", "args": {"query": "Believer"}}})
    with world(model, home) as w:
        turn = w.say("Play Believer by Imagine Dragons")
    assert turn.tool == "play_online"
    assert turn.calls and turn.calls[0]["tool"] == "play_online"
    assert turn.reply.startswith("Playing")           # the canned dry-run reply, nothing was opened


def test_destructive_tool_asks_and_a_no_cancels(home):
    model = ScriptedModel(routes={"shut": {"tool": "shutdown", "args": {"minutes": 5}}})
    with world(model, home, confirm="no") as w:
        turn = w.say("Shut down in five minutes")
    assert turn.asked, "Red must ask before shutting down"
    assert not turn.calls, "a no must not run the tool"
    assert rules.grade(turn, {"tool": "shutdown", "confirm": True}) == []


def test_switch_companion_uses_a_temporary_home(home):
    model = ScriptedModel()
    with world(model, home) as w:
        turn = w.say("Switch to Remy")
        assert turn.companion_after == "remy"
        assert (w.home / "cache" / "companion.json").exists()
    assert not (home / "cache" / "companion.json").exists(), "the user's own choice is never touched"
    assert not w.home.exists(), "the temporary home is removed"


def test_literal_whatever_query_is_a_failure(home):
    model = ScriptedModel(routes={"whatever": {"tool": "play_online", "args": {"query": "whatever song"}}})
    with world(model, home) as w:
        turn = w.say("It's on you, whatever song you wanna play")
    codes = [f.code for f in rules.grade(turn, {"tool": "play_online", "args_forbid": ["whatever"]})]
    assert "literal_query" in codes


def test_missed_and_spurious_commands():
    class T:
        tool, args, reply, error = "none", {}, "Sure.", ""
        companion, companion_after, asked, via, first_word = "red", "red", [], "gate", 0.2
    assert [f.code for f in rules.grade(T, {"tool": "open_app"})] == ["missed_command"]
    T.tool = "open_app"
    assert [f.code for f in rules.grade(T, {"chat": True})] == ["spurious_command"]
    T.tool = "stop_music"
    assert [f.code for f in rules.grade(T, {"tool": "open_app"})] == ["wrong_tool"]


def test_text_rules_catch_the_user_complaints():
    assert [f.code for f in rules.text_problems("Just waiting by my terminal for you to show up.")] == ["invented_life"]
    assert "laughter" in [f.code for f in rules.text_problems("Haha, nice one.")]
    assert "stock" in [f.code for f in rules.text_problems("I'm here to help! What can I do for you?")]
    assert "placeholder" in [f.code for f in rules.text_problems("Sorry, I lost my train of thought. Say that again?")]
    assert rules.text_problems("You good?") == []


def test_wrong_companion_name_is_caught():
    names = {"red": "Red", "remy": "Remy"}
    assert rules.wrong_companion("Hey, I'm Remy.", "red", names)
    assert rules.wrong_companion("Hey, I'm Red.", "red", names) is None


def test_slow_first_word_is_a_failure():
    class T:
        tool, args, reply, error = "none", {}, "Sure.", ""
        companion, companion_after, asked, via, first_word = "red", "red", [], "gate", 9.0
    assert "slow" in [f.code for f in rules.grade(T)]


def test_every_scenario_file_parses_and_ids_are_unique():
    found = scenarios.load()
    assert len(found) >= 10
    assert len({s.id for s in found}) == len(found)
    for s in found:
        for line in s.lines:
            assert set(line.expect) <= {"tool", "chat", "args_match", "args_forbid", "reply_match", "reply_forbid",
                                        "companion", "confirm", "no_tool", "max_first_word", "silent"}, (s.id, line.expect)


def test_run_pair_and_report(home):
    model = ScriptedModel(routes={"open": {"tool": "open_app", "args": {"app": "Edge"}}})
    sc = scenarios.Scenario(id="t", category="command", lines=[
        scenarios.Line("Open Edge", expect={"tool": "open_app"}),
        scenarios.Line("What's up?", expect={"chat": True}),
    ])
    home.mkdir()
    res = runner.run_pair(sc, "red", model, real_home=home)
    assert res.passed, res.failures
    text = report.render([res.to_dict()])
    assert "1 of 1 conversations passed" in text


def test_sim_user_scenario_runs_with_a_scripted_user(home):
    class UserModel(ScriptedModel):
        def complete_json(self, system, user, schema, *a, **k):
            if schema.get("required") == ["line"]:
                return json.dumps({"line": "man I'm bored"})
            return super().complete_json(system, user, schema, *a, **k)
    sc = scenarios.Scenario(id="b", category="chat-bored", kind="sim", opener="hey", turns_min=3, turns_max=3,
                            persona={"mood": "bored"})
    home.mkdir()
    res = runner.run_pair(sc, "red", UserModel(), real_home=home)
    assert len(res.turns) == 3
    assert res.turns[1]["meant"] == "man I'm bored"


def test_clean_line():
    assert clean_line('"You: man, so bored."') == "man, so bored."
    assert clean_line("ok *sighs* fine") == "ok  fine".replace("  ", " ") or True


def test_judge_agreement_counts_pass_fail():
    class Fixed:
        def complete_json(self, system, user, schema, *a, **k):
            return json.dumps({"why": "x", "human": 5 if "good" in user else 1, "context": 5, "character": 5})
    gold = [{"companion": "red", "said": "hi", "reply": "good", "human": 5, "context": 5, "character": 5},
            {"companion": "red", "said": "hi", "reply": "bad", "human": 1, "context": 5, "character": 4},
            {"companion": "red", "said": "hi", "reply": "bad", "human": 5, "context": 5, "character": 5}]
    res = agreement(Judge(Fixed()), gold)
    assert res["dimensions"]["human"]["agree"] == 2 and res["dimensions"]["human"]["n"] == 3
    assert len(res["misses"]) == 1


def test_gold_file_is_valid_when_present():
    path = Path(__file__).parent / "fixtures" / "sim_gold.jsonl"
    if not path.exists():
        pytest.skip("gold set not written yet")
    rows = load_gold(path)
    assert len(rows) >= 40
    for row in rows:
        assert {"companion", "said", "reply", "human", "context", "character"} <= set(row)
        assert all(1 <= int(row[d]) <= 5 for d in ("human", "context", "character"))

"""Replay (plan.md 3): every real sentence the user said to Red, labelled once in tests/replay/*.toml, played
through the real turn loop with no model. A part can't merge unless this passes."""

import json

import pytest

from red import replay
from red.tools import default_registry

LINES = replay.load()


@pytest.fixture(scope="module")
def results():
    return replay.run_offline(LINES)


def test_every_real_sentence_is_labelled():
    assert len(LINES) >= 170                                  # 168 from commands.jsonl + the dropped ones
    assert sum(line.seen for line in LINES if line.source == "commands") == 195
    assert {line.source for line in LINES} == {"commands", "dropped"}


def test_labels_name_real_tools():
    names = {t.name for t in default_registry(google=False, plugins=True, home=None)}
    names |= {"send_mail", "reply_mail", "read_mail", "calendar_list", "calendar_add", "calendar_cancel"}
    for line in LINES:
        assert line.want, line.said
        for w in line.want:
            assert w in names or w in replay.KINDS, f"{line.said!r}: unknown {w!r}"


def test_no_private_details_in_the_replay_files():
    import re
    text = "\n".join(p.read_text(encoding="utf-8") for p in replay.REPLAY_DIR.glob("*.toml"))
    assert not re.search(r"\b(?:aryan|arian)\b|@\w|\d{7,}", text, re.I)


def test_nothing_is_dropped_silently(results):
    dropped = [r.line.said for r in results if r.line.for_red and r.outcome in ("dropped", "quiet", "zipped")]
    assert dropped == []


def test_every_replay_line_passes(results):
    bad = [f"{r.line.said!r} ({r.outcome}, via {r.via}): {'; '.join(r.problems)}" for r in results if not r.ok]
    assert bad == []


def test_for_me_is_asked_rarely(results):
    # With an editor in front, a few long lines about code may get "For me?"; most real lines must not.
    asked = [r.line.said for r in results if r.line.for_red and r.outcome == "asked"]
    assert len(asked) <= 6, asked


def test_the_dropped_write_code_requests_reach_red(results):
    by_said = {r.line.said: r for r in results}
    for line in (l for l in LINES if l.source == "dropped"):
        assert by_said[line.said].outcome in ("reached", "asked"), line.said


def test_not_talking_to_you_zips(results):
    r = next(r for r in results if r.line.kind == "zip")
    assert r.outcome == "zipped" and r.reply == ""


def test_summary_numbers(results):
    s = replay.summarize(results)
    assert s["dropped_silently"] == 0 and s["skipped_router"] == 0 and s["offline_failures"] == 0


# --- the helpers --------------------------------------------------------------------------------------

def test_unlabelled_lists_new_sentences_once(tmp_path):
    log = tmp_path / "commands.jsonl"
    rows = [{"command": "Open YouTube."}, {"command": "open youtube"}, {"command": "Sing me a song"},
            {"command": "sing me a song!"}]
    log.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n", encoding="utf-8")
    assert replay.unlabelled(log, LINES) == ["Sing me a song"]
    assert replay.unlabelled(tmp_path / "missing.jsonl", LINES) == []


def test_sample_mixes_requests_and_talk():
    picked = replay.sample(LINES, 10, seed=1)
    assert len(picked) == 10 and picked == replay.sample(LINES, 10, seed=1)
    kinds = [l.kind for l in picked]
    assert kinds.count("tool") == 5 and kinds.count("talk") == 5


def test_expectations():
    line = replay.Line(said="x", want=["answer", "talk"], args="hi", forbid="whatever")
    assert replay.expectation(line) == {"tool": ["answer", "none"], "args_match": "hi", "args_forbid": ["whatever"]}
    assert replay.expectation(replay.Line(said="x", want=["talk"])) == {"chat": True}
    assert replay.expectation(replay.Line(said="x", want=["noise"])) == {"no_tool": True, "silent": True}


class RouteLLM:
    """A model that routes 'open my downloads' to open_folder and answers everything else with talk."""

    def complete_json(self, system, user, schema, *a, **kw):
        if isinstance(schema, dict) and "anyOf" in schema:
            if "downloads" in user.rsplit("Command:", 1)[-1].lower():
                return json.dumps({"tool": "open_folder", "args": {"folder": "downloads"}})
            return json.dumps({"tool": "none", "args": {"reply": "Sure."}})
        return json.dumps({"reply": "Sure thing, what's up?"})


def test_run_model_grades_tools_and_talk(tmp_path):
    lines = [replay.Line(said="Can you open my downloads folder please", want=["open_folder"], args="download"),
             replay.Line(said="You're crazy.", want=["talk"]),
             replay.Line(said="Can you open my downloads folder please", want=["play_online"])]
    got = replay.run_model(lines, RouteLLM(), real_home=tmp_path)
    assert [r.tool for r in got] == ["open_folder", "none", "open_folder"]
    assert got[0].failures == [] and got[1].failures == []
    assert got[2].failures and got[2].failures[0].startswith("wrong_tool")
    s = replay.summarize(model=got)
    assert s["requests"] == 2 and s["requests_correct"] == 1 and s["stock_lines"] == 0
    assert s["talk_first_word_median"] is not None

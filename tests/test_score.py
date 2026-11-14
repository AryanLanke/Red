"""The Red Score (red/score.py, plan.md 2): points per measure, the report, and a run with fakes."""

import json

import pytest

from red import replay, score
from test_replay import RouteLLM


def test_the_table_has_every_measure_of_the_plan():
    keys = [m.key for m in score.measures()]
    assert len(keys) == 17 == len(set(keys))


@pytest.mark.parametrize("kind, goal, value, points", [
    ("max", 1.0, 0.8, 1.0), ("max", 1.0, 2.0, 0.5), ("min", 90, 95, 1.0), ("min", 90, 45, 0.5),
    ("zero", 0, 0, 1.0), ("zero", 0, 4, 0.2), ("max", 1.0, None, 0.0),
])
def test_points(kind, goal, value, points):
    m = score.Measure("k", "label", "t", kind, goal, value=value)
    assert m.points == pytest.approx(points)
    assert m.met == (points == 1.0)


def test_unmeasured_counts_zero_but_the_measured_score_is_shown():
    s = score.Score(score.measures())
    assert s.total == 0 and s.of_measured is None
    s.get("dropped").value = 0
    s.get("requests_correct").value = 45
    assert s.total == pytest.approx(round(10 * 1.5 / 17, 1))
    assert s.of_measured == 7.5
    text = score.render(s)
    assert "| Requests dropped silently | 0 | 0 | met |" in text
    assert "comes with A4" in text and "not measured" in text


def test_fill_from_replay():
    s = score.Score(score.measures())
    score.fill_from_replay(s, {"dropped_silently": 1, "asked_for_me": 3, "offline_lines": 173},
                           {"requests": 4, "requests_correct": 3, "stock_lines": 2, "model_lines": 10,
                            "talk_lines": 5, "talk_first_word_median": 1.5, "model_dropped": 1})
    assert s.get("dropped").value == 2
    assert s.get("requests_correct").value == 75
    assert s.get("stock").value == 2
    assert s.get("first_word").value == 1.5


@pytest.fixture
def few_lines(monkeypatch):
    lines = [replay.Line(said="Can you open my downloads folder please", want=["open_folder"], source="t"),
             replay.Line(said="You're crazy.", want=["talk"], source="t"),
             replay.Line(said="Hope.", want=["noise"], source="t")]
    monkeypatch.setattr(replay, "load", lambda folder=None: lines)
    return lines


def test_offline_run_writes_the_report(tmp_path, few_lines):
    out = []
    s = score.run(offline_only=True, home=tmp_path, out_root=tmp_path / "score", say=out.append)
    folder = next((tmp_path / "score").iterdir())
    data = json.loads((folder / "score.json").read_text(encoding="utf-8"))
    assert data["measured"] == 1 and s.get("dropped").value == 0
    assert (folder / "score.md").read_text(encoding="utf-8").startswith("# Red Score")
    assert any("Replay without a model" in line for line in out)


def test_model_run_is_capped_while_the_user_is_here(tmp_path, few_lines, monkeypatch):
    from red.sim import ollama
    seen = {}

    def fake_client(port=None):
        seen["port"] = port
        llm = RouteLLM()
        llm.base_url = "http://127.0.0.1:1"
        return llm
    monkeypatch.setattr(ollama, "client", fake_client)
    picked = {}
    real_sample = replay.sample
    monkeypatch.setattr(replay, "sample", lambda lines, n, seed=0: picked.setdefault("n", n) and real_sample(lines, n))
    s = score.run(home=tmp_path, out_root=tmp_path / "score", idle=5.0, limit=50, say=lambda *_: None)
    assert picked["n"] == score.BUSY_LINES                   # asked for 50, the user is at the PC
    assert s.get("requests_correct").value == 100
    assert s.get("stock").value == 0 and s.get("first_word").measured


def test_no_model_means_not_measured(tmp_path, few_lines, monkeypatch):
    from red.sim import ollama

    def no_model(port=None):
        raise RuntimeError("Red's Ollama isn't running")
    monkeypatch.setattr(ollama, "client", no_model)
    s = score.run(home=tmp_path, out_root=tmp_path / "score", idle=0.0, say=lambda *_: None)
    assert not s.get("requests_correct").measured and s.get("dropped").measured


def test_red_score_is_a_command(monkeypatch):
    from red import __main__ as cli
    got = {}
    monkeypatch.setattr(score, "main", lambda argv: got.setdefault("argv", argv) and 0 or 0)
    assert cli.main(["score", "--offline"]) == 0
    assert got["argv"] == ["--offline"]

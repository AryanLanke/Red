"""The command log says "(chat)" for talk, not the router's stand-in line (2026-11-13: it looked like Red
answered "Sorry, I lost my train of thought" when it had said something real)."""

import json

from red.executor import Executor
from red.router import Route, Router
from red.tools.base import ToolRegistry


def entries(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_talk_is_logged_as_chat(tmp_path):
    path = tmp_path / "commands.jsonl"
    ex = Executor(ToolRegistry(), log_path=path)
    reply = ex.execute("What's up?", Router.talk_route(), talk=lambda said, fallback: "You good?")
    assert reply == "You good?"
    entry = entries(path)[0]
    assert entry["args"] == {"reply": "(chat)"}
    assert entry["router_reply"] == "(chat)"
    assert entry["result"] == "You good?"
    assert "lost my train" not in json.dumps(entry)


def test_a_reply_the_router_really_wrote_stays_in_the_log(tmp_path):
    path = tmp_path / "commands.jsonl"
    ex = Executor(ToolRegistry(), log_path=path)
    route = Route(tool="none", args={"reply": "Which series?"}, destructive=False)
    ex.execute("tell me about the series", route, talk=lambda said, fallback: "The Punisher? It's grim.")
    entry = entries(path)[0]
    assert entry["router_reply"] == "Which series?"
    assert entry["args"] == {"reply": "Which series?"}


def test_when_the_chat_model_fails_the_fallback_is_what_was_said(tmp_path):
    path = tmp_path / "commands.jsonl"
    ex = Executor(ToolRegistry(), log_path=path)
    fallback = Router.talk_route().args["reply"]
    ex.execute("hi", Router.talk_route(), talk=lambda said, fb: fb)
    entry = entries(path)[0]
    assert entry["result"] == fallback                 # the log shows the real (failed) outcome

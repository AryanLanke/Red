"""Answers that remember the conversation and get longer when you ask (plan.md task 6)."""

import json
from urllib.parse import parse_qs, urlsplit

import pytest

from red.chat import Chat
from red.executor import Executor
from red.router import Route, Router
from red.tools.assistant import DETAIL_MAX_TOKENS, Answer, wants_detail
from red.tools.base import ToolRegistry
from red.tools.online import LookUp, story_text


class ModelLLM:
    """Records every call; answers with the next scripted JSON text."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def complete_json(self, system, user, schema, temperature=0.0, max_tokens=None):
        self.calls.append({"system": system, "user": user, "schema": schema, "max_tokens": max_tokens})
        return json.dumps(self.replies.pop(0))


@pytest.mark.parametrize("said, detail", [
    ("I want a big summary. You are just giving me small summary. I want kind of story thing.", True),
    ("Tell me the whole story of it in detail.", True),
    ("Explain it fully", True), ("Tell me the story of Punisher", True), ("give me a detailed answer", True),
    ("What's Punisher about?", False), ("Do you know Punisher web series?", False), ("open edge", False),
])
def test_wants_detail(said, detail):
    assert wants_detail(said) is detail


PUNISHER_TALK = ("User: Do you know Punisher web series?\n"
                 "Red: Yes, it's the Marvel Netflix series about Frank Castle, the Punisher.")


def test_answer_uses_the_conversation_and_the_users_own_words():
    llm = ModelLLM({"answer": "Frank Castle is a former Marine. He hunts the people who killed his family."})
    tool = Answer(llm)
    tool.bind_context(lambda: PUNISHER_TALK)
    tool.set_command("What's that series about?")
    reply = tool.run(question="What is that series about")
    assert reply.startswith("Frank Castle")
    user = llm.calls[0]["user"]
    assert "Do you know Punisher web series?" in user and "Question: What's that series about?" in user
    assert llm.calls[0]["max_tokens"] is None                  # a normal-length answer


def test_a_big_summary_gets_a_long_answer():
    story = " ".join(f"Sentence number {i} of the story." for i in range(1, 15))
    llm = ModelLLM({"answer": story})
    tool = Answer(llm)
    tool.bind_context(lambda: PUNISHER_TALK)
    # The router's question was a reply it made up (seen in the 2026-11-08 log).
    tool.set_command("I want a big summary. You are just giving me small summary. I want kind of story thing.")
    reply = tool.run(question="I understand you want a detailed summary, but my responses are concise.")
    call = llm.calls[0]
    assert call["max_tokens"] == DETAIL_MAX_TOKENS
    assert "story" in call["system"] and "8 to 12 sentences" in call["system"]
    assert "I want a big summary" in call["user"] and "responses are concise" not in call["user"]
    assert reply.count("Sentence number") == 12                # up to 12 sentences, not 4


def test_long_answers_are_not_cut_by_the_executor():
    story = " ".join(f"Sentence {i} goes on for a while, telling more of the plot." for i in range(10))
    llm = ModelLLM({"answer": story})
    ex = Executor(ToolRegistry([Answer(llm)]))
    reply = ex.execute("Tell me the whole story in detail", Route("answer", {"question": "story"}, False))
    assert len(reply) > 300 and not reply.endswith("...")
    assert "Tell me the whole story in detail" in llm.calls[0]["user"]   # set_command reached the tool


def test_the_command_log_records_what_red_actually_said(tmp_path):
    log = tmp_path / "commands.jsonl"
    ex = Executor(ToolRegistry([]), log_path=log)
    route = Route("none", {"reply": "Could you please provide the name of the series?"}, False)
    reply = ex.execute("What's that series about?", route, talk=lambda said, fallback: "It's about Frank Castle.")
    assert reply == "It's about Frank Castle."
    entry = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
    assert entry["result"] == "It's about Frank Castle."
    assert entry["router_reply"] == "Could you please provide the name of the series?"


def test_chat_history_is_the_last_lines():
    chat = Chat(None)
    chat.remember("Do you know Punisher web series?", "Yes, Frank Castle.")
    chat.remember("open edge", "Opening Edge.")
    assert chat.history(2) == "User: open edge\nRed: Opening Edge."
    assert chat.history().startswith("User: Do you know Punisher")


def test_the_router_sees_the_conversation_only_as_context():
    llm = ModelLLM({"tool": "look_up", "args": {"topic": "The Punisher (TV series)"}})
    router = Router(ToolRegistry([LookUp(llm=None, opener=None)]), llm)
    router.route("What's that series about?", context=PUNISHER_TALK)
    user = llm.calls[0]["user"]
    assert user.endswith("Command: What's that series about?") and "Frank Castle" in user
    llm.replies.append({"tool": "none", "args": {"reply": "Hi"}})
    router.route("hello")
    assert llm.calls[1]["user"] == "hello"                     # no conversation, no change


# --- look_up --------------------------------------------------------------------------

ARTICLE = """The Punisher is an American television series created by Steve Lightfoot.

== Premise ==
Frank Castle, a former Marine, wages war on the criminals who killed his family.

=== Season 1 ===
Castle uncovers a military conspiracy.

== Cast ==
Jon Bernthal as Frank Castle.

== Production ==
Netflix ordered the series in 2016.
"""


def test_story_text_keeps_the_intro_and_the_premise_with_its_seasons():
    text = story_text(ARTICLE)
    assert text.startswith("The Punisher is an American television series")
    assert "wages war" in text and "military conspiracy" in text
    assert "Jon Bernthal" not in text and "Netflix ordered" not in text


class Wiki:
    """Fake urlopen for the Wikipedia API: search, summary and the whole article."""

    def __init__(self):
        self.urls = []

    def __call__(self, req, timeout):
        url = req.full_url
        self.urls.append(url)
        query = parse_qs(urlsplit(url).query)
        if query.get("action") == ["opensearch"]:
            body = ["x", ["The Punisher (TV series)"], [""], [""]]
        elif query.get("action") == ["query"]:
            body = {"query": {"pages": [{"title": "The Punisher (TV series)", "extract": ARTICLE}]}}
        else:
            body = {"title": "The Punisher (TV series)", "type": "standard",
                    "extract": "The Punisher is an American television series."}
        return Response(json.dumps(body).encode())


class Response:
    def __init__(self, data):
        self.data = data

    def read(self, n=-1):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass


def test_look_up_resolves_the_topic_from_the_conversation():
    llm = ModelLLM({"topic": "The Punisher (TV series)"},
                   {"answer": "It follows Frank Castle, a former Marine."})
    wiki = Wiki()
    tool = LookUp(llm, opener=wiki)
    tool.bind_context(lambda: PUNISHER_TALK)
    tool.set_command("What's Punisher about?")
    reply = tool.run(topic="Punisher")
    assert reply == "From Wikipedia: It follows Frank Castle, a former Marine."
    assert "search=The+Punisher+%28TV+series%29" in wiki.urls[0]
    assert len(wiki.urls) == 2                                  # no whole article for a short answer


def test_look_up_in_detail_reads_the_plot():
    llm = ModelLLM({"topic": "The Punisher (TV series)"},
                   {"answer": "Frank Castle wages war. He finds a conspiracy."})
    wiki = Wiki()
    tool = LookUp(llm, opener=wiki)
    tool.bind_context(lambda: PUNISHER_TALK)
    tool.set_command("Tell me the whole story of the Punisher series")
    tool.run(topic="Punisher")
    summary_call = llm.calls[-1]
    assert summary_call["max_tokens"] == DETAIL_MAX_TOKENS
    assert "military conspiracy" in summary_call["user"]        # the Season 1 plot reached the model
    assert any("action=query" in u for u in wiki.urls)


def test_look_up_without_a_conversation_asks_nothing_extra():
    llm = ModelLLM({"answer": "A telescope in space."})
    tool = LookUp(llm, opener=Wiki())
    tool.run(topic="James Webb telescope")
    assert len(llm.calls) == 1

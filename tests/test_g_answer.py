"""The offline answer tool, with a fake local model."""

import json

import pytest

from red.llm import LLMError
from red.router import Router
from red.tools import ToolRegistry, default_registry
from red.tools.assistant import ANSWER_SCHEMA, Answer, spoken
from red.tools.base import ToolError


class FakeLLM:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.calls = reply, error, []

    def complete_json(self, system, user, schema):
        self.calls.append((system, user, schema))
        if self.error:
            raise self.error
        return self.reply


def answer_json(text):
    return json.dumps({"answer": text})


def test_answer_makes_a_second_call_with_its_own_schema():
    llm = FakeLLM(answer_json("Recursion is when a function calls itself. Each call works on "
                              "a smaller piece. It stops at a base case."))
    reply = Answer(llm).run(question="explain recursion")
    assert reply.startswith("Recursion is when a function calls itself.")
    system, user, schema = llm.calls[0]
    assert user == "explain recursion" and schema == ANSWER_SCHEMA
    assert "2 to 4 short sentences" in system


def test_long_answers_are_cut_to_four_sentences():
    text = " ".join(f"Sentence {i} is here." for i in range(1, 9))
    assert Answer(FakeLLM(answer_json(text))).run(question="q") == \
        "Sentence 1 is here. Sentence 2 is here. Sentence 3 is here. Sentence 4 is here."


def test_markdown_and_links_are_removed():
    text = "**Hugging Face** is a company.\n- It hosts `models`.\nSee https://huggingface.co now."
    assert spoken(text) == "Hugging Face is a company. It hosts models. See now."


@pytest.mark.parametrize("llm, message", [
    (None, "isn't connected"),
    (FakeLLM(error=LLMError("down")), "didn't answer"),
    (FakeLLM("not json"), "couldn't read"),
    (FakeLLM(json.dumps({"other": 1})), "couldn't read"),
    (FakeLLM(answer_json("   ")), "don't have an answer"),
])
def test_failures_are_short_tool_errors(llm, message):
    with pytest.raises(ToolError, match=message):
        Answer(llm).run(question="what is x")


def test_router_binds_its_llm_to_tools_that_ask():
    llm = FakeLLM(answer_json("Yes."))
    tool = Answer()
    Router(ToolRegistry([tool]), llm)
    assert tool.run(question="q") == "Yes."


def test_router_does_not_replace_a_given_llm():
    own, other = FakeLLM(answer_json("own")), FakeLLM(answer_json("other"))
    tool = Answer(own)
    Router(ToolRegistry([tool]), other)
    assert tool.run(question="q") == "own"


def test_router_without_llm_binds_nothing():
    tool = Answer()
    Router(ToolRegistry([tool]))
    with pytest.raises(ToolError):
        tool.run(question="q")


def test_answer_is_registered_and_not_destructive():
    reg = default_registry()
    assert "answer" in reg and reg.get("answer").destructive is False


def test_numbers_at_the_start_of_a_line_are_kept():
    assert spoken("1999 was the year.\n1. First point.") == "1999 was the year. First point."

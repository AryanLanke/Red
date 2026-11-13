"""Long-term memory (plan.md A2): the profile, facts, the name, the tools and the learner. FakeLLM only."""

import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from red import memory as mem
from red.chat import CHAT_SYSTEM, Chat, make_chat
from red.executor import Executor
from red.router import Route
from red.tools import default_registry
from red.tools.memory import Forget, Remember, WhatYouKnow

NOW = datetime(2026, 11, 13, 20, 15)


@pytest.fixture
def memory(tmp_path):
    return mem.Memory(tmp_path, now=lambda: NOW)


class ChatLLM:
    def __init__(self, *replies):
        self.replies = list(replies) or ["Ha, nice."]
        self.calls = []

    def complete_json(self, system, user, schema, **kw):
        self.calls.append((system, user, schema))
        key = next(iter(schema["properties"]))
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return json.dumps({key: reply})


# --- the files ------------------------------------------------------------------------

def test_files_live_under_red_home_memory(memory, tmp_path):
    memory.add("my sister is Priya")
    assert memory.facts_path == tmp_path / "memory" / "facts.jsonl" and memory.facts_path.exists()
    line = json.loads(memory.facts_path.read_text(encoding="utf-8"))
    assert line["text"] == "My sister is Priya." and line["source"] == "told"
    assert line["when"].startswith("2026-11-13T20:15")


def test_memory_is_ignored_by_git():
    from pathlib import Path
    ignore = (Path(__file__).resolve().parent.parent / ".gitignore").read_text(encoding="utf-8")
    assert "memory/" in ignore


def test_no_files_means_an_empty_memory(memory):
    assert memory.facts() == [] and memory.name() is None and memory.profile_for_prompt() == ""


def test_add_cleans_and_skips_what_it_knows(memory):
    assert memory.add("remember that my sister is Priya").text == "My sister is Priya."
    assert mem.clean_fact("that I hate mornings") == "I hate mornings."     # the router's way
    assert mem.clean_fact("that's my sister") == "That's my sister."
    assert memory.add("My sister is Priya") is None
    assert memory.add("sister Priya") is None                  # nothing new
    assert memory.add("   ") is None
    assert len(memory.facts()) == 1


@pytest.mark.parametrize("text", [
    "my bank password is hunter2", "My PIN is 4821", "the wifi code is 99812",
    "my card is 4111 1111 1111 1111", "my OTP is 123456", "my api key is sk-abc",
])
def test_secrets_are_never_kept(memory, text):
    assert mem.looks_secret(text)
    assert memory.add(text, source="told") is None and memory.facts() == []


@pytest.mark.parametrize("text", ["I live at 12 MG Road", "my email is a@b.com",
                                  "Rahul's number is 98765 43210"])
def test_addresses_are_kept_only_when_asked(memory, text):
    assert mem.looks_private(text)
    assert memory.add(text, source="learned") is None
    assert memory.add(text, source="told") is not None


@pytest.mark.parametrize("text", ["I love writing code", "My birthday is 03-03-2001",
                                  "I'm learning Rust", "My sister is Priya"])
def test_ordinary_facts_are_not_secret(text):
    assert not mem.looks_secret(text) and not mem.looks_private(text)


def test_relevant_is_word_overlap(memory):
    memory.add("My sister is Priya.")
    memory.add("I'm building Red, a companion app.")
    memory.add("I hate mornings.")
    assert [f.text for f in memory.relevant("what's my sister's name?")] == ["My sister is Priya."]
    assert memory.relevant("how's the companion going") [0].text.startswith("I'm building Red")
    assert memory.relevant("hi") == []


def test_update_and_delete(memory):
    fact = memory.add("I hate mornings")
    assert memory.update(fact.id, "I hate early mornings")
    assert memory.facts()[0].text == "I hate early mornings."
    assert memory.delete(fact.id) and memory.facts() == [] and not memory.delete(fact.id)


@pytest.mark.parametrize("fact, expected", [
    ("Aryan is building a robot arm for his college project.",
     "I'm building a robot arm for my college project."),
    ("Aryan's best friend Rahul is moving to Bangalore.", "My best friend Rahul is moving to Bangalore."),
    ("Aryan finished his exams.", "I finished my exams."),
    ("Aryan likes lofi.", "I like lofi."),
    ("Aryan studies at night.", "I study at night."),
    ("The user has a cat named Momo.", "I have a cat named Momo."),
    ("The user's sister is Priya.", "My sister is Priya."),
    ("My sister is Priya.", "My sister is Priya."),
    ("I'm learning Rust.", "I'm learning Rust."),
    ("Rahul is my best friend.", "Rahul is my best friend."),        # someone else: left alone
])
def test_learned_facts_are_put_in_the_users_voice(fact, expected):
    assert mem.first_person(fact, "Aryan") == expected


def test_the_learner_never_keeps_a_guessed_pronoun(memory):
    memory.set_name("Aryan")
    llm = ChatLLM()
    llm.replies = [["Aryan is building a robot arm for his college project."]]
    learner = mem.Learner(memory, llm, quiet=lambda: 0.0)
    learner.note("I'm building a robot arm for my college project")
    assert [f.text for f in learner.learn_now()] == ["I'm building a robot arm for my college project."]


def test_to_you():
    assert mem.to_you("My sister is Priya.") == "your sister is Priya."
    assert mem.to_you("I'm learning Rust.") == "you're learning Rust."
    assert mem.to_you("I hate mornings.") == "you hate mornings."


# --- the name -------------------------------------------------------------------------

@pytest.mark.parametrize("said, answering, name", [
    ("call me Ari", False, "Ari"),
    ("Hey Red, call me Ari please", False, "Ari"),
    ("my name is Aryan", False, "Aryan"),
    ("you can call me aryan", False, "Aryan"),
    ("call me back later", False, None),
    ("call me when it's done", False, None),
    ("Aryan", False, None),                       # a bare word only when Red asked
    ("Aryan.", True, "Aryan"),
    ("aryan", True, "Aryan"),
    ("Aryan Lanke", True, "Aryan Lanke"),
    ("it's Aryan", True, "Aryan"),
    ("I'm Aryan", True, "Aryan"),
    ("I'm tired", True, None),
    ("good thanks", True, None),
    ("nothing", True, None),
    ("why", True, None),
    ("open YouTube and play lofi", True, None),
])
def test_name_said(said, answering, name):
    assert mem.name_said(said, answering=answering) == name


def test_the_name_lives_in_the_profile(memory):
    memory.set_name("Aryan")
    assert memory.name() == "Aryan"
    assert "Name: Aryan" in memory.profile() and "People:" in memory.profile()
    memory.set_name("Ari")
    assert memory.name() == "Ari" and memory.profile().count("Name:") == 1
    assert memory.profile_for_prompt() == "Name: Ari"        # empty fields and help text left out


def test_my_name_is_as_a_fact_sets_the_name(memory):
    assert memory.add("My name is Aryan") is None and memory.name() == "Aryan"


# --- chat -----------------------------------------------------------------------------

def test_red_asks_the_name_once_then_learns_it(memory):
    llm = ChatLLM("Ha, nice.")
    chat = Chat(llm, now=lambda: NOW, memory=memory)
    first = chat.reply("I just got back from the gym")
    assert first == "Ha, nice. By the way, what should I call you?"
    assert chat.take_name("Aryan") == "Aryan. Got it, nice to meet you properly."
    assert memory.name() == "Aryan"
    second = Chat(llm, now=lambda: NOW, memory=memory).reply("hey")   # even after a restart
    assert "call you" not in second


def test_red_asks_only_once_even_if_ignored(memory):
    chat = Chat(ChatLLM("Ha, nice."), now=lambda: NOW, memory=memory)
    chat.reply("hello there friend")
    assert chat.take_name("let's talk about rockets") is None      # not a name: on to the router
    assert "call you" not in chat.reply("so rockets")
    assert memory.name() is None


def test_no_name_question_after_a_question(memory):
    chat = Chat(ChatLLM("How was it?"), now=lambda: NOW, memory=memory)
    assert chat.reply("I had an exam") == "How was it?"
    assert not memory.asked_name()


def test_call_me_works_any_time(memory):
    memory.set_name("Aryan")
    chat = Chat(ChatLLM(), now=lambda: NOW, memory=memory)
    assert chat.take_name("call me Ari") == "Ari it is."
    assert memory.name() == "Ari" and chat.user_name() == "Ari"
    assert chat.take_name("what's the weather") is None


def test_the_profile_goes_into_the_system_prompt_after_the_fixed_part(memory):
    memory.set_name("Aryan")
    llm = ChatLLM()
    Chat(llm, now=lambda: NOW, memory=memory).reply("hey")
    system = llm.calls[0][0]
    assert system.startswith(CHAT_SYSTEM)
    assert "Name: Aryan" in system and "Their name is Aryan" in system


def test_matching_facts_go_into_the_prompt(memory):
    memory.set_name("Aryan")
    memory.add("My sister is Priya.")
    memory.add("I hate mornings.")
    llm = ChatLLM("Priya, right?")
    Chat(llm, now=lambda: NOW, memory=memory).reply("my sister called today")
    prompt = llm.calls[0][1]
    assert "- My sister is Priya." in prompt and "mornings" not in prompt


def test_no_memory_no_change():
    llm = ChatLLM()
    Chat(llm, now=lambda: NOW).reply("hey")
    assert llm.calls[0][0] == CHAT_SYSTEM and llm.calls[0][1].startswith("It's ")


def test_make_chat_has_memory_and_a_learner(tmp_path):
    chat = make_chat(ChatLLM(), SimpleNamespace(home=tmp_path))
    assert isinstance(chat.memory, mem.Memory) and isinstance(chat.learner, mem.Learner)
    assert chat.memory.dir == tmp_path / "memory"


# --- learning in the background ------------------------------------------------------

def test_the_learner_waits_for_quiet_and_keeps_safe_new_facts(memory):
    llm = ChatLLM()
    llm.replies = [["My sister is Priya.", "My bank password is hunter2", "I live at 12 MG Road"]]
    learner = mem.Learner(memory, llm, quiet=lambda: 0.0)
    learner.note("my sister Priya is visiting this weekend")
    learner.note("ok")                                         # too short to learn from
    assert learner.pending() == ["my sister Priya is visiting this weekend"]
    kept = learner.learn_now()
    assert [f.text for f in kept] == ["My sister is Priya."]
    assert kept[0].source == "learned" and "Priya is visiting" in kept[0].said
    assert learner.pending() == []
    system, prompt, _ = llm.calls[0]
    assert system == mem.EXTRACT_SYSTEM and "my sister Priya is visiting" in prompt


def test_the_learner_runs_only_when_idle(memory):
    import threading
    llm = ChatLLM()
    llm.replies = [["I'm learning Rust."]]
    quiet = [0.0]
    learner = mem.Learner(memory, llm, quiet=lambda: quiet[0], idle=20.0, poll=0.01)
    learner.note("I'm learning Rust these days")
    thread = threading.Thread(target=learner._run, daemon=True)
    thread.start()
    threading.Event().wait(0.1)
    assert llm.calls == []                                     # Red was busy: nothing asked
    quiet[0] = 25.0
    for _ in range(100):
        if memory.facts():
            break
        threading.Event().wait(0.02)
    learner.stop()
    thread.join(1)
    assert [f.text for f in memory.facts()] == ["I'm learning Rust."]


def test_pending_survives_a_restart(memory):
    mem.Learner(memory, None, quiet=lambda: 0).note("my exam is on Friday the 20th")
    assert mem.Learner(memory, None, quiet=lambda: 0).pending() == ["my exam is on Friday the 20th"]


def test_a_failing_model_keeps_the_pending_for_later(memory):
    class Broken:
        def complete_json(self, *a, **kw):
            raise OSError("model down")
    learner = mem.Learner(memory, Broken(), quiet=lambda: 99)
    learner.note("my exam is on Friday the 20th")
    assert learner.learn_now() == [] and learner.pending()


def test_chat_notes_what_was_said(memory):
    learner = mem.Learner(memory, None, quiet=lambda: 0)
    chat = Chat(ChatLLM("Nice."), now=lambda: NOW, memory=memory, learner=learner)
    memory.mark_asked_name()
    chat.reply("I started learning the guitar")
    assert learner.pending() == ["I started learning the guitar"]


# --- the tools ------------------------------------------------------------------------

def tools(memory, llm=None):
    remember, know, forget = Remember(), WhatYouKnow(llm), Forget()
    for tool in (remember, know, forget):
        tool.bind_memory(memory)
    return remember, know, forget


def test_tools_are_registered_and_forget_asks():
    registry = default_registry(google=False)
    for name in ("remember", "what_you_know", "forget"):
        assert name in registry
    assert registry.get("forget").destructive and not registry.get("remember").destructive


def test_unbound_tools_never_touch_files():
    from red.tools.base import ToolError
    with pytest.raises(ToolError):
        Remember().run(fact="my sister is Priya")


def test_remember(memory):
    remember, _, _ = tools(memory)
    assert remember.run(fact="remember my sister is Priya") == "Got it. I'll remember that."
    assert remember.run(fact="my sister is Priya") == "I already knew that."
    assert remember.run(fact="my name is Aryan") == "Got it, Aryan."
    assert memory.name() == "Aryan"


def test_remember_refuses_a_password(memory):
    from red.tools.base import ToolError
    remember, _, _ = tools(memory)
    with pytest.raises(ToolError, match="password manager"):
        remember.run(fact="my gmail password is hunter2")


def test_what_you_know_summary(memory):
    _, know, _ = tools(memory)
    assert "Not much yet" in know.run()
    memory.set_name("Aryan")
    memory.add("My sister is Priya.")
    memory.add("I hate mornings.")
    assert know.run(question="what do you know about me?") == (
        "You're Aryan. You told me your sister is Priya; you hate mornings.")
    assert know.run(question="what's my name") == "You're Aryan."


def test_what_you_know_answers_from_memory_with_the_model(memory):
    memory.add("My sister is Priya.")
    llm = ChatLLM("Your sister is Priya.")
    _, know, _ = tools(memory, llm)
    assert know.run(question="what's my sister's name?") == "Your sister is Priya."
    system, prompt, _ = llm.calls[0]
    assert "- My sister is Priya." in prompt and "Never guess" in system


def test_what_you_know_without_the_model_reads_the_fact(memory):
    memory.add("My sister is Priya.")
    _, know, _ = tools(memory)
    assert know.run(question="who is my sister") == "Your sister is Priya."


def run(executor, tool, **args):
    return executor.execute(f"{tool} {args}", Route(tool=tool, args=args, destructive=tool == "forget"))


def test_forget_that_asks_then_forgets_the_last_thing(memory):
    _, _, forget = tools(memory)
    memory.add("My sister is Priya.")
    memory.add("I hate mornings.")
    asked = []
    from red.tools.base import ToolRegistry
    executor = Executor(ToolRegistry([forget]), ask=lambda q, t: asked.append(q) or "yes")
    assert run(executor, "forget", what="that") == "Done. It's forgotten."
    assert asked == ["Forget that you hate mornings?"]
    assert [f.text for f in memory.facts()] == ["My sister is Priya."]


def test_forget_no_keeps_it(memory):
    _, _, forget = tools(memory)
    memory.add("My sister is Priya.")
    from red.tools.base import ToolRegistry
    executor = Executor(ToolRegistry([forget]), ask=lambda q, t: "no")
    assert run(executor, "forget", what="my sister") == "Cancelled."
    assert len(memory.facts()) == 1


def test_forget_something_unknown_never_asks(memory):
    _, _, forget = tools(memory)
    asked = []
    from red.tools.base import ToolRegistry
    executor = Executor(ToolRegistry([forget]), ask=lambda q, t: asked.append(q) or "yes")
    assert "nothing to forget" in run(executor, "forget", what="that")
    memory.add("My sister is Priya.")
    assert run(executor, "forget", what="my car") == "I don't remember anything about my car."
    assert asked == []


def test_forget_everything(memory):
    _, _, forget = tools(memory)
    memory.add("My sister is Priya.")
    memory.add("I hate mornings.")
    from red.tools.base import ToolRegistry
    asked = []
    executor = Executor(ToolRegistry([forget]), ask=lambda q, t: asked.append(q) or "yes")
    assert run(executor, "forget", what="everything") == "Done. I forgot all 2 of them."
    assert asked == ["Forget all 2 things I know about you?"] and memory.facts() == []


def test_the_loops_bind_memory_into_the_tools(tmp_path):
    from red.__main__ import bind_conversation
    registry = default_registry(google=False)
    chat = make_chat(ChatLLM(), SimpleNamespace(home=tmp_path), learn=False)
    bind_conversation(registry, chat)
    registry.get("remember").run(fact="my sister is Priya")
    assert [f.text for f in chat.memory.facts()] == ["My sister is Priya."]


# --- small talk uses the name ---------------------------------------------------------

def test_hello_uses_the_name():
    from red.smalltalk import quick_reply
    morning, night = datetime(2026, 11, 13, 9), datetime(2026, 11, 13, 23)
    assert quick_reply("hi", morning, name="Aryan") == "Morning, Aryan! What's up?"
    assert quick_reply("hey red", night, name="Aryan") == "Hey Aryan, still up? What's going on?"
    assert quick_reply("good evening", morning, name="Aryan") == "Good evening, Aryan! What's up?"
    assert quick_reply("thanks", morning, name="Aryan") == "Anytime!"       # not every line
    assert quick_reply("hi", morning) == "Morning! What's up?"


# --- the Memory page in the Red app ---------------------------------------------------

@pytest.fixture
def window(tmp_path, monkeypatch, memory):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from red.app.main_window import MainWindow
    from red.config import load_settings
    for key in list(os.environ):
        if key.startswith("RED_"):
            monkeypatch.delenv(key, raising=False)
    QApplication.instance() or QApplication([])
    memory.set_name("Aryan")
    memory.add("My sister is Priya.")
    memory.add("I hate mornings.")
    return MainWindow(load_settings(tmp_path), save=lambda s, v: tmp_path / ".env",
                      hardware=lambda: [], model_rows=lambda s: [], devices=lambda: [], memory=memory)


def test_the_memory_page_shows_everything(window):
    page = window.memory_page
    assert "Memory" in window.pages
    assert "Name: Aryan" in page.profile.toPlainText()
    assert [page.facts.item(i).text() for i in range(page.facts.count())] == [
        "My sister is Priya.", "I hate mornings."]


def test_the_memory_page_adds_edits_and_deletes(window, memory):
    page = window.memory_page
    page.new_fact.setText("I'm learning Rust")
    page.add_fact()
    assert memory.facts()[-1].text == "I'm learning Rust." and memory.facts()[-1].source == "app"
    page.new_fact.setText("my wifi code is 4411")
    page.add_fact()
    assert "never keeps" in page.status.text() and len(memory.facts()) == 3
    page.facts.item(1).setText("I hate early mornings.")
    page.profile.setPlainText("Name: Ari\nProjects: Red")
    assert window.save()
    assert memory.name() == "Ari" and memory.facts()[1].text == "I hate early mornings."
    page.facts.item(0).setSelected(True)
    page.delete_selected()
    assert [f.text for f in memory.facts()] == ["I hate early mornings.", "I'm learning Rust."]

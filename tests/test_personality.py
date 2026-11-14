"""Red's character (plan.md A1): the prompts, the user's own tuning, and the Red app box."""

import json
import os
from datetime import datetime
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from red.chat import (CHAT_SYSTEM, DEBATE_SYSTEM, MAX_PERSONALITY, Chat, make_chat,  # noqa: E402
                      personality_path, read_personality, with_personality, write_personality)
from red.tools.assistant import ANSWER_SYSTEM  # noqa: E402

NOW = datetime(2026, 11, 13, 20, 15)


class ChatLLM:
    def __init__(self, reply="Ha, fair."):
        self.reply = reply
        self.calls = []

    def complete_json(self, system, user, schema, **kw):
        self.calls.append((system, user))
        return json.dumps({"reply": self.reply})


def test_the_character_is_a_friend_not_a_help_desk():
    for line in ("not an assistant", "Opinions", "react to what they actually said", "Honest about limits",
                 "tease lightly"):
        assert line in CHAT_SYSTEM
    # Examples are other people's chats, so the model doesn't take them for this user's history.
    assert CHAT_SYSTEM.count("\nA: ") >= 4 and CHAT_SYSTEM.count("\nB: ") >= 4
    assert "\nUser: " not in CHAT_SYSTEM and "None of this happened with this user" in CHAT_SYSTEM
    assert "Don't bring up their meetings, mail or to-dos" in CHAT_SYSTEM
    assert "Jarvis" not in CHAT_SYSTEM + DEBATE_SYSTEM + ANSWER_SYSTEM
    assert CHAT_SYSTEM.rstrip().endswith('{"reply": "<what you say>"}')


def test_answers_get_a_light_touch():
    assert "like a smart friend" in ANSWER_SYSTEM and "Never corporate" in ANSWER_SYSTEM


def test_no_tuning_keeps_the_fixed_prompt():
    llm = ChatLLM()
    Chat(llm, now=lambda: NOW).reply("hey")
    assert llm.calls[0][0] == CHAT_SYSTEM


def test_the_users_tuning_goes_after_the_fixed_prompt():
    llm = ChatLLM()
    chat = Chat(llm, now=lambda: NOW, personality=lambda: "Swear a little. Call my code spaghetti.")
    chat.reply("hey")
    system = llm.calls[0][0]
    assert system.startswith(CHAT_SYSTEM)                  # Ollama's prompt cache still matches
    assert system.endswith("Swear a little. Call my code spaghetti.")


def test_a_broken_tuning_never_stops_a_reply():
    def broken():
        raise OSError("disk gone")
    llm = ChatLLM()
    assert Chat(llm, now=lambda: NOW, personality=broken).reply("hey") == "Ha, fair."
    assert llm.calls[0][0] == CHAT_SYSTEM


def test_debates_keep_their_own_prompt():
    llm = ChatLLM("Cats. Your turn.")
    chat = Chat(llm, now=lambda: NOW, personality=lambda: "Be grumpy.")
    chat.reply("let's debate cats versus dogs")
    assert llm.calls[0][0] == DEBATE_SYSTEM


def test_with_personality():
    assert with_personality("S", "  ") == "S"
    assert with_personality("S", " calm ").endswith("\ncalm")


def test_the_personality_file(tmp_path):
    assert read_personality(tmp_path) == ""
    path = write_personality(tmp_path, "  Be calm.\nFewer jokes.  ")
    assert path == personality_path(tmp_path) and path.parent.name == "config"
    assert read_personality(tmp_path) == "Be calm. Fewer jokes."
    write_personality(tmp_path, "x" * (MAX_PERSONALITY + 50))
    assert len(read_personality(tmp_path)) == MAX_PERSONALITY
    write_personality(tmp_path, "")
    assert not path.exists() and read_personality(tmp_path) == ""


def test_make_chat_reads_the_file_each_time(tmp_path):
    llm = ChatLLM()
    chat = make_chat(llm, SimpleNamespace(home=tmp_path))
    chat.reply("hey")
    write_personality(tmp_path, "Be calm.")
    chat.reply("hey again")
    assert llm.calls[0][0].startswith(CHAT_SYSTEM) and llm.calls[1][0].endswith("Be calm.")   # Red's persona follows the rules


def test_the_general_page_edits_the_personality(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from red.app.main_window import MainWindow
    from red.config import load_settings
    for key in list(os.environ):
        if key.startswith("RED_"):
            monkeypatch.delenv(key, raising=False)
    QApplication.instance() or QApplication([])
    settings = load_settings(tmp_path)
    write_personality(tmp_path, "Be calm.")
    saved = []
    window = MainWindow(settings, save=lambda s, v: saved.append(v) or tmp_path / ".env",
                        hardware=lambda: [], model_rows=lambda s: [], devices=lambda: [])
    page = window.general_page
    assert page.personality.toPlainText() == "Be calm."
    page.personality.setPlainText("More jokes, please.")
    assert window.save()
    assert read_personality(tmp_path) == "More jokes, please."
    assert "RED_PERSONALITY" not in saved[0]                # a file, not a .env line

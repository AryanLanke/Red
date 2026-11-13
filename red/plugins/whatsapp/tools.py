"""Message someone on WhatsApp Desktop (plan.md B3.3).

Numbers come from a [phones] table in contacts.toml:

    [phones]
    rahul = "+919876543210"

Red opens whatsapp://send?phone=..&text=.. (both URL-quoted), reads the message
back (the Executor asks once), and presses Enter only on a yes and only while
WhatsApp's window is in front. No reading messages: WhatsApp has no API for
personal accounts and Red doesn't scrape apps.
"""

from __future__ import annotations

import re
import time
import tomllib
from pathlib import Path
from urllib.parse import quote

from red.config import red_home
from red.desk import Desk
from red.tools.base import Tool, ToolError

EXES = {"whatsapp.root.exe", "whatsapp.exe"}
PHONE = re.compile(r"^\+?\d{7,15}$")


def load_phones(path: Path | None = None) -> dict[str, str]:
    path = path or red_home() / "config" / "contacts.toml"
    try:
        table = tomllib.loads(path.read_text(encoding="utf-8")).get("phones", {})
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    out = {}
    for name, number in (table.items() if isinstance(table, dict) else ()):
        digits = re.sub(r"[ ()-]", "", str(number))
        if PHONE.match(digits):
            out[" ".join(str(name).lower().split())] = digits.lstrip("+")
    return out


class OpenWhatsApp(Tool):
    name = "open_whatsapp"
    description = "Open WhatsApp: 'open WhatsApp'."
    args_schema = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}

    def __init__(self, desk=None):
        self.desk = desk or Desk()

    def run(self) -> str:
        try:
            self.desk.open_uri("whatsapp://")
        except OSError as e:
            raise ToolError("I couldn't open WhatsApp. Is it installed?") from e
        self.finish_later(lambda: self.desk.front_app(EXES))
        return "Opening WhatsApp."


class WhatsAppMessage(Tool):
    name = "whatsapp_message"
    description = "Send a WhatsApp message: 'message Rahul on WhatsApp: running late'."
    destructive = True
    args_schema = {"type": "object",
                   "properties": {"to": {"type": "string", "minLength": 1, "maxLength": 40},
                                  "text": {"type": "string", "minLength": 1, "maxLength": 500}},
                   "required": ["to", "text"], "additionalProperties": False}
    phones = staticmethod(load_phones)

    def __init__(self, desk=None):
        self.desk = desk or Desk()

    def number(self, to: str) -> str:
        key = " ".join(to.lower().split())
        phones = self.phones()
        if key in phones:
            return phones[key]
        if PHONE.match(re.sub(r"[ ()-]", "", key)):
            return re.sub(r"[ ()-]", "", key).lstrip("+")
        raise ToolError(f"I don't have a number for {to}. Add it under [phones] in contacts.toml.")

    def prepare(self, to: str, text: str) -> None:
        self.number(to)

    def describe(self, to: str = "", text: str = "") -> str:
        return f'Send {to.strip()} this on WhatsApp: "{text.strip()}"'

    def run(self, to: str, text: str) -> str:
        number = self.number(to)
        text = " ".join(text.split())
        try:
            self.desk.open_uri(f"whatsapp://send?phone={number}&text={quote(text, safe='')}")
        except OSError as e:
            raise ToolError("I couldn't open WhatsApp. Is it installed?") from e
        if not self.desk.front_app(EXES, wait=10.0):
            return "WhatsApp didn't come up. The message is filled in when it does; press Enter."
        time.sleep(1.0)
        if self.desk.foreground_exe() not in EXES:
            return "Something else jumped in front, so I didn't press Enter. The chat is ready."
        self.desk.press("enter")
        return f"Sent to {to.strip()}."

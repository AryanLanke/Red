"""compose_mail: open a new email draft through a mailto: link. It never sends.

The draft opens in whatever mail app Windows uses for mailto: links (Outlook,
the Mail app, or a browser's Gmail handler), with the recipient, subject and
body filled in. Red has no access to any mail account; you review the draft
and press Send yourself.

A spoken name ("mail mom") becomes an address only through
RED_HOME\\config\\contacts.toml:

    [contacts]
    mom = "mom@example.com"
"""

from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path
from typing import Callable
from urllib.parse import quote

from ..config import red_home
from .base import Tool, ToolError

MAX_SUBJECT = 200
MAX_BODY = 1500          # long mailto: links can fail to open
MAX_RECIPIENTS = 10

# Deliberately strict: no spaces, quotes, ?, & or # that could change the link.
EMAIL = re.compile(r"^[A-Za-z0-9.!$%*+/=^_`{|}~'-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
                   r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+$")


def contacts_file() -> Path:
    return red_home() / "config" / "contacts.toml"


def _key(name: str) -> str:
    words = re.sub(r"[^a-z0-9 ]+", " ", name.lower()).split()
    while words and words[0] in {"my", "the", "to"}:
        words = words[1:]
    return " ".join(words)


def load_contacts(path: Path) -> dict[str, str]:
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise ToolError(f"I couldn't read contacts.toml: {e}") from e
    table = data.get("contacts", {})
    if not isinstance(table, dict):
        raise ToolError("contacts.toml: [contacts] must be a table of name = \"address\"")
    contacts = {}
    for name, address in table.items():
        if not isinstance(address, str) or not EMAIL.match(address.strip()):
            raise ToolError(f"contacts.toml: {name} needs a valid email address")
        contacts[_key(str(name))] = address.strip()
    return contacts


def split_recipients(text: str) -> list[str]:
    parts = re.split(r"\s*(?:,|;|\band\b|&)\s*", text.strip())
    return [p.strip() for p in parts if p.strip()]


def mailto_url(to: list[str], subject: str = "", body: str = "") -> str:
    """RFC 6068 mailto: with every part percent-encoded."""
    for address in to:
        if not EMAIL.match(address):
            raise ValueError(f"not an email address: {address!r}")
    url = "mailto:" + ",".join(quote(a, safe="@") for a in to)
    fields = []
    if subject:
        fields.append("subject=" + quote(subject, safe=""))
    if body:
        body = "\r\n".join(body.splitlines())        # CRLF line breaks, as the RFC asks
        fields.append("body=" + quote(body, safe=""))
    return url + ("?" + "&".join(fields) if fields else "")


def _default_open(url: str) -> None:
    os.startfile(url)  # type: ignore[attr-defined]  # Windows only


class ComposeMail(Tool):
    name = "compose_mail"
    description = ("Write a new email draft in the user's mail app, with the recipient, "
                   "subject and body filled in, for the user to review and send. It never "
                   "sends anything.")
    args_schema = {
        "type": "object",
        "properties": {
            "to": {"type": "string", "maxLength": 300,
                   "description": "Email address or contact name, as the user said it."},
            "subject": {"type": "string", "maxLength": MAX_SUBJECT},
            "body": {"type": "string", "maxLength": MAX_BODY,
                     "description": "A short message body, if the user said what to write."},
        },
        "additionalProperties": False,
    }

    def __init__(self, open_url: Callable[[str], None] = _default_open,
                 contacts: Callable[[], dict[str, str]] = lambda: load_contacts(contacts_file())):
        self._open = open_url
        self._contacts = contacts

    def run(self, to: str = "", subject: str = "", body: str = "") -> str:
        subject = " ".join(subject.split())[:MAX_SUBJECT]
        body = body.strip()[:MAX_BODY]
        addresses, unknown = [], []
        wanted = split_recipients(to)[:MAX_RECIPIENTS] if to else []
        contacts = self._contacts() if any(not EMAIL.match(w) for w in wanted) else {}
        for who in wanted:
            if EMAIL.match(who):
                addresses.append(who)
            elif _key(who) in contacts:
                addresses.append(contacts[_key(who)])
            else:
                unknown.append(who)

        try:
            self._open(mailto_url(addresses, subject, body))
        except OSError as e:
            raise ToolError("No mail app is set up to open email links. Choose a default "
                            "email app in Windows Settings.") from e

        reply = "I opened a new draft"
        if addresses:
            reply += " to " + ", ".join(addresses)
        if subject:
            reply += f" about {subject}"
        reply += "."
        if unknown:
            reply += (f" I don't have an address for {', '.join(unknown)}, so add it in the "
                      "draft, or put it in contacts.toml.")
        return reply + " Check it and press Send yourself."

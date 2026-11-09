"""Gmail, after the optional sign-in (python -m red google-login).

- check_mail: "any new mail?" -- how many unread, and who the newest few are from
- read_mail: "read my mail from Rahul" -- the newest one, summarised by the local model
- reply_mail: "reply saying I'll come tomorrow" -- to the mail Red just read
- send_mail: "mail Mom that I'll be late"

Sending a mail or a reply reads it back once first ("Sending to Mom: I'll be
late. Send?"), as the user chose; reading never asks. A recipient must be one
of your Google Contacts, a name in contacts.toml, or a valid address; Red never
guesses one. Only the mail text goes to your own Google account; the summary is
made by the local model on this PC.
"""

from __future__ import annotations

import base64
import re
from email.message import EmailMessage
from email.utils import getaddresses, parseaddr
from typing import Callable

from ..google_auth import GoogleApi, GoogleContacts, GoogleError
from ..llm import LLM
from .assistant import _UsesLLM, ask_model
from .base import Tool, ToolError
from .mail import EMAIL, MAX_BODY, MAX_SUBJECT, _key, contacts_file, load_contacts, split_recipients

GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
NEWEST = 3                 # senders read out for "any new mail?"
MAX_RECIPIENTS = 5
MAX_MAIL_TEXT = 4000       # of one mail, for the summary

MAIL_SYSTEM = """You are Red, a voice assistant. Using only the email below, tell the user in 2 or 3 short spoken sentences who it's from, what it says, and anything it asks them to do or reply to. No lists, markdown or links, and don't add anything that isn't in the email.
Reply with JSON only: {"answer": "<what you say>"}"""


def _header(message: dict, name: str) -> str:
    for h in message.get("payload", {}).get("headers", []):
        if h.get("name", "").lower() == name.lower():
            return " ".join(str(h.get("value", "")).split())
    return ""


def sender_name(from_header: str) -> str:
    """'Rahul Mehta <rahul@x.com>' -> 'Rahul Mehta'; a bare address -> its name part."""
    name, address = parseaddr(from_header)
    return name.strip('" ') or address.split("@")[0] or "someone"


def _body_text(payload: dict) -> str:
    """The plain-text part of a message, decoded."""
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        data = payload["body"]["data"]
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", "replace")
    for part in payload.get("parts", []) or []:
        text = _body_text(part)
        if text:
            return text
    return ""


def _without_quotes(text: str) -> str:
    """Drop the quoted earlier mail ("On Mon, X wrote:" and "> ..." lines)."""
    lines = []
    for line in text.splitlines():
        if line.lstrip().startswith(">") or re.match(r"\s*On .{5,120} wrote:\s*$", line):
            break
        lines.append(line)
    return "\n".join(lines).strip()


def _search_name(who: str) -> str:
    """Words or an address that are safe inside a Gmail search."""
    who = who.strip()
    if EMAIL.match(who):
        return who
    return " ".join(re.sub(r"[^\w' .-]+", " ", who).split())[:60]


class _Gmail(Tool):
    def __init__(self, api: GoogleApi | None = None,
                 contacts: Callable[[], dict[str, str]] | None = None):
        self._api = api or GoogleApi()
        self._google_contacts = contacts if contacts is not None else GoogleContacts(self._api)

    def _contacts(self) -> dict[str, str]:
        """Google Contacts first, then contacts.toml."""
        found: dict[str, str] = {}
        try:
            found.update(load_contacts(contacts_file()))
        except ToolError:
            pass
        try:
            google = self._google_contacts()
        except GoogleError:
            google = {}
        found.update({_key(k): v for k, v in google.items()})
        return found

    def resolve(self, to: str) -> list[tuple[str, str]]:
        """[(how to say it, address)] for each recipient. Raises if any is unknown."""
        wanted = split_recipients(to)[:MAX_RECIPIENTS] if to else []
        if not wanted:
            raise ToolError("Who should I send it to?")
        contacts = None
        out, unknown = [], []
        for who in wanted:
            if EMAIL.match(who):
                out.append((who, who))
                continue
            contacts = self._contacts() if contacts is None else contacts
            address = contacts.get(_key(who))
            if address and EMAIL.match(address):
                out.append((who, address))
            else:
                unknown.append(who)
        if unknown:
            raise ToolError(f"I don't have an email address for {', '.join(unknown)}. "
                            "Add them to your Google Contacts or contacts.toml.")
        return out

    def _send(self, message: EmailMessage, thread_id: str | None = None) -> None:
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        body = {"raw": raw}
        if thread_id:
            body["threadId"] = thread_id
        self._api.post(f"{GMAIL}/messages/send", body)


class _Reads(_Gmail, _UsesLLM):
    """Gmail tools that also need the local model."""

    def __init__(self, api=None, contacts=None, llm: LLM | None = None):
        _Gmail.__init__(self, api, contacts)
        _UsesLLM.__init__(self, llm)


class CheckMail(_Gmail):
    name = "check_mail"
    description = ("Check Gmail for new mail: how many unread emails there are, and who the "
                   "newest ones are from ('any new mail?', 'do I have emails').")
    args_schema = {"type": "object", "properties": {}, "additionalProperties": False}

    def run(self) -> str:
        try:
            inbox = self._api.get(f"{GMAIL}/labels/INBOX")
            unread = int(inbox.get("messagesUnread", 0))
            if not unread:
                return "No new mail."
            listed = self._api.get(f"{GMAIL}/messages", q="in:inbox is:unread", maxResults=NEWEST)
            newest = []
            for item in listed.get("messages", [])[:NEWEST]:
                msg = self._api.get(f"{GMAIL}/messages/{item['id']}", format="metadata",
                                    metadataHeaders=["From", "Subject"])
                subject = _header(msg, "Subject")[:80] or "no subject"
                newest.append(f"{sender_name(_header(msg, 'From'))}, about {subject}")
        except GoogleError as e:
            raise ToolError(str(e)) from e
        self.last_details = "\n".join(newest)
        count = "one unread email" if unread == 1 else f"{unread} unread emails"
        if not newest:
            return f"You have {count}."
        return f"You have {count}. The newest: " + "; ".join(newest) + "."


class LastMail:
    """The mail Red read most recently, so "reply saying ..." knows which one."""

    def __init__(self):
        self.message: dict | None = None


class ReadMail(_Reads):
    name = "read_mail"
    description = ("Read the user's newest email, or the newest from someone or about something, "
                   "and say what it says ('read my mail from Rahul', 'what did Amazon send me').")
    args_schema = {
        "type": "object",
        "properties": {
            "sender": {"type": "string", "maxLength": 100,
                       "description": "Who it's from, as the user said it, if they said."},
            "about": {"type": "string", "maxLength": 100,
                      "description": "Words from the subject or text, if the user said."},
        },
        "additionalProperties": False,
    }

    def __init__(self, api=None, contacts=None, llm=None, last: LastMail | None = None):
        super().__init__(api, contacts, llm)
        self.last = last or LastMail()

    def run(self, sender: str = "", about: str = "") -> str:
        self._command = ""
        query = ["in:inbox"]
        if sender.strip():
            who = sender.strip()
            address = None if EMAIL.match(who) else self._contacts().get(_key(who))
            name = _search_name(address or who)
            if name:
                query.append(f'from:"{name}"')
        if about.strip():
            words = _search_name(about)
            if words:
                query.append(f'"{words}"')
        try:
            listed = self._api.get(f"{GMAIL}/messages", q=" ".join(query), maxResults=1)
            items = listed.get("messages", [])
            if not items:
                who = f" from {sender.strip()}" if sender.strip() else ""
                return f"I didn't find any mail{who}."
            msg = self._api.get(f"{GMAIL}/messages/{items[0]['id']}", format="full")
        except GoogleError as e:
            raise ToolError(str(e)) from e
        self.last.message = msg
        frm, subject = _header(msg, "From"), _header(msg, "Subject")
        self.last_details = f"From: {frm}\nSubject: {subject}"
        text = _without_quotes(_body_text(msg.get("payload", {})))[:MAX_MAIL_TEXT] or msg.get("snippet", "")
        if self._llm is None:
            return f"From {sender_name(frm)}, about {subject or 'nothing'}: {msg.get('snippet', '')[:300]}"
        return ask_model(self._llm, MAIL_SYSTEM,
                         f"From: {frm}\nSubject: {subject}\n\n{text}")


def _plain(text: str, limit: int) -> str:
    return text.strip()[:limit]


class ReplyMail(_Gmail):
    name = "reply_mail"
    description = ("Reply to the email Red just read, with the user's words ('reply saying I'll "
                   "come tomorrow'). Red reads the reply back before sending.")
    destructive = True       # it sends a mail: read back once first
    args_schema = {
        "type": "object",
        "properties": {"body": {"type": "string", "minLength": 1, "maxLength": MAX_BODY,
                                "description": "The reply, written out from the user's words."}},
        "required": ["body"],
        "additionalProperties": False,
    }

    def __init__(self, api=None, contacts=None, last: LastMail | None = None):
        super().__init__(api, contacts)
        self.last = last or LastMail()

    def prepare(self, body: str = "") -> None:
        if self.last.message is None:
            raise ToolError("Which mail? Ask me to read it first, then say reply.")
        if not body.strip():
            raise ToolError("What should the reply say?")

    def describe(self, body: str = "") -> str:
        frm = sender_name(_header(self.last.message or {}, "From"))
        return f"Replying to {frm}: {_plain(body, 300)} Send"

    def run(self, body: str) -> str:
        self.prepare(body)
        original = self.last.message
        frm = _header(original, "Reply-To") or _header(original, "From")
        addresses = [a for _, a in getaddresses([frm]) if EMAIL.match(a)]
        if not addresses:
            raise ToolError("That mail has no address I can reply to.")
        subject = _header(original, "Subject")
        message = EmailMessage()
        message["To"] = addresses[0]
        message["Subject"] = (subject if subject.lower().startswith("re:") else f"Re: {subject}")[:MAX_SUBJECT]
        msg_id = _header(original, "Message-ID")
        if msg_id:
            message["In-Reply-To"] = msg_id
            message["References"] = " ".join(filter(None, [_header(original, "References"), msg_id]))
        message.set_content(_plain(body, MAX_BODY))
        try:
            self._send(message, original.get("threadId"))
        except GoogleError as e:
            raise ToolError(str(e)) from e
        return f"Sent your reply to {sender_name(frm)}."


class SendMail(_Gmail):
    name = "send_mail"
    description = ("Send an email from the user's Gmail ('mail Mom that I'll be late', 'email "
                   "Rahul about lunch'). Write a short subject and the message from the user's "
                   "words. Red reads it back before sending. If the user says draft, use "
                   "compose_mail instead.")
    destructive = True       # it sends a mail: read back once first
    args_schema = {
        "type": "object",
        "properties": {
            "to": {"type": "string", "minLength": 1, "maxLength": 300,
                   "description": "Contact name or email address, as the user said it."},
            "subject": {"type": "string", "maxLength": MAX_SUBJECT},
            "body": {"type": "string", "minLength": 1, "maxLength": MAX_BODY,
                     "description": "The message, written out from the user's words."},
        },
        "required": ["to", "body"],
        "additionalProperties": False,
    }

    def prepare(self, to: str = "", subject: str = "", body: str = "") -> None:
        self.resolve(to)
        if not body.strip():
            raise ToolError("What should the mail say?")

    def describe(self, to: str = "", subject: str = "", body: str = "") -> str:
        names = ", ".join(n for n in split_recipients(to)[:MAX_RECIPIENTS])
        return f"Sending to {names}: {_plain(body, 300)} Send"

    def run(self, to: str, body: str, subject: str = "") -> str:
        recipients = self.resolve(to)
        body = _plain(body, MAX_BODY)
        if not body:
            raise ToolError("What should the mail say?")
        subject = " ".join(subject.split())[:MAX_SUBJECT] or " ".join(body.split()[:6])
        message = EmailMessage()
        message["To"] = ", ".join(address for _, address in recipients)
        message["Subject"] = subject
        message.set_content(body)
        try:
            self._send(message)
        except GoogleError as e:
            raise ToolError(str(e)) from e
        self.last_details = "To: " + ", ".join(f"{n} <{a}>" for n, a in recipients)
        return f"Sent to {', '.join(n for n, _ in recipients)}."


def mail_tools(api: GoogleApi | None = None, contacts=None) -> list[Tool]:
    """The four Gmail tools, sharing one API, one contacts list and the last mail read."""
    api = api or GoogleApi()
    contacts = contacts if contacts is not None else GoogleContacts(api)
    last = LastMail()
    return [CheckMail(api, contacts), ReadMail(api, contacts, last=last),
            ReplyMail(api, contacts, last=last), SendMail(api, contacts)]


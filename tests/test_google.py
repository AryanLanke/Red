"""Mail, calendar and the Google sign-in, with a fake Google (no network)."""

import base64
import email
import io
import json
import threading
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest

from fakes import FakeAsk
from red import google_auth as ga
from red.executor import Executor
from red.router import Router
from red.tools import ToolRegistry, default_registry
from red.tools.base import ToolError
from red.tools.calendar import (CalendarAdd, CalendarCancel, CalendarEvents, CalendarMove, calendar_tools,
                                resolve_day, say_time)
from red.tools.gmail import CheckMail, LastMail, ReadMail, ReplyMail, SendMail, mail_tools, sender_name

TZ = timezone(timedelta(hours=-8))
NOW = datetime(2026, 11, 9, 9, 0, tzinfo=TZ)            # a Monday


class FakeApi:
    """Answers by (method, address); records every call."""

    def __init__(self, answers=None):
        self.answers = answers or {}
        self.calls = []

    def request(self, method, url, params=None, body=None):
        self.calls.append((method, url, params or {}, body))
        for (m, prefix), answer in self.answers.items():
            if m == method and url.startswith(prefix):
                return answer(params or {}, body) if callable(answer) else answer
        return {}

    def get(self, url, **params):
        return self.request("GET", url, params=params)

    def post(self, url, body, **params):
        return self.request("POST", url, params=params, body=body)

    def patch(self, url, body, **params):
        return self.request("PATCH", url, params=params, body=body)

    def delete(self, url, **params):
        return self.request("DELETE", url, params=params)


@pytest.fixture(autouse=True)
def no_contacts_file(tmp_path, monkeypatch):
    monkeypatch.setenv("RED_HOME", str(tmp_path))      # contacts.toml: none unless a test writes one


GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
CONTACTS = {"mom": "mom@example.com", "rahul mehta": "rahul@example.com", "rahul": "rahul@example.com"}


def message(mid, frm, subject, text="Hi", thread="t1", msgid="<abc@mail>"):
    data = base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")
    return {"id": mid, "threadId": thread, "snippet": text[:50],
            "payload": {"mimeType": "multipart/alternative",
                        "headers": [{"name": "From", "value": frm}, {"name": "Subject", "value": subject},
                                    {"name": "Message-ID", "value": msgid}],
                        "parts": [{"mimeType": "text/plain", "body": {"data": data}}]}}


def sent_mail(api):
    (method, url, _, body), = [c for c in api.calls if c[1].endswith("/messages/send")]
    return email.message_from_bytes(base64.urlsafe_b64decode(body["raw"])), body


# --- mail ------------------------------------------------------------------------------

def test_any_new_mail():
    api = FakeApi({("GET", f"{GMAIL}/labels/INBOX"): {"messagesUnread": 3},
                   ("GET", f"{GMAIL}/messages/1"): message("1", "Rahul Mehta <rahul@example.com>", "Dinner Friday"),
                   ("GET", f"{GMAIL}/messages/2"): message("2", "Amazon <ship@amazon.com>", "Your order"),
                   ("GET", f"{GMAIL}/messages"): {"messages": [{"id": "1"}, {"id": "2"}]}})
    reply = CheckMail(api, contacts=dict).run()
    assert reply == ("You have 3 unread emails. The newest: Rahul Mehta, about Dinner Friday; "
                     "Amazon, about Your order.")
    assert api.calls[1][2] == {"q": "in:inbox is:unread", "maxResults": 3}


def test_no_new_mail():
    api = FakeApi({("GET", f"{GMAIL}/labels/INBOX"): {"messagesUnread": 0}})
    assert CheckMail(api, contacts=dict).run() == "No new mail."


class FakeLLM:
    def __init__(self):
        self.calls = []

    def complete_json(self, system, user, schema, **kw):
        self.calls.append((system, user))
        return json.dumps({"answer": "Rahul asks if you can come to dinner on Friday."})


def test_read_my_mail_from_rahul_uses_the_contact_and_the_local_model():
    api = FakeApi({("GET", f"{GMAIL}/messages/9"): message("9", "Rahul <rahul@example.com>", "Dinner",
                                                          "Can you come Friday?\n\nOn Mon, X wrote:\n> old"),
                   ("GET", f"{GMAIL}/messages"): {"messages": [{"id": "9"}]}})
    llm, last = FakeLLM(), LastMail()
    tool = ReadMail(api, contacts=lambda: CONTACTS, llm=llm, last=last)
    assert tool.run(sender="Rahul") == "Rahul asks if you can come to dinner on Friday."
    assert api.calls[0][2]["q"] == 'in:inbox from:"rahul@example.com"'
    assert "Can you come Friday?" in llm.calls[0][1] and "> old" not in llm.calls[0][1]
    assert last.message["id"] == "9"


def test_search_words_cant_change_the_query():
    api = FakeApi({("GET", f"{GMAIL}/messages"): {"messages": []}})
    ReadMail(api, contacts=dict, llm=FakeLLM()).run(sender='x" OR from:"boss', about="a\" -label:x")
    q = api.calls[0][2]["q"]
    assert q.count('"') == 4 and "OR from" in q        # quotes stripped; stays two quoted phrases


def test_send_mail_reads_back_and_sends_only_on_yes():
    api = FakeApi()
    tool = SendMail(api, contacts=lambda: CONTACTS)
    registry = ToolRegistry([tool])
    route = Router(registry).parse(json.dumps({"tool": "send_mail", "args": {
        "to": "Mom", "subject": "Running late", "body": "I'll be late."}}))
    ask = FakeAsk("no", "yes")
    executor = Executor(registry, ask=ask)
    assert executor.execute("mail Mom that I'll be late", route) == "Cancelled."
    assert api.calls == []
    assert executor.execute("mail Mom that I'll be late", route) == "Sent to Mom."
    assert [q for q, _ in ask.questions] == ["Sending to Mom: I'll be late. Send?"] * 2
    mail, body = sent_mail(api)
    assert mail["To"] == "mom@example.com" and mail["Subject"] == "Running late"
    assert mail.get_payload().strip() == "I'll be late."


def test_an_unknown_recipient_is_refused_before_asking():
    api = FakeApi()
    registry = ToolRegistry([SendMail(api, contacts=lambda: CONTACTS)])
    route = Router(registry).parse(json.dumps({"tool": "send_mail", "args": {"to": "Priya", "body": "Hi"}}))
    ask = FakeAsk("yes")
    reply = Executor(registry, ask=ask).execute("mail Priya hi", route)
    assert "don't have an email address for Priya" in reply
    assert ask.questions == [] and api.calls == []


def test_contacts_toml_is_used_too(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "contacts.toml").write_text('[contacts]\nsis = "sis@example.com"\n', encoding="utf-8")
    assert SendMail(FakeApi(), contacts=dict).resolve("sis") == [("sis", "sis@example.com")]


def test_header_injection_is_impossible():
    api = FakeApi()
    SendMail(api, contacts=lambda: CONTACTS).run(to="mom", subject="Hi\r\nBcc: evil@example.com", body="x")
    mail, _ = sent_mail(api)
    assert mail["Bcc"] is None and mail["Subject"] == "Hi Bcc: evil@example.com"


def test_reply_needs_a_mail_read_first_and_threads_it():
    api = FakeApi()
    last = LastMail()
    tool = ReplyMail(api, contacts=dict, last=last)
    with pytest.raises(ToolError, match="read it first"):
        tool.prepare(body="I'll come tomorrow.")
    last.message = message("9", "Rahul <rahul@example.com>", "Dinner", thread="th9", msgid="<m9@x>")
    assert tool.describe(body="I'll come tomorrow.") == "Replying to Rahul: I'll come tomorrow. Send"
    assert tool.run(body="I'll come tomorrow.") == "Sent your reply to Rahul."
    mail, body = sent_mail(api)
    assert mail["To"] == "rahul@example.com" and mail["Subject"] == "Re: Dinner"
    assert mail["In-Reply-To"] == "<m9@x>" and body["threadId"] == "th9"


def test_sender_name():
    assert sender_name('"Rahul Mehta" <rahul@x.com>') == "Rahul Mehta"
    assert sender_name("noreply@amazon.com") == "noreply"


# --- calendar ------------------------------------------------------------------------

EVENTS = "https://www.googleapis.com/calendar/v3/calendars/primary/events"


def event(eid, title, hour, minutes=60, day=NOW.date()):
    start = datetime(day.year, day.month, day.day, hour, 0, tzinfo=TZ)
    return {"id": eid, "summary": title, "start": {"dateTime": start.isoformat()},
            "end": {"dateTime": (start + timedelta(minutes=minutes)).isoformat()}}


def cal(api, cls):
    return cls(api, now=lambda: NOW)


@pytest.mark.parametrize("day, expected", [
    ("today", "2026-11-09"), ("tomorrow", "2026-11-10"), ("friday", "2026-11-13"),
    ("monday", "2026-11-09"), ("sunday", "2026-11-15"), ("2026-12-25", "2026-12-25"),
])
def test_resolve_day(day, expected):
    assert resolve_day(day, NOW.date()).isoformat() == expected


def test_say_time():
    assert say_time(NOW.replace(hour=16)) == "4 PM" and say_time(NOW.replace(hour=10, minute=30)) == "10:30 AM"


def test_whats_on_my_calendar_tomorrow():
    tomorrow = NOW.date() + timedelta(days=1)
    api = FakeApi({("GET", EVENTS): {"items": [event("a", "Standup", 10, day=tomorrow),
                                               event("b", "Dentist", 16, day=tomorrow)]}})
    assert cal(api, CalendarEvents).run(day="tomorrow") == "Tomorrow you have 2 things: Standup at 10 AM; Dentist at 4 PM."
    params = api.calls[0][2]
    assert params["timeMin"].startswith("2026-11-10T00:00:00") and params["singleEvents"] == "true"


def test_add_a_meeting_friday_at_3():
    api = FakeApi()
    assert cal(api, CalendarAdd).run(title="Meeting", day="friday", time="15:00") == \
        "Added Meeting on Friday at 3 PM."
    body = api.calls[0][3]
    assert body["start"]["dateTime"] == "2026-11-13T15:00:00-08:00"
    assert body["end"]["dateTime"] == "2026-11-13T16:00:00-08:00"


def test_move_my_5_pm_to_6_keeps_its_length():
    api = FakeApi({("GET", EVENTS): {"items": [event("e5", "Gym", 17, minutes=90)]}})
    assert cal(api, CalendarMove).run(time="17:00", new_time="18:00") == "Moved Gym to today at 6 PM."
    method, url, _, body = api.calls[-1]
    assert (method, url) == ("PATCH", f"{EVENTS}/e5")
    assert body["end"]["dateTime"] == "2026-11-09T19:30:00-08:00"


def test_cancel_my_4_pm_reads_back_and_deletes_only_on_yes():
    api = FakeApi({("GET", EVENTS): {"items": [event("d4", "Dentist", 16)]}})
    tool = cal(api, CalendarCancel)
    registry = ToolRegistry([tool])
    route = Router(registry).parse('{"tool": "calendar_cancel", "args": {"time": "16:00"}}')
    ask = FakeAsk("no", "yes")
    executor = Executor(registry, ask=ask)
    assert executor.execute("cancel my 4 pm", route) == "Cancelled."
    assert not [c for c in api.calls if c[0] == "DELETE"]
    assert executor.execute("cancel my 4 pm", route) == "Deleted Dentist at 4 PM today."
    assert [q for q, _ in ask.questions] == ["Deleting Dentist at 4 PM today. Delete?"] * 2
    assert [c[:2] for c in api.calls if c[0] == "DELETE"] == [("DELETE", f"{EVENTS}/d4")]


def test_nothing_or_two_at_that_time():
    api = FakeApi({("GET", EVENTS): {"items": [event("a", "One", 16), event("b", "Two", 16)]}})
    with pytest.raises(ToolError, match="more than one"):
        cal(api, CalendarCancel).prepare(time="16:00")
    with pytest.raises(ToolError, match="don't see anything today at 9 AM"):
        cal(api, CalendarCancel).prepare(time="09:00")


def test_a_strange_event_id_never_reaches_the_address():
    api = FakeApi({("GET", EVENTS): {"items": [{**event("x", "Odd", 16), "id": "../../calendars"}]}})
    with pytest.raises(ToolError):
        cal(api, CalendarCancel).prepare(time="16:00")


def test_bad_days_and_times_are_refused_by_the_schema():
    from red.router import RouteError
    router = Router(ToolRegistry(calendar_tools(FakeApi())))
    for bad in ('{"tool": "calendar_add", "args": {"title": "x", "time": "3 pm"}}',
                '{"tool": "calendar_add", "args": {"title": "x", "time": "15:00", "day": "next week"}}',
                '{"tool": "calendar_events", "args": {"day": "2026-11-09; rm"}}'):
        with pytest.raises(RouteError):
            router.parse(bad)


# --- registry -------------------------------------------------------------------------

def test_the_tools_appear_only_after_signing_in(tmp_path):
    names = {"check_mail", "read_mail", "reply_mail", "send_mail",
             "calendar_events", "calendar_add", "calendar_move", "calendar_cancel"}
    assert not names & {t.name for t in default_registry()}           # not signed in (tmp RED_HOME)
    (tmp_path / "config").mkdir(exist_ok=True)
    ga.token_path(tmp_path).write_text("{}", encoding="utf-8")
    registry = default_registry()
    assert names <= {t.name for t in registry}
    assert {t.name for t in registry if t.destructive} >= {"send_mail", "reply_mail", "calendar_cancel"}
    assert not any(registry.get(n).destructive for n in ("check_mail", "read_mail", "calendar_add",
                                                         "calendar_move", "calendar_events"))
    assert "compose_mail" in registry                             # drafts still work


def test_mail_tools_share_the_last_mail():
    read, reply = mail_tools(FakeApi(), contacts=dict)[1:3]
    assert read.last is reply.last


# --- signing in -------------------------------------------------------------------------

def client_file(home):
    (home / "config").mkdir(exist_ok=True)
    ga.client_path(home).write_text(json.dumps({"installed": {"client_id": "cid", "client_secret": "sec"}}),
                                    encoding="utf-8")


class TokenServer:
    """Stands in for oauth2.googleapis.com/token."""

    def __init__(self, reply):
        self.reply, self.forms = reply, []

    def __call__(self, req, timeout):
        self.forms.append(dict(urllib.parse.parse_qsl(req.data.decode())))
        return io.BytesIO(json.dumps(self.reply).encode())


def test_login_with_pkce_and_a_one_time_local_address(tmp_path):
    client_file(tmp_path)
    token = TokenServer({"refresh_token": "r1", "access_token": "a1", "expires_in": 3600})

    def browser(url):
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        assert query["code_challenge_method"] == "S256" and query["access_type"] == "offline"
        assert query["scope"].split() == list(ga.SCOPES)
        assert query["redirect_uri"].startswith("http://127.0.0.1:")
        # Google sends the browser back to Red with the code:
        back = f"{query['redirect_uri']}?state={query['state']}&code=c0de"
        threading.Thread(target=lambda: urllib.request.urlopen(back, timeout=5).read(), daemon=True).start()
    path = ga.login(tmp_path, open_browser=browser, opener=token, timeout=10)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["refresh_token"] == "r1" and path == tmp_path / "config" / "google-token.json"
    form = token.forms[0]
    assert form["code"] == "c0de" and form["grant_type"] == "authorization_code" and len(form["code_verifier"]) >= 43


def test_login_without_a_client_file_explains(tmp_path):
    with pytest.raises(ga.GoogleError, match="google-client.json"):
        ga.login(tmp_path, open_browser=lambda url: None)


def test_the_access_token_is_refreshed_when_it_expires(tmp_path):
    client_file(tmp_path)
    ga.token_path(tmp_path).write_text(json.dumps({"refresh_token": "r1", "access_token": "old",
                                                   "expires_at": 100}), encoding="utf-8")
    seen = []

    def opener(req, timeout):
        if req.full_url == ga.TOKEN_URL:
            return io.BytesIO(json.dumps({"access_token": "new", "expires_in": 3600}).encode())
        seen.append((req.full_url, req.get_header("Authorization")))
        return io.BytesIO(b'{"ok": true}')
    api = ga.GoogleApi(tmp_path, opener=opener, clock=lambda: 1000.0)
    assert api.get(f"{GMAIL}/labels/INBOX") == {"ok": True}
    assert seen == [(f"{GMAIL}/labels/INBOX", "Bearer new")]
    assert json.loads(ga.token_path(tmp_path).read_text())["access_token"] == "new"


def test_only_google_api_addresses(tmp_path):
    with pytest.raises(ValueError):
        ga.GoogleApi(tmp_path).request("GET", "https://evil.example.com/x")


def test_logout_revokes_and_deletes(tmp_path):
    (tmp_path / "config").mkdir()
    ga.token_path(tmp_path).write_text(json.dumps({"refresh_token": "r1"}), encoding="utf-8")
    revoked = TokenServer({})
    assert ga.logout(tmp_path, opener=revoked) is True
    assert revoked.forms == [{"token": "r1"}] and not ga.signed_in(tmp_path)
    assert ga.logout(tmp_path) is False


def test_google_contacts_are_cached():
    calls = []
    api = FakeApi({("GET", ga.PEOPLE_URL): lambda p, b: calls.append(p) or {"connections": [
        {"names": [{"displayName": "Rahul Mehta", "givenName": "Rahul"}],
         "emailAddresses": [{"value": "rahul@example.com"}]},
        {"names": [{"displayName": "No Mail"}]}]}})
    contacts = ga.GoogleContacts(api, clock=lambda: 0.0)
    assert contacts() == {"rahul mehta": "rahul@example.com", "rahul": "rahul@example.com"}
    contacts()
    assert len(calls) == 1


@pytest.mark.parametrize("said, times", [
    ("move my 5 pm to 6", ["17:00", "18:00"]), ("move my 10:30 am meeting to 2 pm", ["10:30", "14:00"]),
    ("move my 12 pm to 1", ["12:00", "13:00"]), ("move it to 7", ["07:00"]),
])
def test_spoken_times(said, times):
    from red.tools.calendar import spoken_times
    assert spoken_times(said) == times


def test_move_uses_your_words_when_the_model_leaves_out_the_time():
    api = FakeApi({("GET", EVENTS): {"items": [event("e5", "Gym", 17)]}})
    tool = cal(api, CalendarMove)
    tool.set_command("move my 5 pm to 6")
    assert tool.run(new_time="18:00") == "Moved Gym to today at 6 PM."
    with pytest.raises(ToolError, match="Which event"):
        tool.run(new_time="18:00")                         # no words this time: ask

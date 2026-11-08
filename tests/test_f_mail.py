"""compose_mail builds an encoded mailto: link. No mail app opens, nothing is sent."""

from urllib.parse import parse_qs, unquote, urlsplit

import pytest

from red.tools.base import ToolError
from red.tools.mail import ComposeMail, load_contacts, mailto_url, split_recipients


class FakeOpen:
    def __init__(self, error=None):
        self.urls, self.error = [], error

    def __call__(self, url):
        self.urls.append(url)
        if self.error:
            raise self.error


def make(contacts=None):
    opener = FakeOpen()
    return ComposeMail(open_url=opener, contacts=lambda: contacts or {}), opener


def parts(url):
    s = urlsplit(url)
    return s.scheme, unquote(s.path), {k: v[0] for k, v in parse_qs(s.query).items()}


def test_full_draft():
    tool, opener = make()
    reply = tool.run(to="bob@example.com", subject="Lunch on Friday",
                     body="Hi Bob,\nAre we still on?")
    assert reply == ("I opened a new draft to bob@example.com about Lunch on Friday. "
                     "Check it and press Send yourself.")
    scheme, to, q = parts(opener.urls[0])
    assert (scheme, to) == ("mailto", "bob@example.com")
    assert q == {"subject": "Lunch on Friday", "body": "Hi Bob,\r\nAre we still on?"}


@pytest.mark.parametrize("text", [
    "a&b=c", "Re: 50% off?", "x\nBcc: evil@example.com", "#hash", "naïve café", "+1 & more",
])
def test_subject_and_body_cannot_add_fields(text):
    tool, opener = make()
    tool.run(to="bob@example.com", subject=text, body=text)
    url = opener.urls[0]
    scheme, to, q = parts(url)
    assert to == "bob@example.com"
    assert set(q) == {"subject", "body"}
    assert q["subject"] == " ".join(text.split())
    assert "\n" not in url and " " not in url and "#" not in url


def test_contact_names_come_from_contacts_toml():
    tool, opener = make({"mom": "mom@example.com", "alex kim": "alex@example.org"})
    reply = tool.run(to="Mom and Alex Kim", subject="Dinner")
    assert parts(opener.urls[0])[1] == "mom@example.com,alex@example.org"
    assert reply.startswith("I opened a new draft to mom@example.com, alex@example.org")


def test_unknown_name_leaves_the_recipient_empty():
    tool, opener = make()
    reply = tool.run(to="Priya", subject="Notes")
    assert opener.urls == ["mailto:?subject=Notes"]
    assert "I don't have an address for Priya" in reply


@pytest.mark.parametrize("bad", ["bob@example.com?cc=evil@x.com", "a b@example.com",
                                 "bob@exa mple.com", "\"x\"@example.com", "bob@", "@x.com",
                                 "bob@example.com&body=hi"])
def test_odd_addresses_are_never_put_in_the_link(bad):
    tool, opener = make()
    tool.run(to=bad)
    assert "evil" not in opener.urls[0] and "body=hi" not in opener.urls[0]
    assert urlsplit(opener.urls[0]).path in ("", "bob@example.com")


def test_empty_draft():
    tool, opener = make()
    assert tool.run() == "I opened a new draft. Check it and press Send yourself."
    assert opener.urls == ["mailto:"]


def test_no_mail_app():
    tool = ComposeMail(open_url=FakeOpen(error=OSError("no association")), contacts=dict)
    with pytest.raises(ToolError, match="No mail app"):
        tool.run(to="bob@example.com")


def test_long_body_is_cut():
    tool, opener = make()
    tool.run(to="bob@example.com", body="x" * 5000)
    assert len(parts(opener.urls[0])[2]["body"]) == 1500


def test_mailto_url_rejects_bad_addresses():
    with pytest.raises(ValueError):
        mailto_url(["not an address"])


def test_split_recipients():
    assert split_recipients("a@x.com, b@y.com; mom and dad & alex") == \
        ["a@x.com", "b@y.com", "mom", "dad", "alex"]


def test_load_contacts(tmp_path):
    assert load_contacts(tmp_path / "missing.toml") == {}
    f = tmp_path / "contacts.toml"
    f.write_text('[contacts]\n"My Mom" = "mom@example.com"\n')
    assert load_contacts(f) == {"mom": "mom@example.com"}
    f.write_text('[contacts]\nmom = "not an email"\n')
    with pytest.raises(ToolError, match="valid email"):
        load_contacts(f)
    f.write_text("[contacts\n")
    with pytest.raises(ToolError, match="couldn't read"):
        load_contacts(f)


def test_never_destructive_and_schema_closed():
    assert ComposeMail.destructive is False
    assert ComposeMail.args_schema["additionalProperties"] is False

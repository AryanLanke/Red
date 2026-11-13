"""Discord without touching your messages (plan.md B3.4).

allowlist.toml:

    [discord]
    mute_key = "ctrl+shift+m"       # the keybinds you set in Discord's settings
    deafen_key = "ctrl+shift+d"
    [discord.channels]
    friends = "discord://-/channels/123456789/987654321"

Only discord:// links from that table are opened, by the name you say. Red
never reads or sends messages: automating a user account breaks Discord's
terms and can get it banned. Mute and deafen press your own keybind, and only
while Discord's window is in front.
"""

from __future__ import annotations

import time
import tomllib
from pathlib import Path

from red.config import red_home
from red.desk import Desk, parse_keys
from red.tools.base import Tool, ToolError

EXES = {"discord.exe"}


def load_config(path: Path | None = None) -> dict:
    path = path or red_home() / "config" / "allowlist.toml"
    try:
        table = tomllib.loads(path.read_text(encoding="utf-8")).get("discord", {})
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return table if isinstance(table, dict) else {}


class _Discord(Tool):
    config = staticmethod(load_config)

    def __init__(self, desk=None):
        self.desk = desk or Desk()


class OpenDiscord(_Discord):
    name = "open_discord"
    description = "Open Discord, or a saved server or channel: 'open Discord', 'open my friends server on Discord'."
    args_schema = {"type": "object",
                   "properties": {"where": {"type": "string", "maxLength": 40}},
                   "required": [], "additionalProperties": False}

    def run(self, where: str = "") -> str:
        channels = self.config().get("channels", {})
        link = "discord://-/channels/@me"
        key = " ".join(where.lower().split())
        if key:
            link = next((str(v) for k, v in channels.items() if " ".join(str(k).lower().split()) == key), "")
            if not link.startswith("discord://"):
                names = ", ".join(sorted(map(str, channels))) or "none saved yet"
                raise ToolError(f"I don't have {where} saved. Saved in allowlist.toml: {names}.")
        try:
            self.desk.open_uri(link)
        except OSError as e:
            raise ToolError("I couldn't open Discord. Is it installed?") from e
        self.finish_later(lambda: self.desk.front_app(EXES))
        return f"Opening {where.strip() or 'Discord'}."


class DiscordVoice(_Discord):
    name = "discord_voice"
    description = "Mute, unmute or deafen yourself in a Discord call: 'mute me on Discord'."
    args_schema = {"type": "object",
                   "properties": {"action": {"type": "string", "enum": ["mute", "unmute", "deafen", "undeafen"]}},
                   "required": ["action"], "additionalProperties": False}

    def run(self, action: str) -> str:
        key = self.config().get("deafen_key" if "deafen" in action else "mute_key", "")
        if not key:
            raise ToolError("Tell me your Discord keybind: set mute_key and deafen_key under "
                            "[discord] in allowlist.toml, the same as in Discord's settings.")
        parse_keys(str(key))
        if self.desk.foreground_exe() not in EXES:
            self.desk.front_app(EXES, wait=3.0)
            time.sleep(0.3)
        if self.desk.foreground_exe() not in EXES:
            raise ToolError("Discord isn't open, so I didn't press anything.")
        self.desk.press(str(key))
        return "Toggled. Discord has no way to tell me whether you're muted now."

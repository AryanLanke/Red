"""System tools: folders, apps, shutdown, restart.

Day 1 defines what each tool accepts, so the router can be tested.
The actions themselves are built on Day 2.
"""

from __future__ import annotations

from .base import Tool

MAX_DELAY_MINUTES = 24 * 60

_NO_ARGS = {"type": "object", "properties": {}, "additionalProperties": False}

_DELAY_ARGS = {
    "type": "object",
    "properties": {
        "minutes": {"type": "integer", "minimum": 0, "maximum": MAX_DELAY_MINUTES,
                    "description": "Delay in minutes. 0 means now."},
    },
    "required": ["minutes"],
    "additionalProperties": False,
}


class OpenFolder(Tool):
    name = "open_folder"
    description = ("Open a folder in File Explorer. Use a known folder name such as "
                   "Downloads, Documents, Desktop, Pictures, Music, or Videos, or a full path.")
    args_schema = {
        "type": "object",
        "properties": {"folder": {"type": "string", "minLength": 1, "maxLength": 260}},
        "required": ["folder"],
        "additionalProperties": False,
    }

    def run(self, folder: str) -> str:
        raise NotImplementedError("open_folder is built on Day 2")


class OpenApp(Tool):
    name = "open_app"
    description = "Start an application by name, for example Notepad, Calculator, or VS Code."
    args_schema = {
        "type": "object",
        "properties": {"app": {"type": "string", "minLength": 1, "maxLength": 100}},
        "required": ["app"],
        "additionalProperties": False,
    }

    def run(self, app: str) -> str:
        raise NotImplementedError("open_app is built on Day 2")


class Shutdown(Tool):
    name = "shutdown"
    description = "Shut down the computer after a delay in minutes (convert hours to minutes)."
    args_schema = _DELAY_ARGS
    destructive = True

    def run(self, minutes: int) -> str:
        raise NotImplementedError("shutdown is built on Day 2")


class Restart(Tool):
    name = "restart"
    description = "Restart the computer after a delay in minutes (convert hours to minutes)."
    args_schema = _DELAY_ARGS
    destructive = True

    def run(self, minutes: int) -> str:
        raise NotImplementedError("restart is built on Day 2")


class CancelShutdown(Tool):
    name = "cancel_shutdown"
    description = "Cancel a scheduled shutdown or restart."
    args_schema = _NO_ARGS

    def run(self) -> str:
        raise NotImplementedError("cancel_shutdown is built on Day 2")

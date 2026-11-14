"""The router's prompt lists each tool's arguments compactly (the JSON schema still constrains the reply)."""

import json

from red.router import Router, compact_args
from red.tools import default_registry


def test_compact_args_names_kinds_and_descriptions():
    schema = {"type": "object",
              "properties": {"url": {"type": "string", "pattern": "^https?://[^ ]+$", "maxLength": 2000},
                             "browser": {"type": "string", "enum": ["chrome", "edge"], "description": "Only if named."},
                             "minutes": {"type": "integer", "minimum": 5, "maximum": 1440},
                             "others": {"type": "array", "items": {"type": "string"}},
                             "loud": {"type": "boolean"}},
              "required": ["url"], "additionalProperties": False}
    assert compact_args(schema) == ("url* (string) matching ^https?://[^ ]+$; browser (chrome|edge): Only if named.; "
                                    "minutes (integer 5-1440); others (list of string); loud (true|false)")
    assert compact_args({"type": "object", "properties": {}}) == "none"
    assert compact_args({"type": "object", "properties": {"n": {"type": "integer", "minimum": 1}}}) == "n (integer >= 1)"


def test_every_tool_keeps_its_argument_names_in_the_prompt():
    registry = default_registry(google=False)
    router = Router(registry, None)
    for tool in registry:
        for name in tool.args_schema.get("properties", {}):
            assert f"{name}" in router.system_prompt.split(f"- {tool.name}:", 1)[1].split("\n- ", 1)[0], (tool.name, name)


def test_the_prompt_is_much_shorter_than_with_the_full_schemas():
    registry = default_registry(google=True)
    compact = len(Router(registry, None).system_prompt)
    full = sum(len(json.dumps(t.args_schema, separators=(",", ":"))) + len(t.description) + len(t.name) + 20
               for t in registry)
    assert compact < full * 0.8, (compact, full)


def test_the_constraint_on_the_reply_is_still_the_full_schema():
    router = Router(default_registry(google=False), None)
    names = {o["properties"]["tool"]["const"] for o in router.schema["anyOf"]}
    assert "shutdown" in names and "none" in names
    shutdown = next(o for o in router.schema["anyOf"] if o["properties"]["tool"]["const"] == "shutdown")
    assert shutdown["properties"]["args"]["properties"]["minutes"]["maximum"] == 1440, "the safety limit stays enforced"

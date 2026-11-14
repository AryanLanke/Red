"""Write, explain and fix code (plan.md B2).

- write_code: Red writes the code into the chat window as it's generated, and
  says one line out loud ("Here you go, it's in the chat window") with what
  the code does. It never reads code aloud.
- explain_code / fix_code: the code on the clipboard (the default) or a file
  you name. A fix goes into the chat window; the file itself is never changed.

Red never runs code, including the code it writes (plan.md Rules). Python is
checked with compile(), which only parses it, so Red can say honestly when it
wrote something broken. Without a chat window (typed mode, overlay off), the
code is saved as a new file in Documents\\Red Code, never over an old one.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from red.chat_window import EXTENSIONS, code_filename, red_code_folder
from red.llm import LLMError, complete
from red.speech import JsonFieldReader
from red.tools.assistant import _UsesLLM, ask_model, spoken
from red.tools.base import ToolError

MAX_CODE = 12_000               # characters
MAX_SOURCE = 200_000            # bytes of a file to explain or fix
CODE_TOKENS = 2_400

WRITE_SYSTEM = """You are Red, the user's programmer friend. Write the code they ask for.
- Complete, working code in one file, with a few short comments where they help. Keep it under about 100 lines.
- Use only the standard library unless they name a package. Default to Python on Windows.
- The code must do exactly what they asked and nothing hidden. Don't delete files, send data anywhere or change system settings unless that is exactly what they asked for; prefer a dry run or asking first in the code when files get renamed or moved.
- language: the language in lower case (python, powershell, javascript, html...).
- summary: one short spoken sentence saying what the code does. No code, symbols or file paths in it.
Reply with JSON only: {"language": "...", "summary": "...", "code": "..."}"""

FIX_SYSTEM = """You are Red, the user's programmer friend. Fix the code below: find what's wrong (bugs, errors, the thing they describe) and return the whole corrected code.
- Change only what's needed, and keep their style.
- language: the language in lower case.
- summary: one or two short spoken sentences on what was wrong and what you changed. No code or symbols in it.
Reply with JSON only: {"language": "...", "summary": "...", "code": "..."}"""

EXPLAIN_SYSTEM = """You are Red, the user's programmer friend. Explain the code below out loud in 2 to 4 short spoken sentences: what it does, how, and anything risky or odd about it. No code, symbols, lists or markdown; say names in plain words.
Reply with JSON only: {"answer": "<your explanation>"}"""

CODE_SCHEMA = {
    "type": "object",
    "properties": {
        "language": {"type": "string", "maxLength": 30},
        "summary": {"type": "string", "minLength": 1, "maxLength": 300},
        "code": {"type": "string", "minLength": 1, "maxLength": MAX_CODE},
    },
    "required": ["language", "summary", "code"],
    "additionalProperties": False,
}

CREATIVE_SYSTEM = """You are Red, the user's witty friend. Write what they ask for (a poem, a story, a joke, a toast...), short enough to say out loud in under a minute, in plain spoken English. No markdown, lists or emoji.
Reply with JSON only: {"answer": "<what you wrote>"}"""

_NOT_CODE = re.compile(r"\b(?:poem|poetry|story|stories|song|lyrics|rap|essay|haiku|joke|limerick|"
                       r"letter|speech|toast|message|tweet|caption|riddle)\b", re.I)
_CODE_WORDS = re.compile(r"\b(?:code|script|program|function|class|app|html|css|python|powershell|"
                         r"javascript|regex|sql|bash|batch|json|api)\b", re.I)

_FENCED = re.compile(r"^\s*```[\w+#.-]*\s*\n(.*?)\n?```\s*$", re.S)
_LANG = re.compile(r'"language"\s*:\s*"([^"]{0,30})"')


def strip_fences(code: str) -> str:
    m = _FENCED.match(code)
    return m.group(1) if m else code.strip("\n")


def syntax_problem(code: str, language: str) -> str:
    """For Python: where it doesn't parse (compile() only parses; nothing runs)."""
    if language not in ("python", "py", ""):
        return ""
    try:
        compile(code, "<red>", "exec", dont_inherit=True)
    except SyntaxError as e:
        return f"line {e.lineno}: {e.msg}"
    except (ValueError, OverflowError) as e:
        return str(e)
    return ""


def fenced(language: str, code: str) -> str:
    return f"```{language}\n{code}\n```"


_NAME_FILLER = frozenset(
    "a an the for me that which who in on of to and with my your please can could would will you i we "
    "want need like said say write wrote make create build give code coding program script function "
    "app language simple small quick some just ok okay skip thing this it is be so now".split())
_NAME_FILLER_LANGS = frozenset(EXTENSIONS) | {"py", "js", "ps", "ps1", "c", "cpp"}

NEXT_STEPS = {
    "python": "Run it with Python, or tell me what to change.",
    "powershell": "Run it in PowerShell, or tell me what to change.",
    "javascript": "Run it with Node, or tell me what to change.",
    "html": "Open it in your browser, or tell me what to change.",
}


def next_step(language: str) -> str:
    """What to do with the code now, in one spoken sentence."""
    return NEXT_STEPS.get(language, "Tell me if you want anything changed.")


def file_name_for(request: str, language: str) -> str:
    """A file name from what the code does: "adds two binary numbers" -> adds-two-binary-numbers.py."""
    words = [w for w in re.findall(r"[a-z0-9]+", (request or "").lower())
             if w not in _NAME_FILLER and w not in _NAME_FILLER_LANGS]
    if not words:
        return code_filename(language)
    stem = "-".join(words[:4])[:40].strip("-")
    return code_filename(language).replace("red-code", stem, 1)


def free_path(folder: Path, name: str) -> Path:
    """folder/name, or name-2, name-3... so an old file is never replaced."""
    path = folder / name
    stem, suffix = path.stem, path.suffix
    n = 2
    while path.exists():
        path = folder / f"{stem}-{n}{suffix}"
        n += 1
    return path


def read_clipboard() -> str:
    """The text on the Windows clipboard (read-only, user32)."""
    import ctypes
    from ctypes import wintypes
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.GetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
    kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]
    if not user32.OpenClipboard(None):
        raise ToolError("Another app is holding the clipboard. Try again in a second.")
    try:
        handle = user32.GetClipboardData(13)             # CF_UNICODETEXT
        if not handle:
            return ""
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            return ""
        try:
            return ctypes.wstring_at(pointer)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def search_folders() -> list[Path]:
    from red.known_folders import known_folder
    folders = [red_code_folder()]
    for name in ("documents", "desktop", "downloads"):
        try:
            folder = known_folder(name)
        except Exception:  # noqa: BLE001
            folder = None
        if folder is not None:
            folders.append(folder)
    return folders


_CLIPBOARD = re.compile(r"^(?:|clipboard|the clipboard|what i copied|this|that|it|this code|the code|"
                        r"my code|copied|copied code|what's copied)$", re.I)


class _CodeTool(_UsesLLM):
    """Shared: the chat window, where the code comes from, and the model's code reply."""

    read_clipboard = staticmethod(read_clipboard)
    folders = staticmethod(search_folders)

    def __init__(self, llm=None):
        super().__init__(llm)
        self._chat = None
        self.last_details = ""

    def bind_chat(self, ui) -> None:
        """Called by red.chat_window: the ChatUI to write into."""
        self._chat = ui

    def source(self, where: str) -> tuple[str, str]:
        """(the code, where it came from): the clipboard, or a file the user named."""
        where = " ".join((where or "").split()).strip(" .?!\"'")
        if _CLIPBOARD.match(where):
            text = self.read_clipboard() or ""
            if not text.strip():
                raise ToolError("Your clipboard is empty. Copy the code first.")
            return text[:MAX_CODE * 2], "your clipboard"
        name = Path(where)
        candidates = [name] if name.is_absolute() else [folder / name for folder in self.folders()]
        for path in candidates:
            try:
                if path.is_file():
                    if path.stat().st_size > MAX_SOURCE:
                        raise ToolError(f"{path.name} is too big for me to read in one go.")
                    return path.read_text(encoding="utf-8", errors="replace"), path.name
            except OSError:
                continue
        raise ToolError(f"I couldn't find {where}. Copy the code, or give me the full path.")

    def ask_for_code(self, system: str, prompt: str, stream=None) -> dict:
        """The model's {"language", "summary", "code"}; streamed into `stream` when there is one."""
        if self._llm is None:
            raise ToolError("I need the local model for code, and it isn't connected.")
        raw = ""
        try:
            if stream is not None and hasattr(self._llm, "stream_json"):
                reader = JsonFieldReader("code")
                code = ""
                pieces = self._llm.stream_json(system, prompt, CODE_SCHEMA, temperature=0.2,
                                               max_tokens=CODE_TOKENS)
                try:
                    for piece in pieces:
                        raw += piece
                        code += reader.feed(piece)
                        if code:
                            m = _LANG.search(raw)
                            stream.set(fenced(m.group(1).lower() if m else "", code))
                finally:
                    close = getattr(pieces, "close", None)
                    if close:
                        close()
            else:
                raw = complete(self._llm, system, prompt, CODE_SCHEMA, temperature=0.2,
                               max_tokens=CODE_TOKENS)
            data = json.loads(raw)
        except LLMError as e:
            raise ToolError("The local model didn't answer. Try again in a moment.") from e
        except (ValueError, TypeError) as e:
            raise ToolError("The code came out garbled. Try asking again.") from e
        code = strip_fences(str(data.get("code", "")))
        if not code.strip():
            raise ToolError("I came up empty on that one. Try saying it another way?")
        language = re.sub(r"[^a-z0-9+#.-]", "", str(data.get("language", "")).lower())[:20] or "python"
        summary = spoken(str(data.get("summary", "")), max_sentences=2, max_chars=300)
        return {"language": language, "summary": summary, "code": code}

    def show(self, result: dict, stream, note: str = "") -> str:
        """Put the code in the window (or a new file). Returns where it went, for the reply."""
        text = f"{result['summary']}{(' ' + note) if note else ''}\n{fenced(result['language'], result['code'])}"
        self.last_details = ""
        if stream is not None:
            stream.done(text)
            return "it's in the chat window"
        path = self.save(result)
        self.last_details = fenced(result["language"], result["code"])
        return f"I saved it as {path.name} in Documents, Red Code"

    def save(self, result: dict, name: str = "") -> Path:
        """The code as a new file in Documents\\Red Code (never over an old one)."""
        folder = red_code_folder()
        try:
            folder.mkdir(parents=True, exist_ok=True)
            path = free_path(folder, name or code_filename(result["language"]))
            path.write_text(result["code"] + "\n", encoding="utf-8")
        except OSError as e:
            raise ToolError(f"I wrote it, but couldn't save it: {e}") from e
        return path

    def open_stream(self, first: str):
        if self._chat is None:
            return None
        try:
            self._chat.show()
            stream = self._chat.stream()
            stream.set(first)
            return stream
        except Exception:  # noqa: BLE001 - fall back to saving a file
            return None


class WriteCode(_CodeTool):
    name = "write_code"
    description = ("Write program code the user asks for (a script, a function, a web page), shown in "
                   "Red's chat window and never run: 'write me a Python script that renames my photos "
                   "by date', 'make a PowerShell script to list big files', 'code a function that "
                   "checks primes'. Only code: a poem, story, message or mail is not code. Not for "
                   "explaining or fixing existing code.")
    args_schema = {
        "type": "object",
        "properties": {
            "request": {"type": "string", "minLength": 3, "maxLength": 500,
                        "description": "What the code should do, in the user's words."},
            "language": {"type": "string", "maxLength": 30,
                         "description": "The language if they named one, else empty."},
        },
        "required": ["request"],
        "additionalProperties": False,
    }
    max_reply = 600

    def run(self, request: str, language: str = "") -> str:
        said = self._command or request
        self._command = ""
        if _NOT_CODE.search(said) and not _CODE_WORDS.search(said) and not language.strip():
            # "write me a poem": the router sent words, not code. Say it like a friend would.
            return ask_model(self._llm, CREATIVE_SYSTEM, said)
        prompt = f"Write this{f' in {language}' if language else ''}: {said}"
        stream = self.open_stream("Writing it...")
        result = self.ask_for_code(WRITE_SYSTEM, prompt, stream)
        problem = syntax_problem(result["code"], result["language"])
        note = f" (It doesn't parse yet, {problem}. Say \"fix this\" after copying it.)" if problem else ""
        code_block = fenced(result["language"], result["code"])
        # What it did and where it is (plan.md 1, Act): always a file too, so the code has a real place.
        try:
            path = self.save(result, file_name_for(said, result["language"]))
        except ToolError:
            if stream is None:
                raise
            path = None
        self.last_details = ""
        if stream is not None:
            stream.done(f"{result['summary']}{note}\n{code_block}" + (f"\nSaved as {path}" if path else ""))
            where = (f"it's in the chat window and saved as {path.name} in Documents, Red Code" if path
                     else "it's in the chat window. I couldn't save a copy")
        else:
            self.last_details = code_block
            where = f"I saved it as {path.name} in Documents, Red Code"
        reply = f"Done, {where}. {result['summary']}".strip()
        if problem:
            reply += " Heads up, it has a syntax error, so copy it and say fix this."
        else:
            reply += " " + next_step(result["language"])
        return reply


class FixCode(_CodeTool):
    name = "fix_code"
    description = ("Fix code the user copied or names. 'fix this', 'fix it', 'debug this', 'fix the "
                   "code I copied', 'why doesn't this work' all mean the clipboard; 'fix rename.py' "
                   "means that file. The fixed code goes into the chat window; the file isn't changed.")
    args_schema = {
        "type": "object",
        "properties": {
            "source": {"type": "string", "maxLength": 200,
                       "description": "'clipboard', or the file name they said."},
            "problem": {"type": "string", "maxLength": 300,
                        "description": "What's wrong, if they said."},
        },
        "required": [],
        "additionalProperties": False,
    }
    max_reply = 600

    def run(self, source: str = "clipboard", problem: str = "") -> str:
        self._command = ""
        code, where = self.source(source)
        stream = self.open_stream(f"Looking at the code from {where}...")
        prompt = (f"The problem: {problem}\n\n" if problem else "") + f"The code:\n{code}"
        result = self.ask_for_code(FIX_SYSTEM, prompt, stream)
        place = self.show(result, stream)
        return f"Fixed version, {place}. {result['summary']}".strip()


class ExplainCode(_CodeTool):
    name = "explain_code"
    description = ("Explain code out loud: what's on the clipboard ('explain this code', 'what does "
                   "this do', 'explain what I copied') or a file they name ('explain rename.py').")
    args_schema = {
        "type": "object",
        "properties": {"source": {"type": "string", "maxLength": 200,
                                  "description": "'clipboard', or the file name they said."}},
        "required": [],
        "additionalProperties": False,
    }

    def run(self, source: str = "clipboard") -> str:
        self._command = ""
        code, where = self.source(source)
        return ask_model(self._llm, EXPLAIN_SYSTEM, f"The code (from {where}):\n{code[:MAX_CODE]}")

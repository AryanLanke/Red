# AGENTS.md

Red is a local, offline voice and action assistant for Windows. A local LLM turns a command into one JSON tool call, and Red validates it before anything runs.

- [progress.md](progress.md) is the developer document: status, specs, decisions, open questions, and the parallel-sessions plan (section 8). Follow its specs and safety rules when building a feature, and keep its status up to date.
- [README.md](README.md) is for users. Keep it free of developer planning.

**Status:** Day 1 is done: config, LLM backends, the tool interface and the router. Every tool's `run()` still raises `NotImplementedError`, and `python -m red` only shows tool calls; it never runs them. Days 2 to 5 are planned as three parallel tracks (A, B, C) in separate git worktrees under `D:\RED\worktrees\`. If you are one of those sessions, progress.md section 8 decides which files you may edit.

## Commands

Windows and PowerShell only. Python 3.11 or newer.

On this machine `RED_HOME` is `D:\RED`, the venv is `D:\RED\.venv`, and the repo is `D:\RED\red`. Set `$env:RED_HOME = "D:\RED"` first; otherwise Red uses `%LOCALAPPDATA%\Red` and downloads a second copy of Ollama and the model (about 6 GB).

```powershell
pip install -r requirements-dev.txt
python -m pytest --basetemp="$env:RED_HOME\cache\pytest-tmp"            # unit tests (integration tests are skipped)
python -m pytest tests\test_router.py::test_shutdown_is_destructive    # one test
$env:RED_INTEGRATION = "1"; python -m pytest tests\test_integration_llm.py   # real model, slow

python -m red setup                   # download and start the Ollama backend and the model
python -m red route "open Downloads"  # print the tool call for one command
python -m red                         # interactive loop (dry run)
```

There is no build step, linter or formatter set up. Dependencies are pinned exactly in `requirements*.txt`.

## Architecture

The flow in `red/__main__.py`: `load_settings()` → `llm.connect(settings)` → `Router(default_registry(), llm)` → `router.route(text)` → `Route(tool, args, destructive)`.

- **Tools** (`red/tools/`): each one subclasses `Tool` and has `name`, `description`, `args_schema` and `destructive`. Register it in `default_registry()` in `tools/__init__.py`. The `description` and `args_schema` are inserted directly into the LLM's system prompt, so their wording changes routing. The schema bounds are also the safety limits; for example, `MAX_DELAY_MINUTES` caps shutdown delays. `none` is a reserved pseudo-tool for "no tool fits" (its args are `{"reply": ...}`), and the registry rejects a tool with that name.
- **Router** (`red/router.py`): builds an `anyOf` JSON schema from the registry. The backend uses it to constrain generation, and `Router.parse()` checks it again with `jsonschema`, because a server may ignore the schema. `parse()` needs no LLM, so most router tests call it directly.
- **LLM backends** (`red/llm.py`): every client implements the `LLM` protocol (`complete_json(system, user, schema) -> str`). `connect()` tries them in this order:
  1. `RED_LLM_URL` (any OpenAI-compatible server)
  2. An Ollama already running on `127.0.0.1:11434`
  3. Red's own pinned Ollama
  4. With `RED_LLM_BACKEND=auto`, a llama.cpp `llama-server` as a fallback

  Ollama receives the schema as `format`. OpenAI-compatible servers receive it as `response_format` json_schema. Model names map to an Ollama tag and Hugging Face GGUF files in `MODELS`.
- **Pinned downloads** (`red/llm.py` and `red/downloads.py`): every binary and GGUF is pinned to a version and a SHA-256. If you change a version, update its hash. A download is written to `.part` and moved to its final path only after the checksum matches, so an existing file there is always verified. Installs write an `.installed` marker. Zips go through `safe_extract`, which blocks paths that would escape the target folder.
- **Child servers** (`red/process.py`): `ManagedServer` starts a backend inside a Windows Job Object set to kill on close, so Ollama and its model runner die with Red, even after a crash. Whoever calls `connect()` owns the returned server and must `stop()` it in a `finally` block.
- **Config** (`red/config.py`): all paths come from `Settings`, which is built on `RED_HOME`. Never hard-code a path. Environment variables win over `RED_HOME\config\.env`. `RED_HOME` itself is only read from the environment.

## Rules that come from the design

- A tool must never pass LLM text to a shell or command line. App and folder names are only lookup keys into Windows' standard folders or `RED_HOME\config\allowlist.toml`. If nothing matches, say so instead of guessing.
- `destructive = True` tools (shutdown, restart, anything that changes files) must get a typed `y`/`yes` before they run. Anything else, or 30 seconds with no answer, cancels. `cancel_shutdown` never asks.
- Tests must never open windows or schedule a real shutdown. Inject a fake runner, as the README's Day 2 section describes. Follow the existing test patterns:
  - `FakeLLM` in `tests/test_router.py`
  - `monkeypatch` to clear `RED_*` variables, with `load_settings(tmp_path)`
  - `monkeypatch` on `llm.start_ollama` / `llm.start_llama_server`
- Red never calls a cloud model. Trading and financial automation are out of scope.
- Windows Smart App Control blocks unsigned binaries. Exit code `0xC0E90002` from llama-server means it was blocked; Ollama is the default for this reason.

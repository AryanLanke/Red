"""Repo sync check: compare local Git repos with their remotes. Read-only.

The repos come from RED_HOME\\config\\repos.toml (copy repos.example.toml):

    [repos]
    red = 'D:\\RED\\red'

For each repo Red runs `git fetch`, `git status`, `git log @{u}..HEAD` and
`git log HEAD..@{u}`, and reports it as clean, ahead, behind or dirty. It
also reports a missing folder, no upstream branch, a detached HEAD and a
failed fetch instead of skipping the repo.

It never pulls, pushes, commits, checks out or changes files. Git runs with
prompts turned off and a timeout, so a credentials prompt can't hang Red.
The model's text is only a lookup key into repos.toml, never a path.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import tomllib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..config import red_home
from .base import Tool

log = logging.getLogger(__name__)

GIT_TIMEOUT = 15.0      # seconds for local commands
FETCH_TIMEOUT = 45.0    # seconds for `git fetch`
MAX_PARALLEL = 4
MAX_SPOKEN_REPOS = 3    # name at most this many repos in the spoken reply

# The only git subcommands this tool may run. Tests check every call against it.
READ_ONLY_COMMANDS = frozenset({"rev-parse", "symbolic-ref", "fetch", "status", "log"})

# Config for every call: no background gc or maintenance, no credential UI.
_GIT_PREFIX = ["git", "-c", "gc.auto=0", "-c", "maintenance.auto=false",
               "-c", "credential.interactive=never", "-c", "fetch.recurseSubmodules=false"]

_GIT_ENV = {
    "GIT_TERMINAL_PROMPT": "0",        # never ask for a username or password
    "GCM_INTERACTIVE": "never",        # Git Credential Manager: fail instead of a login window
    "GIT_ASKPASS": "echo",             # any remaining prompt gets an empty answer
    "SSH_ASKPASS_REQUIRE": "never",
    "GIT_OPTIONAL_LOCKS": "0",         # `git status` won't rewrite the index
    "LC_ALL": "C",                     # English messages for the details
}


@dataclass(frozen=True)
class GitResult:
    returncode: int
    stdout: str
    stderr: str


class GitTimeout(Exception):
    pass


class GitMissing(Exception):
    pass


GitRunner = Callable[[list[str], Path, float], GitResult]


def _kill_tree(proc: subprocess.Popen) -> None:
    """End git and anything it started (ssh, git-remote-https, credential helpers)."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    proc.kill()


def run_git(args: list[str], cwd: Path, timeout: float) -> GitResult:
    """Run one git command with prompts off. Raises GitTimeout or GitMissing."""
    try:
        proc = subprocess.Popen(
            _GIT_PREFIX + list(args), cwd=cwd, env=dict(os.environ, **_GIT_ENV),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except FileNotFoundError as e:
        raise GitMissing("git isn't installed or isn't on PATH") from e
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        proc.communicate()
        raise GitTimeout(f"git {args[0]} took longer than {timeout:g} seconds") from None
    return GitResult(proc.returncode, out, err)


# --------------------------------------------------------------------------
# Checking one repo
# --------------------------------------------------------------------------

@dataclass
class RepoStatus:
    name: str
    path: Path
    problem: str | None = None        # missing, not_a_repo, error
    error: str = ""
    branch: str | None = None         # None when detached
    upstream: str | None = None       # None when there is no upstream branch
    changes: int = 0                  # uncommitted files, including untracked
    ahead: list[str] = field(default_factory=list)    # local commits not pushed
    behind: list[str] = field(default_factory=list)   # remote commits not pulled
    fetch_error: str | None = None

    @property
    def detached(self) -> bool:
        return self.problem is None and self.branch is None

    @property
    def no_upstream(self) -> bool:
        return self.problem is None and self.branch is not None and self.upstream is None

    @property
    def state(self) -> str:
        """One word: clean, ahead, behind, diverged, dirty, detached, no_upstream,
        fetch_failed, missing, not_a_repo or error. Dirty wins over ahead/behind."""
        if self.problem:
            return self.problem
        if self.changes:
            return "dirty"
        if self.detached:
            return "detached"
        if self.no_upstream:
            return "no_upstream"
        if self.ahead and self.behind:
            return "diverged"
        if self.ahead:
            return "ahead"
        if self.behind:
            return "behind"
        if self.fetch_error:
            return "fetch_failed"
        return "clean"

    @property
    def is_clean(self) -> bool:
        return self.state == "clean"

    def spoken(self) -> str:
        """'red has 2 unpushed commits and uncommitted changes'."""
        if self.problem == "missing":
            return f"{self.name}'s folder is missing"
        if self.problem == "not_a_repo":
            return f"{self.name} isn't a Git repo"
        if self.problem:
            return f"{self.name} couldn't be checked"
        parts = []
        if self.ahead:
            parts.append(f"has {_count(len(self.ahead), 'unpushed commit')}")
        if self.behind:
            parts.append(f"is {_count(len(self.behind), 'commit')} behind")
        if self.changes:
            parts.append("has uncommitted changes")
        if self.detached:
            parts.append("is on a detached HEAD")
        if self.no_upstream:
            parts.append("has no upstream branch")
        if self.fetch_error:
            parts.append("couldn't fetch from its remote")
        if not parts:
            return f"{self.name} is clean"
        if len(parts) > 1:
            parts[-1] = "and " + parts[-1]
        return f"{self.name} " + (" " if len(parts) == 2 else ", ").join(parts)

    def detail(self) -> str:
        """One line for the overlay and the log."""
        if self.problem == "missing":
            return f"{self.name}: folder not found ({self.path})"
        if self.problem == "not_a_repo":
            return f"{self.name}: not a Git repo ({self.path})"
        if self.problem:
            return f"{self.name}: couldn't check ({self.error})"
        where = self.branch or "detached HEAD"
        if self.upstream:
            where += f" -> {self.upstream}"
        bits = []
        if self.ahead:
            bits.append(f"{len(self.ahead)} to push")
        if self.behind:
            bits.append(f"{len(self.behind)} to pull")
        if self.changes:
            bits.append(_count(self.changes, "changed file"))
        if self.no_upstream:
            bits.append("no upstream")
        if self.fetch_error:
            bits.append(f"fetch failed: {self.fetch_error}")
        return f"{self.name} ({where}): {', '.join(bits) or 'clean'}"


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def _first_line(text: str, limit: int = 120) -> str:
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    # Prefer git's "fatal:"/"error:" line over hints and progress.
    pick = next((ln for ln in lines if re.match(r"(fatal|error):", ln)), lines[0] if lines else "")
    pick = re.sub(r"^(fatal|error):\s*", "", pick)
    return pick[:limit] or "unknown error"


def check_repo(name: str, path: Path, runner: GitRunner = run_git,
               timeout: float = GIT_TIMEOUT, fetch_timeout: float = FETCH_TIMEOUT) -> RepoStatus:
    """Check one repo without changing it. GitMissing propagates to the caller."""
    status = RepoStatus(name=name, path=path)
    if not path.is_dir():
        status.problem = "missing"
        return status

    def git(*args: str, t: float = timeout) -> GitResult:
        return runner(list(args), path, t)

    try:
        top = git("rev-parse", "--is-inside-work-tree")
        if top.returncode != 0 or top.stdout.strip() != "true":
            status.problem = "not_a_repo"
            return status

        branch = git("symbolic-ref", "--quiet", "--short", "HEAD")
        status.branch = branch.stdout.strip() if branch.returncode == 0 else None

        if status.branch:
            up = git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
            status.upstream = up.stdout.strip() if up.returncode == 0 else None

        # 1. fetch, only when there's something to compare with
        if status.upstream:
            try:
                fetched = git("fetch", "--quiet", "--no-tags", "--no-write-fetch-head",
                              t=fetch_timeout)
                if fetched.returncode != 0:
                    status.fetch_error = _first_line(fetched.stderr)
            except GitTimeout:
                status.fetch_error = f"timed out after {fetch_timeout:g} seconds"

        # 2. uncommitted changes
        st = git("status", "--porcelain=v1", "--untracked-files=normal")
        if st.returncode != 0:
            raise RuntimeError(_first_line(st.stderr))
        status.changes = sum(1 for ln in st.stdout.splitlines() if ln.strip())

        # 3 and 4. commits to push and to pull
        if status.upstream:
            for attr, spec in (("ahead", "@{u}..HEAD"), ("behind", "HEAD..@{u}")):
                out = git("log", "--format=%h %s", spec)
                if out.returncode != 0:
                    raise RuntimeError(_first_line(out.stderr))
                setattr(status, attr, [ln for ln in out.stdout.splitlines() if ln.strip()])
    except GitTimeout as e:
        status.problem, status.error = "error", str(e)
    except (RuntimeError, OSError) as e:
        status.problem, status.error = "error", str(e)
    return status


# --------------------------------------------------------------------------
# repos.toml
# --------------------------------------------------------------------------

class ReposConfigError(ValueError):
    pass


def repos_file() -> Path:
    return red_home() / "config" / "repos.toml"


def load_repos(path: Path) -> dict[str, Path]:
    """Return {name: folder} in file order. Relative folders are relative to the file."""
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ReposConfigError(f"{path.name} has a syntax error: {e}") from e
    table = data.get("repos", {})
    if not isinstance(table, dict):
        raise ReposConfigError(f"{path.name}: [repos] must be a table of name = 'folder'")
    repos = {}
    for name, folder in table.items():
        if not isinstance(folder, str) or not folder.strip():
            raise ReposConfigError(f"{path.name}: repo {name!r} needs a folder path in quotes")
        p = Path(os.path.expandvars(folder.strip())).expanduser()
        repos[str(name)] = p if p.is_absolute() else (path.parent / p)
    return repos


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


# Values that mean "every repo". The model tends to fill the optional repo
# with one of these instead of leaving it out.
_ALL_REPOS = frozenset(_key(v) for v in (
    "all", "any", "every", "everything", "none", "null", "nil", "undefined", "n/a", "*",
    "repos", "repo", "my repos", "all repos", "all my repos", "repositories",
    "all repositories", "my repositories", "git", "github",
))


def means_all_repos(repo: str | None) -> bool:
    return not repo or _key(repo) in _ALL_REPOS or not _key(repo)


# --------------------------------------------------------------------------
# Tool
# --------------------------------------------------------------------------

class CheckRepos(Tool):
    name = "check_repos"
    description = ("Check the user's local Git repos against GitHub and report which have "
                   "unpushed commits, are behind, or have uncommitted changes. Read-only.")
    args_schema = {
        "type": "object",
        "properties": {"repo": {
            "type": "string", "minLength": 1, "maxLength": 100,
            "description": "The repo name the user said, or \"all\" to check every repo."}},
        "additionalProperties": False,
    }

    def __init__(self, runner: GitRunner = run_git, config: Callable[[], Path] = repos_file,
                 timeout: float = GIT_TIMEOUT, fetch_timeout: float = FETCH_TIMEOUT,
                 parallel: int = MAX_PARALLEL):
        self._runner = runner
        self._config = config
        self._timeout = timeout
        self._fetch_timeout = fetch_timeout
        self._parallel = parallel
        # Set by run(), for the overlay and the command log.
        self.last_results: list[RepoStatus] = []
        self.last_details: str = ""

    def run(self, repo: str | None = None) -> str:
        self.last_results, self.last_details = [], ""
        path = self._config()
        if not path.is_file():
            return (f"No repos are set up yet. List them in {path}, "
                    "following repos.example.toml.")
        try:
            repos = load_repos(path)
        except (ReposConfigError, OSError) as e:
            return f"I couldn't read the repo list: {e}"
        if not repos:
            return f"Your repo list is empty. Add repos to {path}."

        if not means_all_repos(repo):
            wanted = {_key(n): n for n in repos}
            match = wanted.get(_key(repo))
            if match is None:
                known = ", ".join(list(repos)[:5])
                return f"I don't have a repo called {repo}. Your repos are {known}."
            repos = {match: repos[match]}

        try:
            with ThreadPoolExecutor(max_workers=max(1, min(self._parallel, len(repos)))) as pool:
                results = list(pool.map(
                    lambda item: check_repo(item[0], item[1], self._runner,
                                            self._timeout, self._fetch_timeout),
                    repos.items()))
        except GitMissing:
            return "Git isn't installed or isn't on PATH, so I can't check your repos."

        self.last_results = results
        self.last_details = "\n".join(r.detail() for r in results)
        for r in results:
            log.info("repo %s: %s", r.state, r.detail())
            for direction in ("ahead", "behind"):
                for commit in getattr(r, direction):
                    log.info("  %s %s: %s", r.name, direction, commit)
        return summarize(results)


def summarize(results: list[RepoStatus]) -> str:
    """The short spoken reply."""
    total = len(results)
    attention = [r for r in results if not r.is_clean]
    if not attention:
        if total == 1:
            return f"{results[0].name} is clean and up to date."
        return f"All {total} repos are clean and up to date."
    named = "; ".join(r.spoken() for r in attention[:MAX_SPOKEN_REPOS])
    more = len(attention) - MAX_SPOKEN_REPOS
    if more > 0:
        named += f"; and {more} more"
    if total == 1:
        return named + "."
    return f"{len(attention)} of {total} repos need attention: {named}."

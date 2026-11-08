"""Repo sync tests. Real git runs only against temporary repos made here, with a
local bare repo as the "remote", so nothing touches the network or real repos."""

import shutil
import subprocess
from pathlib import Path

import pytest

from red.tools import git_sync
from red.tools.git_sync import (CheckRepos, GitMissing, GitResult, GitTimeout, RepoStatus,
                                check_repo, load_repos, run_git, summarize)

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


@pytest.fixture(autouse=True)
def isolated_git(monkeypatch, tmp_path):
    """Keep the user's git config (signing, hooks, helpers) out of the tests."""
    empty = tmp_path / "gitconfig"
    empty.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for var in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{var}_NAME", "Red Test")
        monkeypatch.setenv(f"GIT_{var}_EMAIL", "red@example.invalid")


def git(cwd, *args):
    out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return out.stdout.strip()


def commit(repo, name, text="x"):
    (repo / name).write_text(text)
    git(repo, "add", name)
    git(repo, "commit", "-q", "-m", f"add {name}")


@pytest.fixture
def remote(tmp_path):
    """A bare 'GitHub' repo with one commit on main."""
    bare = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    seed = tmp_path / "seed"
    git(tmp_path, "clone", "-q", str(bare), str(seed))
    git(seed, "checkout", "-q", "-b", "main")
    commit(seed, "README.md")
    git(seed, "push", "-q", "origin", "main")
    return bare


@pytest.fixture
def clone(tmp_path, remote):
    def make(name):
        path = tmp_path / name
        git(tmp_path, "clone", "-q", str(remote), str(path))
        return path
    return make


def push_from_elsewhere(tmp_path, remote, filename):
    other = tmp_path / f"other-{filename}"
    git(tmp_path, "clone", "-q", str(remote), str(other))
    commit(other, filename)
    git(other, "push", "-q", "origin", "main")


def snapshot(repo):
    """Everything a check must not change."""
    return (git(repo, "rev-parse", "HEAD"), git(repo, "status", "--porcelain=v1"),
            git(repo, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads"),
            sorted(p.name for p in repo.iterdir()))


# --- real repos -----------------------------------------------------------------

def test_clean(clone):
    repo = clone("clean")
    s = check_repo("clean", repo)
    assert s.state == "clean" and s.branch == "main" and s.upstream == "origin/main"
    assert s.spoken() == "clean is clean"
    assert s.detail() == "clean (main -> origin/main): clean"


def test_ahead(clone):
    repo = clone("ahead")
    commit(repo, "a.txt")
    commit(repo, "b.txt")
    s = check_repo("ahead", repo)
    assert s.state == "ahead" and len(s.ahead) == 2 and s.behind == []
    assert s.ahead[0].endswith("add b.txt")
    assert s.spoken() == "ahead has 2 unpushed commits"


def test_behind_is_found_by_fetch_and_not_pulled(tmp_path, remote, clone):
    repo = clone("behind")
    push_from_elsewhere(tmp_path, remote, "new.txt")
    before = snapshot(repo)
    s = check_repo("behind", repo)
    assert s.state == "behind" and len(s.behind) == 1
    assert s.spoken() == "behind is 1 commit behind"
    assert snapshot(repo) == before
    assert not (repo / "new.txt").exists()


def test_diverged(tmp_path, remote, clone):
    repo = clone("diverged")
    commit(repo, "mine.txt")
    push_from_elsewhere(tmp_path, remote, "theirs.txt")
    s = check_repo("diverged", repo)
    assert s.state == "diverged" and len(s.ahead) == 1 and len(s.behind) == 1
    assert s.spoken() == "diverged has 1 unpushed commit and is 1 commit behind"


def test_dirty(clone):
    repo = clone("dirty")
    (repo / "README.md").write_text("changed")
    (repo / "untracked.txt").write_text("new")
    before = snapshot(repo)
    s = check_repo("dirty", repo)
    assert s.state == "dirty" and s.changes == 2
    assert s.spoken() == "dirty has uncommitted changes"
    assert "2 changed files" in s.detail()
    assert snapshot(repo) == before


def test_no_upstream(clone):
    repo = clone("noup")
    git(repo, "checkout", "-q", "-b", "feature")
    s = check_repo("noup", repo)
    assert s.state == "no_upstream" and s.branch == "feature" and s.upstream is None
    assert s.spoken() == "noup has no upstream branch"


def test_detached_head(clone):
    repo = clone("detached")
    git(repo, "checkout", "-q", "--detach")
    s = check_repo("detached", repo)
    assert s.state == "detached" and s.branch is None
    assert s.spoken() == "detached is on a detached HEAD"
    assert "detached HEAD" in s.detail()


def test_fetch_failure_is_reported(tmp_path, clone):
    repo = clone("offline")
    commit(repo, "local.txt")
    git(repo, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    s = check_repo("offline", repo)
    assert s.fetch_error and s.problem is None
    assert len(s.ahead) == 1                    # still compared with the last fetch
    assert s.spoken() == "offline has 1 unpushed commit and couldn't fetch from its remote"
    assert "fetch failed" in s.detail()


def test_fetch_failure_on_a_clean_repo(tmp_path, clone):
    repo = clone("offline2")
    git(repo, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    s = check_repo("offline2", repo)
    assert s.state == "fetch_failed" and not s.is_clean


def test_new_repo_without_commits(tmp_path):
    repo = tmp_path / "fresh"
    git(tmp_path, "init", "-q", "-b", "main", str(repo))
    assert check_repo("fresh", repo).state == "no_upstream"


def test_missing_folder_and_not_a_repo(tmp_path):
    assert check_repo("gone", tmp_path / "nope").state == "missing"
    plain = tmp_path / "plain"
    plain.mkdir()
    s = check_repo("plain", plain)
    assert s.state == "not_a_repo"
    assert s.spoken() == "plain isn't a Git repo"


def test_runs_only_read_only_commands(tmp_path, remote, clone):
    repo = clone("audit")
    commit(repo, "x.txt")
    (repo / "dirty.txt").write_text("d")
    calls = []

    def recording(args, cwd, timeout):
        calls.append(args)
        return run_git(args, cwd, timeout)

    check_repo("audit", repo, runner=recording)
    assert {a[0] for a in calls} <= git_sync.READ_ONLY_COMMANDS
    assert any(a[0] == "fetch" for a in calls)


def test_timeout_kills_git(tmp_path):
    with pytest.raises(GitTimeout):
        run_git(["-c", "alias.slow=!sleep 20", "slow"], tmp_path, timeout=1.0)


def test_git_env_turns_off_prompts(tmp_path):
    out = run_git(["-c", "alias.env=!env", "env"], tmp_path, timeout=10)
    assert "GIT_TERMINAL_PROMPT=0" in out.stdout
    assert "GCM_INTERACTIVE=never" in out.stdout


# --- the tool, end to end ------------------------------------------------------

def write_config(tmp_path, entries):
    cfg = tmp_path / "config" / "repos.toml"
    cfg.parent.mkdir(exist_ok=True)
    cfg.write_text("[repos]\n" + "".join(f"{k} = '{v}'\n" for k, v in entries.items()))
    return cfg


def test_tool_reports_every_repo(tmp_path, remote, clone):
    clean, ahead, dirty = clone("clean"), clone("ahead"), clone("dirty")
    commit(ahead, "a.txt")
    (dirty / "d.txt").write_text("d")
    cfg = write_config(tmp_path, {"clean": clean, "ahead": ahead, "dirty": dirty,
                                  "gone": tmp_path / "gone"})
    tool = CheckRepos(config=lambda: cfg)
    reply = tool.run()
    assert reply == ("3 of 4 repos need attention: ahead has 1 unpushed commit; "
                     "dirty has uncommitted changes; gone's folder is missing.")
    assert [r.state for r in tool.last_results] == ["clean", "ahead", "dirty", "missing"]
    assert tool.last_details.splitlines()[0] == "clean (main -> origin/main): clean"
    assert len(tool.last_details.splitlines()) == 4


def test_tool_one_named_repo(tmp_path, clone):
    a, b = clone("a"), clone("b")
    cfg = write_config(tmp_path, {"My-Site": a, "other": b})
    tool = CheckRepos(config=lambda: cfg)
    assert tool.run(repo="my site") == "My-Site is clean and up to date."
    assert len(tool.last_results) == 1
    assert tool.run(repo="nothing") == \
        "I don't have a repo called nothing. Your repos are My-Site, other."


def test_tool_all_clean(tmp_path, clone):
    cfg = write_config(tmp_path, {"a": clone("a"), "b": clone("b")})
    assert CheckRepos(config=lambda: cfg).run() == "All 2 repos are clean and up to date."


# --- config and replies, no git needed -----------------------------------------

def test_no_config_says_how_to_add_one(tmp_path):
    reply = CheckRepos(config=lambda: tmp_path / "repos.toml").run()
    assert reply.startswith("No repos are set up yet.") and "repos.example.toml" in reply


def test_bad_config(tmp_path):
    cfg = tmp_path / "repos.toml"
    cfg.write_text("[repos\n")
    assert CheckRepos(config=lambda: cfg).run().startswith("I couldn't read the repo list")
    cfg.write_text("[repos]\nx = 3\n")
    assert "needs a folder path" in CheckRepos(config=lambda: cfg).run()
    cfg.write_text("# nothing yet\n")
    assert CheckRepos(config=lambda: cfg).run().startswith("Your repo list is empty")


def test_load_repos_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("RED_TEST_DIR", str(tmp_path / "env"))
    cfg = tmp_path / "repos.toml"
    cfg.write_text("[repos]\nabs = 'C:\\x\\y'\nrel = 'sub\\dir'\n"
                   "env = '%RED_TEST_DIR%\\r'\n")
    repos = load_repos(cfg)
    assert list(repos) == ["abs", "rel", "env"]
    assert repos["abs"] == Path(r"C:\x\y")
    assert repos["rel"] == tmp_path / "sub" / "dir"
    assert repos["env"] == tmp_path / "env" / "r"


def test_example_file_parses():
    example = Path(__file__).resolve().parent.parent / "repos.example.toml"
    assert "red" in load_repos(example)


def test_default_config_is_under_red_home(monkeypatch, tmp_path):
    monkeypatch.setenv("RED_HOME", str(tmp_path))
    assert git_sync.repos_file() == tmp_path / "config" / "repos.toml"


def test_git_missing(tmp_path):
    def no_git(args, cwd, timeout):
        raise GitMissing("nope")

    cfg = write_config(tmp_path, {"a": tmp_path})
    assert CheckRepos(runner=no_git, config=lambda: cfg).run().startswith("Git isn't installed")


def test_timeout_on_a_local_command_is_an_error(tmp_path):
    def slow(args, cwd, timeout):
        if args[0] == "status":
            raise GitTimeout("git status took longer than 15 seconds")
        return {"rev-parse": GitResult(0, "true\n", ""),
                "symbolic-ref": GitResult(0, "main\n", "")}.get(args[0], GitResult(1, "", ""))

    s = check_repo("slow", tmp_path, runner=slow)
    assert s.state == "error" and "status" in s.error
    assert s.spoken() == "slow couldn't be checked"


def test_fetch_timeout_is_a_fetch_failure(tmp_path):
    def runner(args, cwd, timeout):
        if args[0] == "fetch":
            raise GitTimeout("slow network")
        return {"rev-parse": GitResult(0, "true\n" if "--is-inside-work-tree" in args
                                       else "origin/main\n", ""),
                "symbolic-ref": GitResult(0, "main\n", "")}.get(args[0], GitResult(0, "", ""))

    s = check_repo("r", tmp_path, runner=runner, fetch_timeout=5)
    assert s.fetch_error == "timed out after 5 seconds" and s.state == "fetch_failed"


def test_summary_caps_the_spoken_list(tmp_path):
    results = [RepoStatus(f"r{i}", tmp_path, branch="main", upstream="origin/main", changes=1)
               for i in range(5)]
    assert summarize(results) == ("5 of 5 repos need attention: r0 has uncommitted changes; "
                                  "r1 has uncommitted changes; r2 has uncommitted changes; "
                                  "and 2 more.")


def test_spoken_lists_three_problems(tmp_path):
    s = RepoStatus("r", tmp_path, branch="main", upstream="origin/main", changes=1,
                   ahead=["a"], behind=["b", "c"])
    assert s.spoken() == ("r has 1 unpushed commit, is 2 commits behind, "
                          "and has uncommitted changes")


def test_tool_is_not_destructive():
    assert CheckRepos.destructive is False
    assert CheckRepos.args_schema["additionalProperties"] is False


@pytest.mark.parametrize("value", [None, "", "all", "All", "none", "null", "my repos",
                                   "all my repos", "repositories", "*", "GitHub"])
def test_placeholders_mean_every_repo(tmp_path, value):
    assert git_sync.means_all_repos(value)
    cfg = write_config(tmp_path, {"a": tmp_path / "x", "b": tmp_path / "y"})
    tool = CheckRepos(config=lambda: cfg)
    tool.run(repo=value)
    assert len(tool.last_results) == 2


def test_real_repo_names_are_looked_up():
    assert not git_sync.means_all_repos("red")

"""The installer's inputs: the pins, the lock file and the scripts. No network, nothing installed."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "installer"


def test_pins_are_https_with_a_sha256_and_a_licence():
    pins = json.loads((INSTALLER / "pins.json").read_text(encoding="utf-8"))
    for name in ("python", "innosetup"):
        pin = pins[name]
        assert pin["url"].startswith("https://") and re.fullmatch(r"[0-9a-f]{64}", pin["sha256"])
        assert pin["version"] in pin["url"] and pin["licence"]
    assert pins["python"]["version"].startswith("3.11.")       # the wheels are built for 3.11


def normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def top_level_requirements() -> set[str]:
    found = set()
    for path in (ROOT / "requirements.txt", ROOT / "requirements-voice.txt", ROOT / "requirements-ui.txt"):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.split("#")[0].strip()
            m = re.match(r"([A-Za-z0-9_.\-]+)==", line)
            if m:
                found.add(normalise(m.group(1)))
    return found


def test_the_lock_pins_every_package_with_a_hash():
    lines = [l for l in (INSTALLER / "requirements-lock.txt").read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.startswith("#")]
    assert len(lines) > 30
    locked = {}
    for line in lines:
        m = re.match(r"([A-Za-z0-9_.\-]+)==([^\s]+) --hash=sha256:([0-9a-f]{64})\s+# (\S+\.whl)$", line)
        assert m, line
        locked[normalise(m.group(1))] = (m.group(2), m.group(4))
    assert top_level_requirements() <= set(locked)               # nothing the repo pins is missing
    for name, (version, wheel) in locked.items():
        assert wheel.endswith(".whl") and not wheel.endswith("none-any.whl") or "py3" in wheel or "py2" in wheel
    for line in (ROOT / "requirements-voice.txt").read_text(encoding="utf-8").splitlines():
        m = re.match(r"([A-Za-z0-9_.\-]+)==([^\s#]+)", line.strip())
        if m:                                                    # the same versions as the repo's own pins
            assert locked[normalise(m.group(1))][0] == m.group(2)
    assert not [w for _, w in locked.values() if "linux" in w or "macosx" in w]


def test_the_inno_script_is_per_user_and_asks_before_deleting_data():
    iss = (INSTALLER / "red.iss").read_text(encoding="utf-8")
    assert "PrivilegesRequired=lowest" in iss and "DefaultDirName={localappdata}\\Red" in iss
    assert "-m red.app.launch" in iss and "startup on" in iss and "startup off" in iss
    assert "Keep your memory" in iss and "DELETEDATA" in iss and "UninstallSilent" in iss
    for folder in ("memory", "models", "config"):
        assert folder in iss


def test_build_script_checks_hashes_and_never_runs_unpinned_downloads():
    ps1 = (INSTALLER / "build.ps1").read_text(encoding="utf-8")
    assert "--require-hashes" in ps1 and "Get-FileHash" in ps1 and "Get-Pinned" in ps1
    assert ps1.count("Invoke-WebRequest") == 1                    # the one pinned download helper
    assert "pins.json" in ps1 and "requirements-lock.txt" in ps1


@pytest.mark.skipif(shutil.which("powershell") is None, reason="needs Windows PowerShell")
def test_build_script_parses():
    command = ("$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile("
               f"'{INSTALLER / 'build.ps1'}', [ref]$null, [ref]$e); if ($e) {{ $e | ForEach-Object Message; exit 1 }}")
    done = subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True, text=True,
                          timeout=60)
    assert done.returncode == 0, done.stdout

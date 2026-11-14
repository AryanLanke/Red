# Red's installer

`Red-Setup.exe`: one file, per-user (no admin), installs Red to `%LOCALAPPDATA%\Red` with its own Python. No
Python, git or command line needed. The models (about 3.5 to 6 GB) are not in it; the first-run wizard downloads
them, checked against their checksums.

## Build

```powershell
powershell -ExecutionPolicy Bypass -File installer\build.ps1
# or, with a Python that has pip (only used to fetch wheels) and a work folder of your choice:
powershell -File installer\build.ps1 -Python D:\RED\.venv\Scripts\python.exe -Work D:\RED\cache\installer-work
```

Output: `installer\out\Red-Setup.exe` and its `.sha256`. What the build does:

1. Downloads the embeddable Python 3.11 and checks its SHA-256 against `pins.json`.
2. Downloads every wheel from `requirements-lock.txt` with `--require-hashes` and installs them into the embedded
   Python (`python\Lib\site-packages`). Wheels only, so no compiler and no scripts run at install time.
3. Copies `red\` and `companions\` into `app\`, compiles them.
4. Downloads Inno Setup (pinned, hash-checked), installs it silently into the work folder, compiles `red.iss`.

Nothing outside the work and output folders is touched.

## Pins

- `pins.json`: the embeddable Python and Inno Setup (URL, version, SHA-256, licence). To update one, download the
  new file, look at it, and put its SHA-256 here.
- `requirements-lock.txt`: made by `python installer\lock.py` from `requirements.txt` (pip resolves it for Python
  3.11 on Windows and reports each file's SHA-256). Run it again whenever `requirements*.txt` changes, and read
  the diff.

## What the installer does

- Installs to `%LOCALAPPDATA%\Red` (that folder is Red's `RED_HOME`: models, memory and settings live there too).
- Start menu: **Red** (`pythonw -m red.app.launch`: the first-run wizard once, then starts Red; later, starts Red
  or opens the settings if it is running) and **Red settings**.
- Optional tasks: start Red when you sign in (`red startup on`), a desktop icon.
- Uninstall: stops Red, removes the sign-in shortcut and the program files, then **asks whether to keep your
  memory, settings, companions and downloaded models**. A silent uninstall keeps them unless `/DELETEDATA=1`.

## The automatic install test

```powershell
powershell -ExecutionPolicy Bypass -File installer\sandbox_test.ps1 -Mode auto -Setup <out>\Red-Setup.exe -Stage <work>\stage -Results <folder>
```

Silent install, the files and shortcuts, `red doctor`, uninstall keeping memory, install again, uninstall
with `/DELETEDATA=1`; `result.json` lists every check. `-Mode host` runs it inside Windows Sandbox
(`sandbox-test.wsb`; Windows 11 Pro or better), `-Mode guest` on any clean Windows (the GitHub Actions
workflow `installer.yml` does this), `-Mode staged` copies the build's staged files instead of running the
exe (for a PC with Smart App Control on). The nightly run (`python -m red nightly`) builds and runs this
every night.

## Test it by hand

```powershell
Red-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /DIR="C:\Temp\RedTest" /LOG="C:\Temp\red-install.log"
C:\Temp\RedTest\python\python.exe -m red --home C:\Temp\RedTest doctor
C:\Temp\RedTest\unins000.exe /VERYSILENT /DELETEDATA=1
```

## Windows trust

Smart App Control blocks unsigned programs and SmartScreen warns about unknown ones. Until the installer is
signed (SignPath Foundation, or the Microsoft Store), the README tells people how to unblock it. Every file
inside is pinned and hashed, so what runs is what was reviewed.

# What the installer bundles or uses, and under which terms

Nothing here is downloaded without a pinned hash (`pins.json`, `requirements-lock.txt`). The licences of the
Python packages are the ones their own wheels carry (each wheel has a `*.dist-info\METADATA` and `LICENSE`
files, kept in `python\Lib\site-packages` inside the installed copy).

| What | Version | Where it comes from | Licence | Goes into `Red-Setup.exe`? |
|---|---|---|---|---|
| CPython, embeddable package | 3.11.9 | python.org (`pins.json`) | Python Software Foundation License | yes (`python\`) |
| Python packages (51, wheels only) | see `requirements-lock.txt` | PyPI, hash-pinned | each package's own (mostly MIT, BSD, Apache-2.0; PySide6 is LGPLv3, shipped as unmodified wheels) | yes (`python\Lib\site-packages`) |
| Inno Setup | 6.7.4 | jrsoftware/issrc releases (`pins.json`) | Inno Setup License: free to use, including to make commercial installers | no: build tool only |
| Red itself | see `pyproject.toml` | this repository | MIT (`LICENSE`) | yes (`app\`) |

PySide6 (LGPLv3): the wheels are installed unmodified as separate files next to Red, so a user can replace
them. The models (language model, Whisper, Kokoro, Piper, wake word) are not in the installer; Red downloads them
from their pinned sources on first run, and their licences are in the README.

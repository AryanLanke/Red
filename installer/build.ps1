<#
.SYNOPSIS
  Builds Red-Setup.exe: a one-file installer for Windows 11 with no Python, git or command line needed.

.DESCRIPTION
  1. Downloads the embeddable Python 3.11 and checks its SHA-256 (installer\pins.json).
  2. Downloads Red's wheels, every one pinned with a hash (installer\requirements-lock.txt),
     and installs them into the embedded Python. A wheel that changed on PyPI is refused.
  3. Copies the red package and the shipped companions next to it (the "app" folder).
  4. Downloads Inno Setup, checks its SHA-256, installs it silently into the work folder (per user, no
     admin), and compiles installer\red.iss.
  The models are NOT in the installer: Red downloads them on first run, with checksums.

  Nothing is installed outside the work folder. Output: installer\out\Red-Setup.exe

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File installer\build.ps1
  powershell -File installer\build.ps1 -Python "D:\RED\.venv\Scripts\python.exe" -Work D:\RED\cache\installer-work
#>
param(
    [string]$Work = "$PSScriptRoot\work",
    [string]$Out = "$PSScriptRoot\out",
    # A Python with pip, only used to download and unpack wheels (any 3.9+ works).
    [string]$Python = "",
    [switch]$SkipInno
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$pins = Get-Content "$PSScriptRoot\pins.json" -Raw | ConvertFrom-Json

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }

function Get-Pinned($pin, $dest) {
    # Download once, and only trust a file whose SHA-256 matches the pin.
    if (Test-Path $dest) {
        if ((Get-FileHash $dest -Algorithm SHA256).Hash -eq $pin.sha256.ToUpper()) { return }
        Remove-Item $dest -Force
    }
    Write-Host "downloading $($pin.url)"
    New-Item -ItemType Directory -Force (Split-Path $dest) | Out-Null
    $part = "$dest.part"
    Invoke-WebRequest -Uri $pin.url -OutFile $part -UseBasicParsing
    $actual = (Get-FileHash $part -Algorithm SHA256).Hash
    if ($actual -ne $pin.sha256.ToUpper()) {
        Remove-Item $part -Force
        throw "SHA-256 of $($pin.url) is $actual, not the pinned $($pin.sha256). Not using it."
    }
    Move-Item $part $dest
}

if (-not $Python) {
    $found = Get-Command python -ErrorAction SilentlyContinue
    if (-not $found) { throw "Need a Python with pip to unpack wheels: pass -Python <path to python.exe>." }
    $Python = $found.Source
}
$version = (Select-String -Path "$root\pyproject.toml" -Pattern '^version\s*=\s*"(.+)"').Matches[0].Groups[1].Value
Write-Host "Building Red $version into $Out"

$dl = "$Work\downloads"
$stage = "$Work\stage"
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force $dl, "$stage\app", $Out | Out-Null

# --- 1. the embeddable Python --------------------------------------------------------------------------
Step "Python $($pins.python.version) (embeddable)"
$pyzip = "$dl\python-$($pins.python.version)-embed-amd64.zip"
Get-Pinned $pins.python $pyzip
Expand-Archive $pyzip -DestinationPath "$stage\python" -Force
# Where Python looks for code: its own folder, the packages we install, and the app (red). `import site`
# makes the packages folder count; the embeddable Python ignores PYTHONPATH and the current folder.
$pth = Get-ChildItem "$stage\python\python*._pth" | Select-Object -First 1
$zipName = [IO.Path]::GetFileNameWithoutExtension($pth.Name).Replace("._pth", "")
Set-Content $pth.FullName -Encoding ascii -Value @("$zipName.zip", ".", "Lib\site-packages", "..\app", "import site")

# --- 2. the wheels, pinned with hashes ------------------------------------------------------------------
Step "Wheels (hash-checked)"
$lock = "$PSScriptRoot\requirements-lock.txt"
$wheels = "$Work\wheels"
New-Item -ItemType Directory -Force $wheels | Out-Null
$common = @("--only-binary=:all:", "--python-version", "3.11", "--platform", "win_amd64", "--no-deps",
            "--require-hashes", "--disable-pip-version-check", "-q")
& $Python -m pip download @common -r $lock -d $wheels
if ($LASTEXITCODE -ne 0) { throw "downloading the wheels failed" }
& $Python -m pip install @common --no-index --find-links $wheels --target "$stage\python\Lib\site-packages" -r $lock
if ($LASTEXITCODE -ne 0) { throw "installing the wheels failed" }
Get-ChildItem "$stage\python\Lib\site-packages" -Filter "__pycache__" -Recurse -Directory |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

# --- 3. the app -------------------------------------------------------------------------------------------
Step "Red's own files"
$skip = @("__pycache__", "*.pyc")
robocopy "$root\red" "$stage\app\red" /E /XD __pycache__ /XF *.pyc /NFL /NDL /NJH /NJS /NP | Out-Null
robocopy "$root\companions" "$stage\app\companions" /E /XD __pycache__ /NFL /NDL /NJH /NJS /NP | Out-Null
foreach ($f in ".env.example", "allowlist.example.toml", "repos.example.toml", "contacts.example.toml",
               "LICENSE", "README.md", "pyproject.toml") {
    Copy-Item "$root\$f" "$stage\app\$f"
}
Copy-Item "$PSScriptRoot\requirements-lock.txt" "$stage\app\requirements-lock.txt"
# Compile Red's own files now, so the first start doesn't.
& "$stage\python\python.exe" -m compileall -q "$stage\app\red"
Set-Content "$stage\app\VERSION" -Value $version -Encoding ascii

$bytes = (Get-ChildItem $stage -Recurse -File | Measure-Object Length -Sum).Sum
Write-Host ("staged {0:N0} MB in {1:N0} files" -f ($bytes / 1MB), (Get-ChildItem $stage -Recurse -File).Count)

if ($SkipInno) { Write-Host "Skipping Inno Setup (-SkipInno). Staged files are in $stage"; return }

# --- 4. Inno Setup, pinned, installed silently into the work folder ------------------------------------------
Step "Inno Setup $($pins.innosetup.version)"
$iscc = "$Work\inno\ISCC.exe"
if (-not (Test-Path $iscc)) {
    $setup = "$dl\innosetup-$($pins.innosetup.version).exe"
    Get-Pinned $pins.innosetup $setup
    $p = Start-Process $setup -Wait -PassThru -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
        "/CURRENTUSER", "/NOICONS", "/DIR=`"$Work\inno`"")
    if ($p.ExitCode -ne 0 -or -not (Test-Path $iscc)) { throw "Inno Setup did not install (exit $($p.ExitCode))" }
}

Step "Compiling Red-Setup.exe"
& $iscc "/DAppVersion=$version" "/DStage=$stage" "/DOutDir=$Out" "$PSScriptRoot\red.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed ($LASTEXITCODE)" }

$exe = Join-Path $Out "Red-Setup.exe"
$hash = (Get-FileHash $exe -Algorithm SHA256).Hash
Write-Host ("`nDone: {0}  {1:N0} MB`nSHA-256 {2}" -f $exe, ((Get-Item $exe).Length / 1MB), $hash) -ForegroundColor Green
Set-Content "$Out\Red-Setup.exe.sha256" -Value "$hash *Red-Setup.exe" -Encoding ascii

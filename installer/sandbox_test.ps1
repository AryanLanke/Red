<#
.SYNOPSIS
  Installs Red-Setup.exe silently, checks it, runs `red doctor`, uninstalls it (keeping data, then deleting it)
  and writes result.json. Nothing is played, recorded or downloaded.

.DESCRIPTION
  -Mode guest    The real test, on a clean Windows: inside Windows Sandbox, on a CI machine or a spare PC.
                 Installs to %LOCALAPPDATA%\Red (or -InstallDir), with the "start with Windows" task.
  -Mode host     Starts Windows Sandbox with installer\sandbox-test.wsb (paths filled in), which runs this
                 script in guest mode, and waits for its result.json. Needs Windows 11 Pro, Enterprise or
                 Education with the Windows Sandbox feature on.
  -Mode staged   For a PC that can't run the unsigned installer (Smart App Control) or has no Sandbox:
                 copies the staged files the installer would copy (build.ps1 -Work ...\stage) into a test
                 folder, runs the same checks on the embedded Python, then removes the program folders the
                 way the uninstaller does. It never touches the Start menu, the Startup folder or the registry.
  -Mode auto     host if Windows Sandbox is there, else staged. What the nightly run uses.

  Exit code 0 = every check passed. result.json lists each check with ok/fail and a detail line.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File installer\sandbox_test.ps1 -Mode auto -Results D:\RED\cache\installer\test
  powershell -File installer\sandbox_test.ps1 -Mode guest -Setup .\Red-Setup.exe -Results .\result
#>
param(
    [ValidateSet("auto", "host", "guest", "staged")]
    [string]$Mode = "auto",
    [string]$Setup = "",
    [string]$Stage = "",
    [string]$Results = "",
    [string]$InstallDir = "",
    [int]$TimeoutMinutes = 30,
    [switch]$Shutdown
)

$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
if (-not $Results) { $Results = Join-Path $here "out\sandbox-test" }
New-Item -ItemType Directory -Force $Results | Out-Null
$sandboxExe = Join-Path $env:SystemRoot "System32\WindowsSandbox.exe"

if ($Mode -eq "auto") { $Mode = if (Test-Path $sandboxExe) { "host" } else { "staged" } }
if (-not $Setup) { $Setup = Join-Path $here "out\Red-Setup.exe" }

$checks = New-Object System.Collections.ArrayList
$started = Get-Date
function Check([string]$name, [bool]$ok, [string]$detail = "") {
    [void]$checks.Add([ordered]@{ name = $name; ok = $ok; detail = $detail })
    $mark = if ($ok) { "[ok]  " } else { "[FAIL]" }
    Write-Host "$mark $name $(if ($detail) { "- $detail" })"
}
function Finish([string]$mode, [hashtable]$extra = @{}) {
    $failed = @($checks | Where-Object { -not $_.ok }).Count
    $result = [ordered]@{
        mode = $mode; passed = ($failed -eq 0 -and $checks.Count -gt 0); failed = $failed
        checks = $checks; seconds = [int]((Get-Date) - $started).TotalSeconds
        finished = (Get-Date).ToString("s"); computer = $env:COMPUTERNAME
    }
    foreach ($k in $extra.Keys) { $result[$k] = $extra[$k] }
    $result | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $Results "result.json") -Encoding utf8
    Write-Host ("`n{0}: {1} of {2} checks passed in {3} s. {4}" -f $mode, ($checks.Count - $failed), $checks.Count,
                $result.seconds, (Join-Path $Results "result.json"))
    if ($Shutdown) { shutdown.exe /s /t 5 | Out-Null }
    exit $(if ($result.passed) { 0 } else { 1 })
}

# --------------------------------------------------------------------------------------------------------
# host: run the guest test inside Windows Sandbox and wait for it
# --------------------------------------------------------------------------------------------------------
if ($Mode -eq "host") {
    if (-not (Test-Path $sandboxExe)) { Check "Windows Sandbox is available" $false "not on this edition of Windows"; Finish "host" }
    if (-not (Test-Path $Setup)) { Check "Red-Setup.exe exists" $false $Setup; Finish "host" }
    $guestResults = Join-Path $Results "guest"
    if (Test-Path $guestResults) { Remove-Item $guestResults -Recurse -Force }
    New-Item -ItemType Directory -Force $guestResults | Out-Null
    $esc = { param($p) [Security.SecurityElement]::Escape((Resolve-Path $p).Path) }
    $wsb = (Get-Content (Join-Path $here "sandbox-test.wsb") -Raw).
        Replace("{SETUP_DIR}", (& $esc (Split-Path $Setup))).
        Replace("{SCRIPTS_DIR}", (& $esc $here)).
        Replace("{RESULTS_DIR}", (& $esc $guestResults)).
        Replace("{SETUP_NAME}", [IO.Path]::GetFileName($Setup))
    $wsbPath = Join-Path $Results "run.wsb"
    Set-Content $wsbPath $wsb -Encoding utf8
    Write-Host "Starting Windows Sandbox ($wsbPath); waiting up to $TimeoutMinutes minutes for the result"
    Start-Process $sandboxExe -ArgumentList "`"$wsbPath`""
    $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
    $guestJson = Join-Path $guestResults "result.json"
    while (-not (Test-Path $guestJson) -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 10 }
    if (-not (Test-Path $guestJson)) {
        Get-Process WindowsSandbox*, WindowsSandboxRemoteSession -ErrorAction SilentlyContinue | Stop-Process -Force
        Check "the Sandbox test finished" $false "no result.json after $TimeoutMinutes minutes"
        Finish "host"
    }
    Start-Sleep -Seconds 2
    $guest = Get-Content $guestJson -Raw | ConvertFrom-Json
    foreach ($c in $guest.checks) { Check $c.name ([bool]$c.ok) $c.detail }
    Finish "host" @{ guest_seconds = $guest.seconds }
}

# --------------------------------------------------------------------------------------------------------
# guest and staged: install, check, doctor, uninstall
# --------------------------------------------------------------------------------------------------------
$staged = $Mode -eq "staged"
if (-not $InstallDir) {
    $InstallDir = if ($staged) { Join-Path $Results "Red" } else { Join-Path $env:LOCALAPPDATA "Red" }
}
if ($staged -and $InstallDir.StartsWith("$env:LOCALAPPDATA", "OrdinalIgnoreCase")) {
    throw "staged mode installs into a test folder, never the real %LOCALAPPDATA%\Red"
}
if ($staged -and (Test-Path $InstallDir)) { Remove-Item $InstallDir -Recurse -Force }
$py = Join-Path $InstallDir "python\python.exe"
$version = ""

function Install-Red {
    if ($staged) {
        if (-not $Stage) { throw "staged mode needs -Stage <build work folder>\stage" }
        foreach ($d in "python", "app") {
            robocopy (Join-Path $Stage $d) (Join-Path $InstallDir $d) /E /NFL /NDL /NJH /NJS /NP | Out-Null
            if ($LASTEXITCODE -ge 8) { throw "copying $d failed (robocopy $LASTEXITCODE)" }
        }
        return 0
    }
    $log = Join-Path $Results "install.log"
    $p = Start-Process $Setup -Wait -PassThru -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
        "/SP-", "/TASKS=startup", "/DIR=`"$InstallDir`"", "/LOG=`"$log`"")
    return $p.ExitCode
}

function Wait-Uninstall {
    # The uninstaller runs a copy of itself from %TEMP%; wait for that copy too.
    $deadline = (Get-Date).AddMinutes(3)
    while ((Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Name -like "_iu*" -or $_.Name -like "unins*" }) -and
           (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 500 }
}

function Uninstall-Red([bool]$deleteData) {
    if ($staged) {
        # What [UninstallDelete] does; the data question is the uninstaller's and is tested in guest mode.
        foreach ($d in "python", "app") { Remove-Item (Join-Path $InstallDir $d) -Recurse -Force -ErrorAction SilentlyContinue }
        if ($deleteData) { Remove-Item $InstallDir -Recurse -Force -ErrorAction SilentlyContinue }
        return 0
    }
    $uargs = @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART")
    if ($deleteData) { $uargs += "/DELETEDATA=1" }
    $p = Start-Process (Join-Path $InstallDir "unins000.exe") -Wait -PassThru -ArgumentList $uargs
    Wait-Uninstall
    return $p.ExitCode
}

function Run-Py([string[]]$pyArgs, [string]$logName) {
    $out = Join-Path $Results $logName
    $env:PYTHONIOENCODING = "utf-8"
    Push-Location (Join-Path $InstallDir "app")
    try { & $py @pyArgs *> $out; $code = $LASTEXITCODE } finally { Pop-Location }
    return $code
}

# 1. install
$t0 = Get-Date
if (-not $staged -and -not (Test-Path $Setup)) { Check "Red-Setup.exe exists" $false $Setup; Finish $Mode }
if (-not $staged) {
    $mb = [math]::Round((Get-Item $Setup).Length / 1MB)
    Check "Red-Setup.exe is under 200 MB" ($mb -lt 200) "$mb MB"
}
try { $code = Install-Red } catch { $code = -1; Check "install" $false $_.Exception.Message; Finish $Mode }
Check "install" ($code -eq 0) ("exit {0} in {1:N0} s into {2}" -f $code, ((Get-Date) - $t0).TotalSeconds, $InstallDir)
if ($code -ne 0) { Finish $Mode }

# 2. files and shortcuts
$need = @("python\python.exe", "python\pythonw.exe", "app\red\__main__.py", "app\red\app\launch.py", "app\companions",
          "app\VERSION", "app\LICENSE")
if (-not $staged) { $need += "unins000.exe" }
$missing = @($need | Where-Object { -not (Test-Path (Join-Path $InstallDir $_)) })
Check "program files are in place" ($missing.Count -eq 0) $(if ($missing) { "missing: $($missing -join ', ')" } else { "$($need.Count) checked" })
if (Test-Path (Join-Path $InstallDir "app\VERSION")) { $version = (Get-Content (Join-Path $InstallDir "app\VERSION") -Raw).Trim() }
$programs = [Environment]::GetFolderPath("Programs")
$startupDir = [Environment]::GetFolderPath("Startup")
if (-not $staged) {
    Check "Start menu: Red and Red settings" ((Test-Path "$programs\Red.lnk") -and (Test-Path "$programs\Red settings.lnk")) $programs
    Check "start with Windows shortcut" (Test-Path "$startupDir\Red.lnk") $startupDir
}

# 3. red doctor on the embedded Python, with the install folder as RED_HOME
$env:RED_HOME = $InstallDir
$code = Run-Py @("-m", "red", "--home", $InstallDir, "doctor") "doctor.txt"
$doctorText = Get-Content (Join-Path $Results "doctor.txt") -Raw -ErrorAction SilentlyContinue
$summary = ([regex]::Match("$doctorText", "\d+ problem\(s\), \d+ warning\(s\)")).Value
Check "red doctor runs" ($summary -ne "") $(if ($summary) { $summary } else { "exit $code, no summary line" })
# Python, the packages and RED_HOME must be ok; the models are missing on purpose (the wizard downloads them).
$probe = "import json; from red.doctor import run_checks; " +
         "print(json.dumps([[c.status, c.title] for c in run_checks()]))"
$code = Run-Py @("-c", $probe) "doctor.json"
try {
    $rows = Get-Content (Join-Path $Results "doctor.json") -Raw | ConvertFrom-Json
    foreach ($want in "Python 3.11", "Core packages", "Voice packages", "Overlay packages", "RED_HOME is") {
        $row = $rows | Where-Object { $_[1].StartsWith($want) } | Select-Object -First 1
        Check "doctor: $want" ($row -and $row[0] -eq "ok") $(if ($row) { "$($row[0]): $($row[1])" } else { "not reported" })
    }
} catch { Check "doctor checks as data" $false "exit $code; $($_.Exception.Message)" }

# 4. other commands that must work before any model is there
$code = Run-Py @("-m", "red", "--home", $InstallDir, "plugins", "list") "plugins.txt"
Check "red plugins list" ($code -eq 0) "exit $code"
$code = Run-Py @("-c", "import red.app.first_run, red.app.launch, red.avatar, red.tray; print('ok')") "imports.txt"
Check "the wizard, companion and tray import" ($code -eq 0) "exit $code"
$code = Run-Py @("-m", "red", "--home", $InstallDir, "startup") "startup.txt"
Check "red startup (show)" ($code -eq 0) "exit $code"

# 5. uninstall, keeping the user's data
$marker = Join-Path $InstallDir "memory\install-test.txt"
New-Item -ItemType Directory -Force (Split-Path $marker) | Out-Null
Set-Content $marker "kept?" -Encoding ascii
$code = Uninstall-Red $false
$gone = -not (Test-Path (Join-Path $InstallDir "python")) -and -not (Test-Path (Join-Path $InstallDir "app"))
Check "uninstall removes the program" ($code -eq 0 -and $gone) "exit $code"
Check "uninstall keeps memory" (Test-Path $marker) $marker
if (-not $staged) {
    Check "uninstall removes the Start menu entries" (-not (Test-Path "$programs\Red.lnk")) ""
    Check "uninstall removes start with Windows" (-not (Test-Path "$startupDir\Red.lnk")) ""
}

# 6. install again over the kept data, then uninstall with /DELETEDATA=1
$code = Install-Red
Check "install again over kept data" ($code -eq 0 -and (Test-Path $marker)) "exit $code"
$code = Uninstall-Red $true
Check "uninstall /DELETEDATA=1 removes everything" ($code -eq 0 -and -not (Test-Path $InstallDir)) "exit $code"

Finish $Mode @{ version = $version; install_dir = $InstallDir }

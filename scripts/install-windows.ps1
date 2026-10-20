<#
.SYNOPSIS
  Install LMMS MCP Pro and register it with the Claude desktop app (Chat and Code).

.DESCRIPTION
  1. Creates a virtual environment in .venv and installs this repo in editable mode
     (edits to the source take effect the next time Claude starts the server).
  2. Finds lmms.exe and picks a folder for the projects Claude writes.
  3. Runs scripts\smoke_test.py (starts the server over stdio, lists tools).
  4. Chat: adds "lmms-pro" to claude_desktop_config.json (a backup is written first).
  5. Code: adds "lmms-pro" at user scope (all folders) with `claude mcp add`,
     or, if the claude CLI is not installed, directly in %USERPROFILE%\.claude.json.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install-windows.ps1
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install-windows.ps1 -ProjectsDir "D:\Music\LMMS\Claude" -LmmsExe "C:\Program Files\LMMS\lmms.exe"
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install-windows.ps1 -SkipChat     # Code only
#>
param(
    [string]$Name = "lmms-pro",
    [string]$ProjectsDir = (Join-Path $env:USERPROFILE "Documents\lmms\projects\Claude"),
    [string]$LmmsExe = "",
    [string]$Python = "",          # e.g. "C:\Users\me\AppData\Local\Programs\Python\Python312\python.exe"
    [switch]$Clean,                # delete .venv first and rebuild it
    [switch]$SkipChat,
    [switch]$SkipCode,
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
$VenvPy = Join-Path $Repo ".venv\Scripts\python.exe"
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "    OK  $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "    !!  $msg" -ForegroundColor Yellow }

function Set-McpServer($path, $serverName, $entry) {
    # JSON edits go through Python so the rest of the file is kept exactly (PowerShell 5.1's
    # ConvertFrom-Json chokes on some files, e.g. keys that differ only in case).
    $tmp = [System.IO.Path]::GetTempFileName()
    [System.IO.File]::WriteAllText($tmp, ($entry | ConvertTo-Json -Depth 8), $Utf8NoBom)
    & $VenvPy (Join-Path $Repo "scripts\mcp_config.py") set $path $serverName $tmp
    $code = $LASTEXITCODE
    Remove-Item $tmp
    if ($code -ne 0) { throw "Could not update $path" }
}

# --------------------------------------------------------------------------- 1. install
function Get-PyInfo($exe) {
    # Returns @{Exe; Version; FreeThreaded} or $null. Never throws.
    $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    try {
        $out = & $exe -c "import sys, sysconfig; print('%d.%d|%d|%s' % (sys.version_info[0], sys.version_info[1], 1 if sysconfig.get_config_var('Py_GIL_DISABLED') else 0, sys.executable))" 2>$null
    } catch { $out = $null }
    $ErrorActionPreference = $prev
    if (-not $out) { return $null }
    $parts = ([string]$out).Trim().Split("|")
    if ($parts.Count -lt 3) { return $null }
    return @{ Exe = $parts[2]; Version = [version]$parts[0]; FreeThreaded = ($parts[1] -eq "1") }
}

function Find-Python {
    # Every Python the py launcher knows (py -0p), plus python.exe on PATH.
    $paths = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
        $list = & py -0p 2>$null
        $ErrorActionPreference = $prev
        foreach ($line in $list) {
            if ($line -match "([A-Za-z]:\\.+?\.exe)\s*$") { $paths += $Matches[1] }
        }
    }
    Get-Command python -All -ErrorAction SilentlyContinue | ForEach-Object { $paths += $_.Source }
    $found = @()
    foreach ($p in ($paths | Select-Object -Unique)) {
        if ($p -like "*WindowsApps*") { continue }          # Microsoft Store alias stubs
        $info = Get-PyInfo $p
        if ($info) { $found += $info }
    }
    return $found
}

if (-not $SkipInstall) {
    Step "Python + virtual environment"
    if ($Python) {
        $pick = Get-PyInfo $Python
        if (-not $pick) { throw "Could not run '$Python'. Give the full path to an existing python.exe." }
    } else {
        $all = @(Find-Python)
        foreach ($i in $all) {
            $tag = ""; if ($i.FreeThreaded) { $tag = "  (free-threaded - skipped)" }
            Write-Host ("    found Python {0}  {1}{2}" -f $i.Version, $i.Exe, $tag)
        }
        $pick = $all | Where-Object { -not $_.FreeThreaded -and $_.Version -ge [version]"3.10" } |
                Sort-Object @{ Expression = { $_.Version }; Descending = $true },
                            @{ Expression = { if ($_.Exe -match "conda") { 1 } else { 0 } }; Ascending = $true } |
                Select-Object -First 1      # same version: prefer python.org over Anaconda
        if (-not $pick) {
            throw ("No usable Python found. Needs a normal (not free-threaded) Python 3.10 or newer. " +
                   "Install Python 3.12 or 3.13 from python.org, or pass -Python 'C:\path\to\python.exe'.")
        }
    }
    if ($pick.FreeThreaded) {
        throw "$($pick.Exe) is a free-threaded build (python3.13t). pywin32, which the MCP library needs on Windows, does not support it. Use the normal python.exe."
    }
    if ($pick.Version -lt [version]"3.10") { throw "Python $($pick.Version) found, 3.10+ required." }
    Ok "using Python $($pick.Version): $($pick.Exe)"

    # Rebuild .venv if asked, or if it was made by a free-threaded / broken Python
    $venvDir = Join-Path $Repo ".venv"
    if (Test-Path $venvDir) {
        $vinfo = Get-PyInfo $VenvPy
        if ($Clean -or -not $vinfo -or $vinfo.FreeThreaded -or $vinfo.Version -ne $pick.Version) {
            Remove-Item -Recurse -Force $venvDir
            Ok "removed old .venv"
        }
    }
    if (-not (Test-Path $VenvPy)) {
        & $pick.Exe -m venv $venvDir
        if ($LASTEXITCODE -ne 0) { throw "Creating the virtual environment failed." }
    }
    & $VenvPy -m pip install --quiet --upgrade pip
    & $VenvPy -m pip install --quiet -e "$Repo[dev]"
    if ($LASTEXITCODE -ne 0) {
        Warn "pip install failed - running it again with full output so the cause is visible:"
        & $VenvPy -c "import sys, platform, sysconfig; print('venv python:', sys.version); print('platform:', platform.platform(), platform.architecture()[0], platform.machine()); print('free-threaded:', bool(sysconfig.get_config_var('Py_GIL_DISABLED')))"
        & $VenvPy -m pip --version
        & $VenvPy -m pip config list
        Get-ChildItem Env: | Where-Object { $_.Name -like "PIP_*" } | ForEach-Object { Write-Host "    env $($_.Name)=$($_.Value)" }
        & $VenvPy -m pip install -e "$Repo[dev]"
        throw "pip install failed - copy everything from 'Python + virtual environment' down and send it to Claude."
    }
    Ok "installed into $Repo\.venv (editable)"
}
if (-not (Test-Path $VenvPy)) { throw "No .venv found. Run without -SkipInstall first." }

# --------------------------------------------------------------------------- 2. paths
Step "LMMS and projects folder"
if (-not $LmmsExe) {
    $candidates = @(
        "$env:ProgramFiles\LMMS\lmms.exe",
        "${env:ProgramFiles(x86)}\LMMS\lmms.exe",
        "$env:LOCALAPPDATA\Programs\LMMS\lmms.exe"
    )
    foreach ($c in $candidates) { if ($c -and (Test-Path $c)) { $LmmsExe = $c; break } }
}
if ($LmmsExe -and (Test-Path $LmmsExe)) { Ok "LMMS: $LmmsExe" }
else { Warn "lmms.exe not found - rendering disabled. Re-run with -LmmsExe 'C:\path\to\lmms.exe'."; $LmmsExe = "" }

New-Item -ItemType Directory -Force -Path $ProjectsDir | Out-Null
Ok "projects: $ProjectsDir"

$envVars = [ordered]@{ "LMMS_PROJECTS_DIR" = $ProjectsDir; "PYTHONUNBUFFERED" = "1" }
if ($LmmsExe) { $envVars["LMMS_EXECUTABLE"] = $LmmsExe }

# --------------------------------------------------------------------------- 3. smoke test
Step "Smoke test (starts the server like Claude does)"
foreach ($k in $envVars.Keys) { Set-Item -Path "Env:$k" -Value $envVars[$k] }
& $VenvPy (Join-Path $Repo "scripts\smoke_test.py")
if ($LASTEXITCODE -ne 0) { throw "Smoke test failed - see the error above." }

$entry = [ordered]@{
    "command" = $VenvPy
    "args"    = @("-m", "lmms_mcp")
    "env"     = $envVars
}

# --------------------------------------------------------------------------- 4. Chat
if (-not $SkipChat) {
    Step "Claude desktop app - Chat (claude_desktop_config.json)"
    # Microsoft Store (MSIX) installs redirect AppData\Roaming into the app's own package
    # folder, so the app never reads %APPDATA%\Claude there. Write where the app looks.
    $targets = @()
    $msix = @(Get-ChildItem (Join-Path $env:LOCALAPPDATA "Packages") -Directory -Filter "Claude_*" -ErrorAction SilentlyContinue)
    foreach ($m in $msix) {
        $dir = Join-Path $m.FullName "LocalCache\Roaming\Claude"
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
        $targets += (Join-Path $dir "claude_desktop_config.json")
        Ok "Microsoft Store install detected: $($m.Name)"
    }
    $classic = Join-Path $env:APPDATA "Claude\claude_desktop_config.json"
    if ($msix.Count -eq 0 -or (Test-Path $classic)) {
        New-Item -ItemType Directory -Force -Path (Split-Path $classic) | Out-Null
        $targets += $classic
    }
    foreach ($t in $targets) { Set-McpServer $t $Name $entry }
}

# --------------------------------------------------------------------------- 5. Code
if (-not $SkipCode) {
    Step "Claude Code (Code tab) - user scope, available in every folder"
    $claude = Get-Command claude -ErrorAction SilentlyContinue
    if ($claude) {
        $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
        & claude mcp remove $Name -s user *> $null      # fine if it was not registered yet
        $ErrorActionPreference = $prev
        $cliArgs = @("mcp", "add", "--scope", "user")
        foreach ($k in $envVars.Keys) { $cliArgs += @("--env", "$k=$($envVars[$k])") }
        $cliArgs += @("--transport", "stdio", $Name, "--", $VenvPy, "-m", "lmms_mcp")
        & claude @cliArgs
        if ($LASTEXITCODE -ne 0) { throw "claude mcp add failed." }
        Ok "registered with: claude mcp add (user scope)"
    } else {
        Warn "claude CLI not on PATH - writing user scope directly into ~/.claude.json"
        Set-McpServer (Join-Path $env:USERPROFILE ".claude.json") $Name $entry
    }
}

Step "Done"
Write-Host "    Fully quit Claude (tray icon > Quit) and open it again."
Write-Host "    Chat: '+' menu > Connectors should list '$Name'."
Write-Host "    Code: type /mcp in a session - '$Name' should show as connected."

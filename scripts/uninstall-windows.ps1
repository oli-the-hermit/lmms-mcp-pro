<#
.SYNOPSIS
  Remove the "lmms-pro" registration from Claude (Chat and Code). Leaves .venv and the repo alone.
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\uninstall-windows.ps1
#>
param([string]$Name = "lmms-pro")
$Repo = Split-Path -Parent $PSScriptRoot
$VenvPy = Join-Path $Repo ".venv\Scripts\python.exe"
$Helper = Join-Path $Repo "scripts\mcp_config.py"

$paths = @(Join-Path $env:APPDATA "Claude\claude_desktop_config.json")
Get-ChildItem (Join-Path $env:LOCALAPPDATA "Packages") -Directory -Filter "Claude_*" -ErrorAction SilentlyContinue |
    ForEach-Object { $paths += (Join-Path $_.FullName "LocalCache\Roaming\Claude\claude_desktop_config.json") }
foreach ($p in $paths) { if (Test-Path $p) { & $VenvPy $Helper remove $p $Name } }

if (Get-Command claude -ErrorAction SilentlyContinue) { & claude mcp remove $Name -s user }
else {
    $cj = Join-Path $env:USERPROFILE ".claude.json"
    if (Test-Path $cj) { & $VenvPy $Helper remove $cj $Name }
}
Write-Host "Restart Claude to apply."

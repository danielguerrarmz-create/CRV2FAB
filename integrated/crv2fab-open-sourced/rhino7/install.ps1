# CRV2FAB: one-step install of the nudge core's Python side (Windows, PowerShell 5.1 or later).
#
#   powershell -ExecutionPolicy Bypass -File install.ps1 [-Core <folder>] [-Python <python.exe>]
#
# 1. Finds the nudge core: -Core, else GNJ_CORE_DIR, else core\ beside this folder (the published
#    layout), else gnj-nudge-core\ beside it (a checkout). The core is the folder that holds gnj_nudge.
# 2. Checks for the Python the core's pyproject.toml declares (requires-python, today 3.13 or later):
#    -Python, else python on the PATH, else the py launcher.
# 3. Makes a virtual environment in <core>\.venv and installs the core's needs into it:
#    numpy, pillow and anthropic (the core imports anthropic at start; it calls the Anthropic API only
#    with GNJ_BACKEND=api and a key).
# 4. Writes crv2fab.config.json here (core_dir, python). The Rhino side reads it to start the core.
# Then, once, in Rhino 7:  _-RunPythonScript "<this folder>\install_rhino.py"  adds the CRV2FAB command.
param([string]$Core = "", [string]$Python = "")
$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$parent = Split-Path -Parent $here

$tried = @($Core, $env:GNJ_CORE_DIR, (Join-Path $parent "core"), (Join-Path $parent "gnj-nudge-core")) | Where-Object { $_ }
$coreDir = $tried | Where-Object { Test-Path (Join-Path $_ "gnj_nudge") } | Select-Object -First 1
if (-not $coreDir) { throw "The nudge core was not found (tried: $($tried -join ', ')). Pass -Core <folder that holds gnj_nudge>." }
$coreDir = (Resolve-Path $coreDir).Path
Write-Output "Core: $coreDir"

if (-not $Python) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { $Python = $cmd.Source }
    elseif (Get-Command py -ErrorAction SilentlyContinue) { $Python = (& py -3 -c "import sys; print(sys.executable)").Trim() }
    else { throw "Python was not found. Install it from python.org, or pass -Python <python.exe>." }
}
# The minimum is the core's own: requires-python = ">=X.Y" in its pyproject.toml.
$needMajor, $needMinor = 3, 13
$pyproject = Join-Path $coreDir "pyproject.toml"
if (Test-Path $pyproject) {
    $m = Select-String -Path $pyproject -Pattern 'requires-python\s*=\s*">=\s*(\d+)\.(\d+)' | Select-Object -First 1
    if ($m) { $needMajor, $needMinor = [int]$m.Matches[0].Groups[1].Value, [int]$m.Matches[0].Groups[2].Value }
}
$version = (& $Python -c "import sys; print('%d.%d' % sys.version_info[:2])").Trim()
$major, $minor = $version.Split(".") | ForEach-Object { [int]$_ }
if ($major -lt $needMajor -or ($major -eq $needMajor -and $minor -lt $needMinor)) {
    throw "Python $version at $Python is too old: the core needs $needMajor.$needMinor or later."
}
Write-Output "Python $version at $Python"

$venv = Join-Path $coreDir ".venv"
$venvPython = Join-Path $venv "Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    & $Python -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw "Could not make the virtual environment at $venv." }
}
& $venvPython -m pip install --disable-pip-version-check --quiet numpy pillow anthropic
if ($LASTEXITCODE -ne 0) { throw "pip could not install numpy, pillow and anthropic into $venv." }
Write-Output "Installed numpy, pillow and anthropic into $venv"

$config = Join-Path $here "crv2fab.config.json"
$json = @{ core_dir = $coreDir; python = $venvPython } | ConvertTo-Json
[System.IO.File]::WriteAllText($config, $json, (New-Object System.Text.UTF8Encoding $false))
Write-Output "Wrote $config"
Write-Output ""
Write-Output "Next, once, in Rhino 7 (Rhino 8 is expected to work but untested):"
Write-Output "  _-RunPythonScript `"$(Join-Path $here 'install_rhino.py')`""
Write-Output "Then type CRV2FAB in Rhino to open the card."

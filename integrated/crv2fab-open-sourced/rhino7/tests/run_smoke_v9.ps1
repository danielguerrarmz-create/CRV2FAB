# Runs tests/smoke_v9.py in a fresh Rhino 7 test instance (/scheme=GNJSmoke) on a BRAND NEW empty
# document (Daniel, 2026-11-15): no file is opened and nothing is saved.
# Usage (Windows PowerShell 5.1):  powershell -File tests\run_smoke_v9.ps1 [outdir] [-Scheme name] [-Port n] [-Core dir]
# Rhino 7 only; never Rhino 8. Kills only the Rhino it started. Fails if Daniel's Default scheme file
# changed while it ran. Core: a committed export (git archive) of gnj-nudge-core, on its own port.
param([string]$Out = "C:\Users\danie\scratch\2026-11-15\v9-ui",
      [string]$Scheme = "GNJSmoke",
      [int]$Port = 8781,
      [string]$Core = "C:\Users\danie\scratch\2026-11-15\gnj-core-main-c64ed6d")
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$rhino = "C:\Program Files\Rhino 7\System\Rhino.exe"
$default = Join-Path $env:APPDATA "McNeel\Rhinoceros\7.0\settings\settings-Scheme__Default.xml"
if ($Scheme -eq "Default" -or $Port -eq 8742) { throw "never Daniel's Default scheme or port 8742" }
if (-not (Test-Path (Join-Path $Core "gnj_nudge"))) { throw "no core export at $Core" }
New-Item -ItemType Directory -Force -Path $Out | Out-Null
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { throw "port $Port is in use" }
$before = (Get-Item $default).LastWriteTimeUtc
$script = Join-Path $repo "tests\smoke_v9.py"
if ($script.Contains(" ")) { throw "paths with spaces cannot go inside /runscript" }
Get-ChildItem $Out -Filter "v9-*.png" -ErrorAction SilentlyContinue | Remove-Item   # every screenshot is retaken
Get-ChildItem $Out -Filter "tv-*.png" -ErrorAction SilentlyContinue | Remove-Item
$env:GNJ_SMOKE_DIR = $Out
$env:GNJ_SMOKE_PORT = "$Port"
$env:GNJ_CORE_MAIN_DIR = $Core
$env:GNJ_SMOKE_TESTS = $PSScriptRoot
$rhinoArgs = "/nosplash /scheme=$Scheme /runscript=`"_-RunPythonScript $script _-Exit _No`""
$p = Start-Process -FilePath $rhino -ArgumentList $rhinoArgs -PassThru
Write-Output "Rhino pid $($p.Id) scheme $Scheme core $Core port $Port"
if (-not $p.WaitForExit(480000)) { $p.Kill(); Write-Output "TIMED OUT: killed Rhino pid $($p.Id)" }
$after = (Get-Item $default).LastWriteTimeUtc
Write-Output "Rhino pid $($p.Id) exit $($p.ExitCode); Default scheme unchanged: $($before -eq $after) ($before)"
Get-Content (Join-Path $Out "smoke_v9.log")

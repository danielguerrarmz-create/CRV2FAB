# Runs tests/smoke_install.py in a fresh Rhino 7 test instance (/scheme=GNJSmoke) on an empty document.
# Usage (Windows PowerShell 5.1):  powershell -File tests\run_install_smoke.ps1 [outdir] [-Scheme name]
# Rhino 7 only; never Rhino 8; never the Default scheme. Fails if Daniel's Default scheme file changed.
param([string]$Out = (Join-Path $env:TEMP "crv2fab-install-smoke"), [string]$Scheme = "GNJSmoke")
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$rhino = "C:\Program Files\Rhino 7\System\Rhino.exe"
$default = Join-Path $env:APPDATA "McNeel\Rhinoceros\7.0\settings\settings-Scheme__Default.xml"
if ($Scheme -eq "Default") { throw "never the Default scheme" }
New-Item -ItemType Directory -Force -Path $Out | Out-Null
$before = (Get-Item $default).LastWriteTimeUtc
$script = Join-Path $repo "tests\smoke_install.py"
if ($script.Contains(" ")) { throw "paths with spaces cannot go inside /runscript" }
$env:GNJ_SMOKE_DIR = $Out
$rhinoArgs = "/nosplash /scheme=$Scheme /runscript=`"_-RunPythonScript $script _-Exit _No`""
$p = Start-Process -FilePath $rhino -ArgumentList $rhinoArgs -PassThru
if (-not $p.WaitForExit(240000)) { $p.Kill(); Write-Output "TIMED OUT: killed Rhino pid $($p.Id)" }
$after = (Get-Item $default).LastWriteTimeUtc
Write-Output "Rhino pid $($p.Id) exit $($p.ExitCode); scheme $Scheme; Default scheme unchanged: $($before -eq $after) ($before)"
Get-Content (Join-Path $Out "smoke_install.log")

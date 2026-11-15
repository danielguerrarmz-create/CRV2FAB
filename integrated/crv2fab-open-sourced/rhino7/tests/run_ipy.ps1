# Runs tests/ipy_check.py on Rhino 7's IronPython 2.7, without starting Rhino.
# Usage (Windows PowerShell 5.1, it needs .NET Framework):  powershell -File tests\run_ipy.ps1 [logpath]
param([string]$Log = "$env:TEMP\gnj-ipy-check.log")
$ipy = "C:\Program Files\Rhino 7\Plug-ins\IronPython"
$repo = Split-Path -Parent $PSScriptRoot
Add-Type -Path "$ipy\Microsoft.Scripting.dll"
Add-Type -Path "$ipy\Microsoft.Dynamic.dll"
Add-Type -Path "$ipy\IronPython.dll"
Add-Type -Path "$ipy\IronPython.Modules.dll"
$engine = [IronPython.Hosting.Python]::CreateEngine()
$paths = $engine.GetSearchPaths()
$paths.Add("$ipy\Lib")
$engine.SetSearchPaths($paths)
[Environment]::SetEnvironmentVariable("GNJ_REPO", $repo)
[Environment]::SetEnvironmentVariable("GNJ_LOG", $Log)
$engine.ExecuteFile("$repo\tests\ipy_check.py") | Out-Null
Get-Content $Log

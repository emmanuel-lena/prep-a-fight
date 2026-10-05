# prep-a-fight installer for Windows: run install.bat (double-click), or this script from PowerShell.
# Installs uv (Astral's Python installer, which also brings its own Python), prep-a-fight from this folder,
# SimulationCraft, and a desktop shortcut that opens the local web app. Nothing needs admin rights.
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }

Step "uv (Python installer)"
$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uv) {
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
    $uv = Get-Command uv -ErrorAction Stop
}
Write-Host "uv: $($uv.Source)"

Step "prep-a-fight"
& $uv.Source tool install --force --python 3.12 "$here"
if ($LASTEXITCODE -ne 0) { throw "prep-a-fight could not be installed" }
& $uv.Source tool update-shell | Out-Null
$bin = Join-Path $env:USERPROFILE ".local\bin"
$paf = Join-Path $bin "paf.exe"
$app = Join-Path $bin "prep-a-fight.exe"
if (-not (Test-Path $paf)) { $paf = (Get-Command paf -ErrorAction Stop).Source }

Step "SimulationCraft (about 100 MB)"
& $paf setup
if ($LASTEXITCODE -ne 0) { throw "SimulationCraft could not be downloaded" }

Step "Desktop shortcut"
$desktop = [Environment]::GetFolderPath("Desktop")
$link = Join-Path $desktop "prep-a-fight.lnk"
$shell = New-Object -ComObject WScript.Shell
$sc = $shell.CreateShortcut($link)
$sc.TargetPath = $app
$sc.WorkingDirectory = $env:USERPROFILE
$sc.Description = "Prepare a boss fight (local web app)"
$sc.Save()
Write-Host "Shortcut: $link"

Write-Host "`nDone. Double-click 'prep-a-fight' on your desktop." -ForegroundColor Green
Write-Host "It opens in its own window; close the window to stop it."

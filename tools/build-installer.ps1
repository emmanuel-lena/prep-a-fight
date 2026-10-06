# Builds dist/prep-a-fight-setup-<version>.exe: python.org's embeddable Python, the app and its libraries
# (installed by uv for that Python), packed by Inno Setup (installer/prep-a-fight.iss).
# Needs uv and Inno Setup 6 (winget install JRSoftware.InnoSetup --scope user).
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$pyVersion = "3.12.10"  # the last 3.12 with an embeddable build
$cache = Join-Path $root "build\cache"
$app = Join-Path $root "build\app"
$python = Join-Path $app "python"

$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 not found: winget install JRSoftware.InnoSetup --scope user" }
$uv = (Get-Command uv -ErrorAction Stop).Source

New-Item -ItemType Directory -Force $cache | Out-Null
if (Test-Path $app) { Remove-Item -Recurse -Force $app }
New-Item -ItemType Directory -Force $python | Out-Null

$zip = Join-Path $cache "python-$pyVersion-embed-amd64.zip"
if (-not (Test-Path $zip)) {
    Invoke-WebRequest "https://www.python.org/ftp/python/$pyVersion/python-$pyVersion-embed-amd64.zip" -OutFile $zip
}
Expand-Archive $zip -DestinationPath $python
# the embeddable build ignores site-packages unless its ._pth file lists it
$pth = Get-ChildItem $python -Filter "python3*._pth" | Select-Object -First 1
$zipName = (Get-ChildItem $python -Filter "python3*.zip" | Select-Object -First 1).Name
[IO.File]::WriteAllText($pth.FullName, "$zipName`r`n.`r`nLib\site-packages`r`nimport site`r`n")

& $uv pip install --quiet --python $pyVersion --python-platform x86_64-pc-windows-msvc `
    --target (Join-Path $python "Lib\site-packages") $root
if ($LASTEXITCODE -ne 0) { throw "uv could not install the app" }
Copy-Item (Join-Path $root "src\paf\assets\prep-a-fight.ico") $app
# the app keeps its data (preps, caches, SimulationCraft) in <install folder>\data, see paf.config.installed_home
[IO.File]::WriteAllText((Join-Path $app "paf-home.txt"), "data")

$version = [regex]::Match((Get-Content (Join-Path $root "pyproject.toml") -Raw), '(?m)^version\s*=\s*"([^"]+)"').Groups[1].Value
& $iscc /Q "/DAppVersion=$version" (Join-Path $root "installer\prep-a-fight.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
Get-Item (Join-Path $root "dist\prep-a-fight-setup-$version.exe") | Select-Object FullName, @{n = "MB"; e = { [math]::Round($_.Length / 1MB, 1) } }

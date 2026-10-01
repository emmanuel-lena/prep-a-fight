# Build dist/prep-a-fight-<version>.zip from the last commit (git archive: only committed files, so nothing
# personal like .env, CLAUDE.local.md or the caches). Send the zip; the receiver unzips and runs install.bat.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root
$version = (Select-String -Path pyproject.toml -Pattern '^version = "(.+)"').Matches[0].Groups[1].Value
$commit = (git rev-parse --short HEAD).Trim()
New-Item -ItemType Directory -Force dist | Out-Null
$zip = "dist\prep-a-fight-$version-$commit.zip"
git archive --format=zip --prefix=prep-a-fight/ -o $zip HEAD
if ($LASTEXITCODE -ne 0) { throw "git archive failed" }
if (git status --porcelain) { Write-Warning "uncommitted changes are NOT in the zip" }
Write-Host "Bundle: $(Resolve-Path $zip)"

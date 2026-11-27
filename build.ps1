# Build ClockGrid.exe and install it with a Start menu shortcut.
#
#   .\build.ps1             build and install
#   .\build.ps1 -NoInstall  only build (output in %LOCALAPPDATA%\ClockGrid-build\dist)
#
# Installs to %LOCALAPPDATA%\Programs\ClockGrid (no admin rights needed).
# Your data lives separately in %APPDATA%\ClockGrid and is never touched.

param([switch]$NoInstall)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "No .venv found. Create it first: python -m venv .venv; .venv\Scripts\python -m pip install -e .[build]"
}

# Build outside the project folder: it may be synced by OneDrive, which locks
# files mid-build and would upload ~130 MB of build output.
$buildRoot = Join-Path $env:LOCALAPPDATA "ClockGrid-build"
$distDir = Join-Path $buildRoot "dist"

Write-Host "Building ClockGrid..." -ForegroundColor Cyan
& $python -m PyInstaller `
    --noconfirm --clean --windowed `
    --distpath $distDir `
    --workpath (Join-Path $buildRoot "work") `
    --specpath $buildRoot `
    --name ClockGrid `
    --icon "$PSScriptRoot\clockgrid\assets\clockgrid.ico" `
    --add-data "$PSScriptRoot\clockgrid\assets;clockgrid\assets" `
    --paths $PSScriptRoot `
    "$PSScriptRoot\clockgrid\__main__.py"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

if ($NoInstall) {
    Write-Host "Built $distDir\ClockGrid\ClockGrid.exe" -ForegroundColor Green
    exit 0
}

$installDir = Join-Path $env:LOCALAPPDATA "Programs\ClockGrid"
if (Get-Process ClockGrid -ErrorAction SilentlyContinue) {
    throw "ClockGrid is running. Close it, then run this script again."
}
Write-Host "Installing to $installDir..." -ForegroundColor Cyan
if (Test-Path $installDir) { Remove-Item $installDir -Recurse -Force }
Copy-Item (Join-Path $distDir "ClockGrid") $installDir -Recurse

$startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\ClockGrid.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($startMenu)
$shortcut.TargetPath = Join-Path $installDir "ClockGrid.exe"
$shortcut.WorkingDirectory = $installDir
$shortcut.IconLocation = Join-Path $installDir "ClockGrid.exe"
$shortcut.Description = "Track time against your weekly goals"
$shortcut.Save()

Write-Host "Installed. Search for 'ClockGrid' in the Start menu." -ForegroundColor Green

# Build Jarvis Windows package (run on Windows with Python 3.11+)
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\build_exe.ps1

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

Write-Host "==> Installing build deps..."
python -m pip install -U pip wheel
python -m pip install -r requirements.txt
python -m pip install pyinstaller

Write-Host "==> Building with PyInstaller..."
python -m PyInstaller Jarvis.spec --noconfirm --clean

if (-not (Test-Path "dist\Jarvis\Jarvis.exe")) {
    Write-Error "Build failed: dist\Jarvis\Jarvis.exe not found"
}

Write-Host "==> Creating zip..."
$ver = "1.0.0"
if (Test-Path "VERSION") { $ver = (Get-Content VERSION -Raw).Trim() }
$zipName = "Jarvis-Windows-x64-v$ver.zip"
if (Test-Path $zipName) { Remove-Item $zipName -Force }
Compress-Archive -Path "dist\Jarvis\*" -DestinationPath $zipName -Force

Write-Host "Done: $zipName"
Write-Host "Users extract the zip and run Jarvis.exe (Python not required)."

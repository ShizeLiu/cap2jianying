$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot

function Assert-Command($name) {
  if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
    throw ("Command not found: " + $name + ". Please install it and ensure it is in PATH.")
  }
}

Assert-Command python

# Use an isolated venv for stable PyInstaller builds.
# This avoids pulling hooks from a huge conda environment (pandas/pyarrow/scipy/qt, etc.).
$VENV_DIR = ".\\.venv_build"
$VENV_PY = Join-Path $VENV_DIR "Scripts\\python.exe"

Write-Host "==> Preparing isolated venv for build..." -ForegroundColor Cyan
if (-not (Test-Path $VENV_PY)) {
  python -m venv $VENV_DIR
}

Write-Host "==> Installing build deps (pyinstaller) into venv..." -ForegroundColor Cyan
& $VENV_PY -m pip install --upgrade pip
& $VENV_PY -m pip install -r .\requirements-dev.txt

Write-Host "==> Cleaning old artifacts..." -ForegroundColor Cyan
if (Test-Path .\build) { Remove-Item -Recurse -Force .\build }
if (Test-Path .\dist) {
  try {
    Remove-Item -Recurse -Force .\dist
  } catch {
    # Windows 上如果 dist 被资源管理器/残留进程占用，直接删除会失败
    $ts = Get-Date -Format "yyyyMMdd_HHmmss"
    $bak = ".\dist_bak_$ts"
    Write-Host ("dist is locked; renaming to " + $bak) -ForegroundColor Yellow
    try { Move-Item -Force .\dist $bak } catch { }
  }
}
if (Test-Path .\dist_out) {
  try {
    Remove-Item -Recurse -Force .\dist_out
  } catch {
    $ts = Get-Date -Format "yyyyMMdd_HHmmss"
    $bak = ".\dist_out_bak_$ts"
    Write-Host ("dist_out is locked; renaming to " + $bak) -ForegroundColor Yellow
    try { Move-Item -Force .\dist_out $bak } catch { }
  }
}
if (Test-Path .\*.spec) { Remove-Item -Force .\*.spec }

Write-Host "==> Building (onedir)..." -ForegroundColor Cyan

$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$DISTPATH = ".\\dist_out_$ts"

# Notes:
# - onedir: outputs a folder (exe + dlls)
# - windowed: no console window (GUI)
# - ffmpeg is NOT bundled; install ffmpeg on target machines
& $VENV_PY -m PyInstaller `
  --noconfirm `
  --clean `
  --onedir `
  --windowed `
  --distpath $DISTPATH `
  --name "VideoRecorderOnly" `
  --collect-all tkinter `
  --hidden-import difflib `
  --hidden-import asyncio `
  --hidden-import asyncio.events `
  --hidden-import asyncio.base_events `
  --hidden-import pymediainfo `
  --hidden-import uiautomation `
  --hidden-import comtypes `
  --hidden-import win32ctypes `
  --hidden-import pynput `
  --hidden-import pynput.mouse `
  --hidden-import pynput.keyboard `
  --hidden-import jy_wrapper `
  --hidden-import smart_zoomer `
  --hidden-import pyJianYingDraft `
  --add-data "..\scripts;jy_skill\scripts" `
  --add-data "..\assets;jy_skill\assets" `
  --add-data ".\overrides\smart_zoomer.py;jy_skill\overrides" `
  --add-data "..\scripts\vendor\pyJianYingDraft\assets;jy_skill\scripts\vendor\pyJianYingDraft\assets" `
  .\recorder.py

if ($LASTEXITCODE -ne 0) {
  throw ("PyInstaller failed with exit code " + $LASTEXITCODE)
}

Write-Host ""
Write-Host ("Build done: " + (Join-Path $PSScriptRoot (Join-Path $DISTPATH "VideoRecorderOnly"))) -ForegroundColor Green
Write-Host "Tip: zip and distribute the whole folder; target machines must have ffmpeg in PATH." -ForegroundColor Yellow

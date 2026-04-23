$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot

# 打包数据路径：独立仓库为 .\scripts / .\assets；若在 jianying-editor-skill 内则为 ..\scripts
function Resolve-JyScriptsDir {
  $candidates = @(
    (Join-Path $PSScriptRoot "scripts"),
    (Join-Path (Join-Path $PSScriptRoot "..") "scripts")
  )
  foreach ($c in $candidates) {
    $full = [System.IO.Path]::GetFullPath($c)
    if (Test-Path (Join-Path $full "jy_wrapper.py")) {
      return $full
    }
  }
  return $null
}

function Resolve-JyAssetsDir {
  $candidates = @(
    (Join-Path $PSScriptRoot "assets"),
    (Join-Path (Join-Path $PSScriptRoot "..") "assets")
  )
  foreach ($c in $candidates) {
    $full = [System.IO.Path]::GetFullPath($c)
    if (Test-Path $full) {
      return $full
    }
  }
  return $null
}

$SCRIPTS_SRC = Resolve-JyScriptsDir
if (-not $SCRIPTS_SRC) {
  throw "Could not find scripts/ (need jy_wrapper.py). Copy jianying-editor-skill/scripts into ./scripts or place this repo next to that monorepo."
}
$ASSETS_SRC = Resolve-JyAssetsDir
if (-not $ASSETS_SRC) {
  throw "Could not find assets/. Copy jianying-editor-skill/assets into ./assets or use monorepo layout with ../assets."
}
$PJ_DRAFT_ASSETS = Join-Path $SCRIPTS_SRC "vendor\pyJianYingDraft\assets"
if (-not (Test-Path $PJ_DRAFT_ASSETS)) {
  throw ("Missing pyJianYingDraft assets folder: " + $PJ_DRAFT_ASSETS)
}
$SMART_ZOOM_SRC = Join-Path $PSScriptRoot "overrides\smart_zoomer.py"
if (-not (Test-Path $SMART_ZOOM_SRC)) {
  throw ("Missing overrides/smart_zoomer.py: " + $SMART_ZOOM_SRC)
}

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
# 使用命令行参数打包，不依赖每次生成 spec；保留仓库中的 VideoRecorderOnly.spec 供参考

Write-Host "==> Building (onedir)..." -ForegroundColor Cyan

$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$DISTPATH = ".\\dist_out_$ts"
# 避免 PyInstaller 每次在仓库根目录覆盖手写版 VideoRecorderOnly.spec
$SPECPATH_STAGING = Join-Path $PSScriptRoot "build\\pyi_spec_staging"
if (-not (Test-Path $SPECPATH_STAGING)) {
  New-Item -ItemType Directory -Path $SPECPATH_STAGING -Force | Out-Null
}

# Notes:
# - onedir: outputs a folder (exe + dlls)
# - windowed: no console window (GUI)
# - ffmpeg is NOT bundled; install ffmpeg on target machines
& $VENV_PY -m PyInstaller `
  --noconfirm `
  --clean `
  --specpath $SPECPATH_STAGING `
  --onedir `
  --windowed `
  --distpath $DISTPATH `
  --name "VideoRecorderOnly" `
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
  --add-data ($SCRIPTS_SRC + ";jy_skill\scripts") `
  --add-data ($ASSETS_SRC + ";jy_skill\assets") `
  --add-data ($SMART_ZOOM_SRC + ";jy_skill\overrides") `
  --add-data ($PJ_DRAFT_ASSETS + ";jy_skill\scripts\vendor\pyJianYingDraft\assets") `
  .\recorder.py

if ($LASTEXITCODE -ne 0) {
  throw ("PyInstaller failed with exit code " + $LASTEXITCODE)
}

Write-Host ""
Write-Host ("Build done: " + (Join-Path $PSScriptRoot (Join-Path $DISTPATH "VideoRecorderOnly"))) -ForegroundColor Green
Write-Host "Tip: zip and distribute the whole folder; target machines must have ffmpeg in PATH." -ForegroundColor Yellow

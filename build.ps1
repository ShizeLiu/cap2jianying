param(
  [ValidateSet("release", "test")]
  [string]$BuildMode = "",
  [string]$ReleaseVersion = "",
  [switch]$Yes
)

$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot

# 控制台输出统一为 UTF-8（避免中文提示乱码）
try {
  [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
} catch { }

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

# ---------------- 版本与命名（交互式）----------------
# 正式打包：cap2jianying-<version>（例如 cap2jianying-0.1.0）
# 测试打包：cap2jianying-test-<timestamp>
$APP_BASE_NAME = "cap2jianying"
$LAST_RELEASE_FILE = Join-Path $PSScriptRoot "release-version.txt"

function Read-LastReleaseVersion {
  if (Test-Path $LAST_RELEASE_FILE) {
    try {
      $v = (Get-Content -LiteralPath $LAST_RELEASE_FILE -Raw -ErrorAction Stop).Trim()
      if ($v) { return $v }
    } catch { }
  }
  return "0.1.0"
}

function Write-LastReleaseVersion([string]$v) {
  try {
    # 避免写入 UTF-8 BOM（一些工具读出来会多出不可见字符）
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($LAST_RELEASE_FILE, $v, $utf8NoBom)
  } catch { }
}

function Assert-SemVer([string]$v) {
  # 允许 0.1.0 / 1.2.3 / 1.2.3-rc.1
  if ($v -notmatch '^\d+\.\d+\.\d+([\-+][0-9A-Za-z\.\-_]+)?$') {
    throw ("版本号格式不正确（建议语义化版本 SemVer，例如 0.1.1 或 0.1.1-rc.1）： " + $v)
  }
}

$lastRelease = Read-LastReleaseVersion
Write-Host ""
Write-Host "请选择打包类型：" -ForegroundColor Cyan
Write-Host ("  [1] 正式打包（需要输入版本号；上次 release = " + $lastRelease + "）")
Write-Host "  [2] 测试打包（自动时间戳命名）"
$mode = ""
if ($BuildMode -eq "release") {
  $mode = "1"
} elseif ($BuildMode -eq "test") {
  $mode = "2"
} else {
  $mode = (Read-Host "输入 1 或 2").Trim()
  if ($mode -ne "1" -and $mode -ne "2") { $mode = "2" }
}

$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$version = ""
if ($mode -eq "1") {
  if ($ReleaseVersion) {
    $version = $ReleaseVersion.Trim()
  } else {
    $version = (Read-Host ("请输入本次正式版本号（回车默认 " + $lastRelease + "）")).Trim()
    if (-not $version) { $version = $lastRelease }
  }
  Assert-SemVer $version
  $APP_NAME = ($APP_BASE_NAME + "-" + $version)
} else {
  $APP_NAME = ($APP_BASE_NAME + "-test-" + $ts)
}

$DISTPATH = (Join-Path ".\\dist_out" $APP_NAME)

Write-Host ""
Write-Host ("即将开始打包：") -ForegroundColor Cyan
Write-Host ("  - 输出目录: " + (Join-Path $PSScriptRoot $DISTPATH))
Write-Host ("  - EXE 名称: " + $APP_NAME + ".exe")
if (-not $Yes) {
  $confirm = (Read-Host "确认继续？(Y/N)").Trim()
  if ($confirm -notin @("Y","y","YES","yes")) {
    Write-Host "已取消。" -ForegroundColor Yellow
    exit 0
  }
}

Write-Host "==> Building (onedir)..." -ForegroundColor Cyan

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
  --name $APP_NAME `
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
if ($mode -eq "1" -and $version) {
  Write-LastReleaseVersion $version
}

# ---------------- 打包后处理：清理 logs 并生成 zip ----------------
$APP_OUT_DIR = Join-Path $PSScriptRoot (Join-Path $DISTPATH $APP_NAME)

# 将版本更新说明放到产物根目录（与 _internal 同级），并确保 zip 包含它
$RELEASE_NOTES_SRC = Join-Path $PSScriptRoot "更新说明.md"
if (Test-Path $RELEASE_NOTES_SRC) {
  try {
    Copy-Item -Force $RELEASE_NOTES_SRC (Join-Path $APP_OUT_DIR "更新说明.md")
    Write-Host ("Copied release notes: " + $RELEASE_NOTES_SRC) -ForegroundColor DarkGray
  } catch {
    Write-Host ("Warning: failed to copy release notes: " + $RELEASE_NOTES_SRC) -ForegroundColor Yellow
  }
} else {
  Write-Host ("Warning: missing release notes file: " + $RELEASE_NOTES_SRC) -ForegroundColor Yellow
}

# 产物目录里如果存在 logs（通常是运行后生成），release 包不携带它
$LOGS_DIR_IN_APP = Join-Path $APP_OUT_DIR "logs"
if (Test-Path $LOGS_DIR_IN_APP) {
  try {
    Remove-Item -Recurse -Force $LOGS_DIR_IN_APP
    Write-Host ("Removed logs folder: " + $LOGS_DIR_IN_APP) -ForegroundColor DarkGray
  } catch {
    Write-Host ("Warning: failed to remove logs folder: " + $LOGS_DIR_IN_APP) -ForegroundColor Yellow
  }
}

# 在 dist_out 同级生成 zip：dist_out\<APP_NAME>.zip
$DIST_OUT_ROOT = Join-Path $PSScriptRoot ".\\dist_out"
$ZIP_PATH = Join-Path $DIST_OUT_ROOT ($APP_NAME + ".zip")
if (Test-Path $ZIP_PATH) {
  try { Remove-Item -Force $ZIP_PATH } catch { }
}
try {
  Compress-Archive -Path $APP_OUT_DIR -DestinationPath $ZIP_PATH -Force
  Write-Host ("Zip created: " + $ZIP_PATH) -ForegroundColor Green
} catch {
  Write-Host ("Warning: failed to create zip: " + $ZIP_PATH) -ForegroundColor Yellow
}

Write-Host ("Build done: " + $APP_OUT_DIR) -ForegroundColor Green
Write-Host "Tip: zip can be uploaded to Releases; target machines must have ffmpeg in PATH." -ForegroundColor Yellow

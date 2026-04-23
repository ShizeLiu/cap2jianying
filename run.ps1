$ErrorActionPreference = "Stop"

# 始终切到脚本所在目录，避免从其他目录启动时找不到配置/相对路径混乱
Set-Location -LiteralPath $PSScriptRoot

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  Write-Host "未找到 python，请先安装 Python 并确保 python 在 PATH 中。" -ForegroundColor Yellow
  exit 1
}

python .\recorder.py @args

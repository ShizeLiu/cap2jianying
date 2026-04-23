@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo 未找到 python，请先安装 Python 并确保 python 在 PATH 中。
  exit /b 1
)

python "%~dp0recorder.py" %*

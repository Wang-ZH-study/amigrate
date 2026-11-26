@echo off
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo 未找到 python，请安装 Python 3.12 或把 python 加入 PATH。
  pause
  exit /b 1
)
start "amigrate" /min python tools\webui.py
timeout /t 2 >nul
start "" http://127.0.0.1:8800
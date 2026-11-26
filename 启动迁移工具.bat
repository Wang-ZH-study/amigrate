@echo off
chcp 65001 >nul
cd /d "%~dp0"
where pythonw >nul 2>nul
if errorlevel 1 (
  echo 未找到 pythonw，请安装 Python 3.12 或把 Python 加入 PATH。
  pause
  exit /b 1
)
start "" pythonw tools\amigrate_app.py
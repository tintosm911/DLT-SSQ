@echo off
rem ================================================================
rem  Lottery Lab - start Web GUI
rem  Double-click this file, the browser opens automatically.
rem ================================================================
cd /d "%~dp0"
chcp 65001 >nul 2>&1
python scripts\launch_web.py --port 9876
if errorlevel 1 (
  echo.
  echo   Start failed. Check logs\web_gui.log
  pause
)

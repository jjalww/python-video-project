@echo off
rem Double-click this to open the Montage Maker window.
cd /d "%~dp0"
".venv\Scripts\python.exe" app.py
if errorlevel 1 (
  echo.
  echo The app exited with an error. Read the message above.
  pause
)

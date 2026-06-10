@echo off
rem Double-click this to open the Montage Maker window.
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto :run
echo This looks like a fresh download - the app is not set up on this PC yet.
echo Please double-click "Setup (run once).bat" first. It installs everything.
echo.
pause
exit /b 1
:run
".venv\Scripts\python.exe" app.py
if errorlevel 1 (
  echo.
  echo The app exited with an error. Read the message above.
  pause
)

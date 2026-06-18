@echo off
rem First-time setup: installs Python 3.12, the app's packages, FFmpeg, and Deno.
rem Safe to run again any time - it skips whatever is already installed.
setlocal
cd /d "%~dp0"
title Montage Maker - first-time setup
echo ============================================
echo    Montage Maker - first-time setup
echo ============================================
echo This installs everything the app needs. It can take a few
echo minutes and needs an internet connection.
echo.

rem ---- 1/3: Python 3.12 ----
py -3.12 -c "print()" >nul 2>&1
if not errorlevel 1 goto :python_ok
echo [1/4] Python 3.12 is not on this PC yet - installing it now...
winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
if errorlevel 1 goto :python_fail
echo.
echo Python was just installed. Close this window, then double-click
echo "Setup (run once).bat" ONE more time to finish the setup.
echo.
pause
exit /b 0
:python_ok
echo [1/4] Python 3.12 ... OK

rem ---- 2/3: the app's own Python workspace + packages ----
if exist ".venv\Scripts\python.exe" goto :venv_ok
echo [2/4] Creating the app's Python workspace...
py -3.12 -m venv .venv
if errorlevel 1 goto :venv_fail
:venv_ok
echo [2/4] Downloading the app's packages - this is the slow part...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :pip_fail
echo [2/4] Packages ... OK

rem ---- 3/4: FFmpeg (the free video tool that does the cutting) ----
where ffmpeg >nul 2>&1
if not errorlevel 1 goto :ffmpeg_ok
echo [3/4] Installing FFmpeg...
winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
echo NOTE: if the app says FFmpeg is missing later, restart this PC once.
goto :ffmpeg_done
:ffmpeg_ok
echo [3/4] FFmpeg ... OK
:ffmpeg_done

rem ---- 4/4: Deno (lets the song downloader handle YouTube's newer checks) ----
where deno >nul 2>&1
if not errorlevel 1 goto :deno_ok
echo [4/4] Installing Deno (helps download songs from YouTube links)...
winget install -e --id DenoLand.Deno --accept-package-agreements --accept-source-agreements
echo NOTE: Deno is a nice-to-have. If it didn't install, songs you UPLOAD or
echo       already have on the PC still work perfectly.
goto :done
:deno_ok
echo [4/4] Deno ... OK

:done
echo.
echo ============================================
echo    All set! Double-click "Montage Maker.bat" to start.
echo ============================================
pause
exit /b 0

:python_fail
echo.
echo Could not install Python automatically. Please install Python 3.12
echo from python.org, then run this file again.
pause
exit /b 1

:venv_fail
echo.
echo Could not create the app's Python workspace. Run this file again;
echo if it keeps failing, reinstall Python 3.12 from python.org.
pause
exit /b 1

:pip_fail
echo.
echo Package install failed. Check your internet connection and run
echo this file again.
pause
exit /b 1

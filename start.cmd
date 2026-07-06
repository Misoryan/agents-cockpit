@echo off
setlocal
REM Agents Cockpit launcher with auto-restart supervisor loop.
REM app.py os._exits on in-app restart; this loop relaunches it ~2s later.
title Agents Cockpit
cd /d "%~dp0"
:run
python "%~dp0app.py"
echo.
echo [supervisor] Agents Cockpit exited (code %errorlevel%), relaunch in 2s. Close this window to stop.
ping -n 3 127.0.0.1 >nul
goto run

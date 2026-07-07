@echo off
setlocal
REM Agents Cockpit - FOREGROUND launcher with auto-restart supervisor loop.
REM This is the debug variant of start.cmd: it runs the supervisor loop IN THIS
REM WINDOW so you see live output (banner, errors, relaunch messages). Use
REM start.cmd for normal background running (window closes, service stays up).
REM
REM app.py os._exits on in-app restart; this loop relaunches it ~2s later.
REM
REM Intentional full-stop signals (do NOT relaunch):
REM   * exit code 42                        - web exited via /api/_stop (run stop.cmd)
REM   * .agent-cockpit\stop.sentinel        - written by stop.cmd when web is unreachable
REM
REM NOTE: keep this file pure ASCII - cmd.exe parses it in the OEM codepage,
REM so non-ASCII bytes (e.g. Chinese in UTF-8) mojibake or break parsing.
REM Chinese explanations live in README.md; rich console output is from Python.
title Agents Cockpit (foreground)
cd /d "%~dp0"
REM clear any sentinel left by a previous stop so a fresh start isn't blocked
if exist "%~dp0.agent-cockpit\stop.sentinel" del "%~dp0.agent-cockpit\stop.sentinel" >nul 2>&1

:run
REM honor a stop request written mid-loop (web already dead, exit 42 can't fire)
if exist "%~dp0.agent-cockpit\stop.sentinel" (
    del "%~dp0.agent-cockpit\stop.sentinel" >nul 2>&1
    echo [supervisor] stop sentinel found - exiting.
    goto :eof
)
python "%~dp0app.py"
set EC=%errorlevel%
if "%EC%"=="42" echo [supervisor] intentional stop - exiting. & goto :eof
echo.
echo [supervisor] Agents Cockpit exited (code %EC%), relaunch in 2s.
echo [supervisor] Close this window, or run stop.cmd to stop completely.
ping -n 3 127.0.0.1 >nul
goto run

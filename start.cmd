@echo off
setlocal
REM Agents Cockpit - BACKGROUND launcher.
REM Detaches a HIDDEN supervisor (run_bg.vbs -> python supervisor.py) that owns
REM the web relaunch loop, then THIS WINDOW CLOSES IMMEDIATELY. The service keeps
REM running in the background after the window is closed (survives window close
REM and RDP disconnect). run stop.cmd to stop it fully; start-fg.cmd to debug.
REM
REM NOTE: keep this file pure ASCII - cmd.exe parses it in the OEM codepage,
REM so non-ASCII bytes (e.g. Chinese in UTF-8) mojibake or break parsing.
cd /d "%~dp0"
REM clear any sentinel left by a previous stop so a fresh start isn't blocked
if exist "%~dp0.agent-cockpit\stop.sentinel" del "%~dp0.agent-cockpit\stop.sentinel" >nul 2>&1

REM quick "already running?" probe on the web port (sub-second; no bins/auth needed)
python "%~dp0app.py" --is-running >nul 2>&1
if not errorlevel 1 (
    echo Agents Cockpit is already running in the background.
    echo Run stop.cmd to stop it, or start-fg.cmd to view live logs.
    ping -n 4 127.0.0.1 >nul
    goto :eof
)

REM detach: wscript launches python supervisor.py hidden and returns at once
wscript "%~dp0run_bg.vbs"
echo Agents Cockpit started in the background.
echo - Stop:    run stop.cmd          Debug: run start-fg.cmd
echo - Logs:    .agent-cockpit\web.log
ping -n 3 127.0.0.1 >nul
endlocal
exit

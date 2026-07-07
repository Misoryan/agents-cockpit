@echo off
setlocal
REM Agents Cockpit - full stop (works for both background and foreground mode).
REM Stops web + manager + all ttyd/codex/claude sessions, and tells the
REM background supervisor (if any) to stop relaunching.
REM (keep this file pure ASCII - cmd.exe parses it in the OEM codepage)
cd /d "%~dp0"
python "%~dp0app.py" --stop
echo.
echo If a port is still reported busy above, the service runs in the
echo background with no window. End any leftover python.exe in Task Manager
echo (its PID is in .agent-cockpit\supervisor.pid), or run stop.cmd again.
echo.
pause
endlocal

@echo off
setlocal
REM Codex-Web launcher (web only; manager keeps Codex sessions alive)
title Codex Web
cd /d "%~dp0"
python "%~dp0app.py"
echo.
echo Codex Web exited. Press any key to close...
pause >nul

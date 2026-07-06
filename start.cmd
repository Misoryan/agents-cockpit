@echo off
REM === Codex-Web launcher (picker + auto ttyd) ===
REM Opens a folder picker on http://<lan-ip>:7680 ; after you pick a folder it
REM launches codex (via ttyd) on http://<lan-ip>:7681 in that folder.
title Codex Web
python "%~dp0app.py"
echo.
echo Codex Web 已退出。按任意键关闭...
pause >nul

#!/usr/bin/env bash
# Linux / macOS 启动脚本(带自动重启监督循环,与 start.cmd 对齐)。
# Windows 请用 start.cmd。
cd "$(dirname "$0")"
while true; do
  python3 app.py
  echo "[supervisor] Agent Cockpit exited (code $?), relaunch in 2s. Ctrl+C 或关闭本终端停止。"
  sleep 2
done

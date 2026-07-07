#!/usr/bin/env bash
# Agents Cockpit - full stop (works for both background and foreground mode).
cd "$(dirname "$0")"
python3 app.py --stop
echo
echo "If a port is still reported busy above, the service runs in the background"
echo "with no terminal. Its PID is in .agent-cockpit/supervisor.pid"
echo "(or: ps aux | grep -E 'supervisor.py|app.py'), kill it or run stop.sh again."

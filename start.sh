#!/usr/bin/env bash
# Agents Cockpit - BACKGROUND launcher (POSIX: Linux/macOS).
# Detaches the supervisor (setsid / nohup -> python3 supervisor.py) which owns
# the web relaunch loop, then this script exits. The service keeps running after
# the terminal closes. run stop.sh to stop fully; start-fg.sh to debug live.
cd "$(dirname "$0")"
SENTINEL=".agent-cockpit/stop.sentinel"
rm -f "$SENTINEL" 2>/dev/null   # clear stale sentinel from a prior stop

# quick "already running?" probe on the web port
if python3 app.py --is-running >/dev/null 2>&1; then
    echo "Agents Cockpit is already running in the background."
    echo "Run stop.sh to stop it, or see .agent-cockpit/web.log."
    exit 0
fi

# detach into a new session with no controlling terminal.
# setsid (Linux) fully detaches into a new session; macOS lacks setsid, so fall
# back to nohup + disown (ignore SIGHUP, drop from the shell job table).
if command -v setsid >/dev/null 2>&1; then
    setsid python3 supervisor.py </dev/null >/dev/null 2>&1 &
else
    nohup python3 supervisor.py </dev/null >/dev/null 2>&1 &
    disown 2>/dev/null
fi

echo "Agents Cockpit started in the background."
echo "- Stop: run stop.sh          Logs: .agent-cockpit/web.log"

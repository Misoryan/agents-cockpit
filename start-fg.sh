#!/usr/bin/env bash
# Agents Cockpit - FOREGROUND launcher with auto-restart supervisor loop.
# This is the debug variant of start.sh: it runs the loop IN THIS TERMINAL so
# you see live output (banner, errors, relaunch messages). Use start.sh for
# normal background running (terminal closes, service stays up).
#
# Full-stop signals (do NOT relaunch):
#   * exit code 42                  - web exited via /api/_stop (run stop.sh)
#   * .agent-cockpit/stop.sentinel  - written by stop.sh when web is unreachable
cd "$(dirname "$0")"
SENTINEL=".agent-cockpit/stop.sentinel"
rm -f "$SENTINEL" 2>/dev/null   # clear any stale sentinel from a prior stop
cleanup() { kill 0 2>/dev/null; }   # Ctrl+C: kill the whole process group (web + manager)
trap cleanup INT TERM
while true; do
  if [ -f "$SENTINEL" ]; then rm -f "$SENTINEL"; echo "[supervisor] stop sentinel found - exiting."; exit 0; fi
  python3 app.py
  EC=$?
  if [ "$EC" = "42" ]; then echo "[supervisor] intentional stop, exiting."; exit 0; fi
  echo "[supervisor] Agents Cockpit exited (code $EC), relaunch in 2s. Ctrl+C or run stop.sh to stop."
  sleep 2
done

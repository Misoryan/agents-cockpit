# -*- coding: utf-8 -*-
"""
Agents Cockpit detached supervisor (Windows background; POSIX portable).

Mirrors the old start.cmd :run loop, but runs with NO console so it survives
window close / RDP disconnect: start.cmd launches us hidden via run_bg.vbs
(`wscript ... , 0, False`), and we own the web relaunch loop in the background.
start-fg.cmd runs the same loop in a visible window for debugging.

Lifecycle:
  * idempotency: take supervisor.lock (O_CREAT|O_EXCL); if it already exists,
    probe the web port -- alive means another instance owns it (exit 0), dead
    means a crashed supervisor left a stale lock (take it over).
  * write supervisor.pid so common.perform_shutdown can kill us as a last resort.
  * clear any stale stop.sentinel so a fresh start isn't blocked.
  * loop:
      - top-of-loop: honor stop.sentinel (web-unreachable stop path) and re-probe
        the port (second-instance guard).
      - Popen [python, app.py] with stdout/stderr -> web.log, CREATE_NO_WINDOW on
        Windows; wait().
      - exit code 42 -> intentional stop -> exit 0.
      - else sleep ~2s and relaunch; track consecutive fast failures -> give up
        (so a broken install doesn't hot-loop a hidden process forever).
  * cleanup lock/pid in finally.

Deliberately does NOT import common: common.py sys.exit(1)s at import time on a
broken install (missing claude or empty auth.txt). The supervisor is
the bootstrap layer and must be the most robust file in the project -- it must
never die from a broken install. It hardcodes the handful of constants it needs
and reads [server] port from config.ini directly.
"""
import os
import sys
import time
import socket
import subprocess
import configparser

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(HERE, ".agent-cockpit")
STOP_SENTINEL = os.path.join(STATE_DIR, "stop.sentinel")
WEB_LOG = os.path.join(STATE_DIR, "web.log")
SUP_LOCK = os.path.join(STATE_DIR, "supervisor.lock")
SUP_PID = os.path.join(STATE_DIR, "supervisor.pid")
SUP_GIVEUP = os.path.join(STATE_DIR, "supervisor.giveup")
CREATE_NO_WINDOW = 0x08000000
RESTART_DELAY = 2.0
WEB_STOP_EXIT_CODE = 42
DEFAULT_PORT = 7682
MAX_CONSEC_FAILURES = 10        # consecutive fast failures before giving up
GIVEUP_WINDOW = 30.0            # ...only counted if they happen within this window (s)


def _picker_port():
    """Read [server] port from config.ini (default 7682). Mirrors common.PICKER_PORT
    without importing common (which has heavy import-time side effects)."""
    try:
        cp = configparser.ConfigParser(interpolation=None)
        cp.read(os.path.join(HERE, "config.ini"), encoding="utf-8")
        return cp.getint("server", "port") or DEFAULT_PORT
    except Exception:
        return DEFAULT_PORT


def _port_alive(port, timeout=0.5):
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout)
        s.close()
        return True
    except OSError:
        return False


def _log(fout, msg):
    """Best-effort timestamped line into web.log (the same file web's stdout ->)."""
    if not fout:
        return
    try:
        line = ("[%s] [supervisor] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
        fout.write(line.encode("utf-8"))
        fout.flush()
    except OSError:
        pass


def _acquire_lock():
    """Atomically take supervisor.lock. Returns True if we created/own it.

    If the lock already exists: another instance may be running -- if the web
    port is alive, yield (exit); if the port is dead, the lock is stale (a
    crashed supervisor) and we take it over. Returns False if we should exit
    (a live instance already owns the port, or we lost a takeover race)."""
    try:
        fd = os.open(SUP_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except OSError:
        pass
    # lock exists -- decide stale vs live by probing the web port
    if _port_alive(_picker_port()):
        return False
    try:
        os.unlink(SUP_LOCK)
        fd = os.open(SUP_LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except OSError:
        return False


def _cleanup(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def main():
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
    except OSError:
        pass

    if not _acquire_lock():
        # already running (or lost a race) -- silent exit
        return 0

    _cleanup(SUP_GIVEUP)   # clear a giveup marker from a previous run

    # publish our pid so common.perform_shutdown can kill us as a last resort
    try:
        with open(SUP_PID, "w") as f:
            f.write(str(os.getpid()))
    except OSError:
        pass

    # clear any stop sentinel left by a previous stop so a fresh start isn't blocked
    _cleanup(STOP_SENTINEL)

    # one log handle for the whole supervisor lifetime; reused across web relaunches
    # (append -- never truncate, so debug history survives restarts)
    try:
        fout = open(WEB_LOG, "ab")
    except OSError:
        fout = None

    # Force UTF-8 on the child's redirected stdout/stderr. On Windows a redirected
    # file defaults to the OEM/ANSI codepage and the Chinese prints in web.py /
    # common.py (e.g. "控制台端口") raise UnicodeEncodeError. This is the
    # load-bearing fix for background mode.
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    popen_kwargs = {"cwd": HERE, "stdout": fout, "stderr": subprocess.STDOUT, "env": env}
    if os.name == "nt":
        popen_kwargs["creationflags"] = CREATE_NO_WINDOW

    consec = 0
    first_fail_at = 0.0
    try:
        while True:
            # honor a stop request written mid-loop (web already dead, exit 42 can't fire)
            if os.path.isfile(STOP_SENTINEL):
                _cleanup(STOP_SENTINEL)
                _log(fout, "stop sentinel found - exiting")
                break
            # second-instance guard: if something now owns the web port, exit
            if _port_alive(_picker_port()):
                _log(fout, "web port already in use - another instance is running; exiting")
                break

            _log(fout, "launching python app.py")
            try:
                p = subprocess.Popen([sys.executable, os.path.join(HERE, "app.py")], **popen_kwargs)
            except OSError as e:
                _log(fout, "Popen failed: %s" % e)
                time.sleep(RESTART_DELAY)
                continue

            ec = p.wait()
            _log(fout, "app.py exited code=%d" % ec)

            if ec == WEB_STOP_EXIT_CODE:
                _log(fout, "intentional stop (exit 42) - exiting")
                break

            # failure tracking: only give up on a tight cluster of fast failures
            # (a broken install that sys.exit(1)s on every launch). A web that ran
            # for a while before crashing resets the window and never gives up.
            now = time.time()
            if first_fail_at == 0.0:
                first_fail_at = now
            if now - first_fail_at > GIVEUP_WINDOW:
                consec = 0
                first_fail_at = now
            consec += 1
            if consec >= MAX_CONSEC_FAILURES:
                _log(fout, "giving up after %d consecutive failures - check web.log / install" % consec)
                try:
                    with open(SUP_GIVEUP, "w") as g:
                        g.write("giveup after %d consecutive failures\n" % consec)
                except OSError:
                    pass
                break

            _log(fout, "relaunch in %ds" % int(RESTART_DELAY))
            time.sleep(RESTART_DELAY)
    finally:
        _cleanup(SUP_LOCK)
        _cleanup(SUP_PID)
        if fout:
            try:
                fout.close()
            except OSError:
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

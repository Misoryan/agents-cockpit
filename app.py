# -*- coding: utf-8 -*-
"""
Agents Cockpit entry point.

Single launcher kept for compatibility with start.cmd (`python app.py`). It just
picks web vs manager mode from argv and delegates:

  python app.py            -> web.py     (serves index.html + proxies to manager)
  python app.py --manager  -> manager.py (owns web-rendered agent sessions)
  python app.py --stop     -> common.perform_shutdown()
                                (fully stop a running Cockpit: web + manager +
                                 every session; tells the supervisor to stop too)
  python app.py --help     -> this text

All shared infra lives in common.py.
importing common runs env/bin/auth resolution (and may sys.exit on misconfig —
except in --stop / --help mode, which must work even on a broken install).
"""
import sys

import common  # noqa: F401  (resolves bins + auth at import; side effects intentional)


def main():
    if "--help" in sys.argv or "-h" in sys.argv:
        print("Agents Cockpit")
        print("Usage: python app.py [--manager | --stop | --help]")
        print("  (no flag)  web layer — serves the console and proxies to the manager")
        print("  --manager  manager layer — owns web-rendered agent sessions")
        print("  --stop     fully stop a running Agents Cockpit (web + manager + all")
        print("             sessions); also signals the supervisor to stop relaunching")
        return
    if "--is-running" in sys.argv:
        # background-mode probe (used by start.cmd / supervisor to detect a live
        # instance). Safe path: works without bins/auth (no sys.exit at import).
        running = common._port_alive(common.PICKER_PORT)
        print("running" if running else "not running")
        sys.exit(0 if running else 1)
    if "--stop" in sys.argv:
        result = common.perform_shutdown()
        print("[stop] web port (%d) free: %s"
              % (common.PICKER_PORT, result["web_port_free"]))
        print("[stop] manager port (%d) free: %s"
              % (common.MANAGER_PORT, result["manager_port_free"]))
        if result["web_port_free"] and result["manager_port_free"]:
            print("[stop] Agents Cockpit 已完全停止。")
        else:
            print("[stop] 仍有端口被占用 —— 可能有残留进程。请关闭 start.cmd 窗口,")
            print("       或在任务管理器里结束 python.exe。")
        return
    if common.RUN_MODE == "manager":
        import manager
        manager.run()
    else:
        import web
        web.run()


if __name__ == "__main__":
    main()

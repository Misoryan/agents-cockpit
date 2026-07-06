# -*- coding: utf-8 -*-
"""
Agent Cockpit entry point.

Single launcher kept for compatibility with start.cmd (`python app.py`). It just
picks web vs manager mode from argv and delegates:

  python app.py            -> web.py  (serves index.html + proxies to manager)
  python app.py --manager  -> manager.py (owns the codex/claude ttyd sessions)

All shared infra lives in common.py; the terminal multiplexer in hub.py.
importing common runs env/bin/auth resolution (and may sys.exit on misconfig).
"""
import sys

import common  # noqa: F401  (resolves bins + auth at import; side effects intentional)


def main():
    if common.RUN_MODE == "manager":
        import manager
        manager.run()
    else:
        import web
        web.run()


if __name__ == "__main__":
    main()

"""Check manager HTTP routing stays split by audience."""
import inspect
import sys
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import manager  # noqa: E402


def main():
    assert manager._INTERNAL_GATE_POSTS == {"/api/_perm_gate", "/api/_ask_gate"}
    assert manager._INTERNAL_CONTROL_POSTS == {"/api/_exit", "/api/_soft_exit"}

    handler = manager.ManagerHandler
    for name in (
        "_handle_internal_gate",
        "_handle_internal_control",
        "_handle_user_get",
        "_handle_user_post",
        "_serve_session",
        "_native_ws_handshake",
    ):
        assert hasattr(handler, name), name

    do_get = inspect.getsource(handler.do_GET)
    do_post = inspect.getsource(handler.do_POST)
    assert "_serve_session" in do_get
    assert "_handle_user_get" in do_get
    assert "_handle_internal_control" in do_post
    assert "_handle_internal_gate" in do_post
    assert "_handle_user_post" in do_post
    assert "/api/nsend" not in do_post

    print("manager routing boundary checks passed")


if __name__ == "__main__":
    main()

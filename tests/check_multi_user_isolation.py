"""Lightweight multi-user isolation checks for Agents Cockpit.

Run from the repository root:
    python tests/check_multi_user_isolation.py
"""
import os
import sys
import tempfile
from pathlib import Path

# Let common.py import without requiring local auth.txt or CLI binaries.
if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import common  # noqa: E402
import codex_native  # noqa: E402
import manager  # noqa: E402


class FakeNative:
    alive = True
    yolo = False
    claude_sid = None
    thread_id = None
    last_activity = 1
    convo_title = "fake"

    def state(self):
        return "idle"


def main():
    with tempfile.TemporaryDirectory() as td:
        old_users = common.USERS
        old_user_data_dir = common.USER_DATA_DIR
        old_default_root = common.DEFAULT_WORKSPACE_ROOT
        old_allow = common.ALLOW_UNCONFIGURED_PATHS
        old_primary_homes = common.PRIMARY_USER_USES_DEFAULT_HOMES
        old_sessions = dict(manager.sessions)
        try:
            common.USERS = {"alice": "pw", "bob": "pw"}
            common.USER_DATA_DIR = os.path.join(td, "users")
            common.DEFAULT_WORKSPACE_ROOT = os.path.join(td, "users", "{uid}", "workspace")
            common.ALLOW_UNCONFIGURED_PATHS = False
            common.PRIMARY_USER_USES_DEFAULT_HOMES = False
            manager.sessions.clear()

            alice = common.user_context("alice")
            bob = common.user_context("bob")
            assert alice and bob and alice["uid"] != bob["uid"]
            assert alice["state_dir"] != bob["state_dir"]
            assert alice["claude_home"].startswith(alice["state_dir"])
            assert bob["claude_home"].startswith(bob["state_dir"])
            assert alice["codex_home"].startswith(alice["state_dir"])
            assert bob["codex_home"].startswith(bob["state_dir"])
            assert os.path.isdir(alice["workspace_roots"][0])
            assert common.path_allowed_for_user("alice", alice["workspace_roots"][0])
            assert not common.path_allowed_for_user("alice", bob["workspace_roots"][0])

            manager.sessions["s1"] = {
                "user": "alice",
                "uid": alice["uid"],
                "state_dir": alice["state_dir"],
                "dir": alice["workspace_roots"][0],
                "title": "a",
                "mode": "new",
                "backend": "claude_native",
                "provider": "claude",
                "started": 1,
                "native": FakeNative(),
            }
            manager.sessions["s2"] = {
                "user": "bob",
                "uid": bob["uid"],
                "state_dir": bob["state_dir"],
                "dir": bob["workspace_roots"][0],
                "title": "b",
                "mode": "new",
                "backend": "claude_native",
                "provider": "claude",
                "started": 2,
                "native": FakeNative(),
            }

            handler = object.__new__(manager.ManagerHandler)
            assert handler._owned_session("s1", alice)["user"] == "alice"
            assert handler._owned_session("s2", alice) is None

            common.registry_upsert("s1", {"dir": alice["workspace_roots"][0], "user": "alice"}, state_dir=alice["state_dir"])
            common.registry_upsert("s2", {"dir": bob["workspace_roots"][0], "user": "bob"}, state_dir=bob["state_dir"])
            assert "s1" in common.registry_load(state_dir=alice["state_dir"])["sessions"]
            assert "s2" not in common.registry_load(state_dir=alice["state_dir"])["sessions"]

            ca = codex_native.get_app_client(user="alice", uid=alice["uid"], state_dir=alice["state_dir"])
            cb = codex_native.get_app_client(user="bob", uid=bob["uid"], state_dir=bob["state_dir"])
            assert ca is not cb
            assert ca.codex_home != cb.codex_home
            assert ca.codex_home.startswith(alice["state_dir"])
            assert cb.codex_home.startswith(bob["state_dir"])

            common.PRIMARY_USER_USES_DEFAULT_HOMES = True
            alice_default = common.user_context("alice")
            bob_isolated = common.user_context("bob")
            assert alice_default["uses_default_homes"]
            assert alice_default["codex_home"] == ""
            assert alice_default["claude_home"] == os.path.abspath(common.CLAUDE_HOME)
            assert not bob_isolated["uses_default_homes"]
            assert bob_isolated["codex_home"].startswith(bob_isolated["state_dir"])
            assert bob_isolated["claude_home"].startswith(bob_isolated["state_dir"])
            print("multi-user isolation checks passed")
        finally:
            common.USERS = old_users
            common.USER_DATA_DIR = old_user_data_dir
            common.DEFAULT_WORKSPACE_ROOT = old_default_root
            common.ALLOW_UNCONFIGURED_PATHS = old_allow
            common.PRIMARY_USER_USES_DEFAULT_HOMES = old_primary_homes
            manager.sessions.clear()
            manager.sessions.update(old_sessions)
            codex_native.shutdown_app_server()


if __name__ == "__main__":
    main()

"""Check per-user/workspace helpers after extracting them from common.py."""
import os
import sys
import tempfile
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import common  # noqa: E402
import common_users  # noqa: E402


class FakeHandler:
    def __init__(self, headers):
        self.headers = headers


def main():
    with tempfile.TemporaryDirectory() as td:
        settings = common_users.UserSettings(
            base_dir=td,
            user_data_dir=os.path.join(td, "users"),
            default_workspace_root=os.path.join("workspaces", "{uid}"),
            allow_unconfigured_paths=False,
            primary_user_uses_default_homes=True,
            claude_home=os.path.join(td, ".claude"),
            users={"alice": "pw", "bob": "pw"},
        )

        alice_uid = common_users.safe_user_id("alice")
        assert alice_uid.startswith("alice-")
        alice = common_users.user_context("alice", settings)
        bob = common_users.user_context("bob", settings)
        assert alice and bob
        assert alice["uid"] != bob["uid"]
        assert alice["state_dir"].startswith(settings.user_data_dir)
        assert alice["uses_default_homes"] is True
        assert bob["uses_default_homes"] is False
        assert alice["claude_home"] == os.path.abspath(settings.claude_home)
        assert bob["claude_home"].startswith(bob["state_dir"])
        assert bob["codex_home"].startswith(bob["state_dir"])
        assert os.path.isdir(alice["workspace_roots"][0])

        assert common_users.path_allowed_for_user("alice", alice["workspace_roots"][0], settings)
        assert not common_users.path_allowed_for_user("alice", bob["workspace_roots"][0], settings)
        overview = common_users.workspace_overview("alice", settings)
        assert overview and overview[0]["path"] == alice["workspace_roots"][0]

        assert common_users.request_user(
            FakeHandler({"X-Agent-Cockpit-User": "alice"}), settings, lambda _tok: None
        ) == "alice"
        assert common_users.request_user(
            FakeHandler({"Cookie": "x=1; ac_session=tok"}), settings, lambda tok: "bob" if tok == "tok" else None
        ) == "bob"

        old = {
            "USERS": common.USERS,
            "USER_DATA_DIR": common.USER_DATA_DIR,
            "DEFAULT_WORKSPACE_ROOT": common.DEFAULT_WORKSPACE_ROOT,
            "ALLOW_UNCONFIGURED_PATHS": common.ALLOW_UNCONFIGURED_PATHS,
            "PRIMARY_USER_USES_DEFAULT_HOMES": common.PRIMARY_USER_USES_DEFAULT_HOMES,
            "CLAUDE_HOME": common.CLAUDE_HOME,
        }
        try:
            common.USERS = {"alice": "pw", "bob": "pw"}
            common.USER_DATA_DIR = os.path.join(td, "common-users")
            common.DEFAULT_WORKSPACE_ROOT = os.path.join(td, "common-work", "{uid}")
            common.ALLOW_UNCONFIGURED_PATHS = False
            common.PRIMARY_USER_USES_DEFAULT_HOMES = True
            common.CLAUDE_HOME = os.path.join(td, "common-claude")

            ca = common.user_context("alice")
            cb = common.user_context("bob")
            assert ca["uses_default_homes"] is True
            assert cb["uses_default_homes"] is False
            assert common.path_allowed_for_user("alice", ca["workspace_roots"][0])
            assert not common.path_allowed_for_user("alice", cb["workspace_roots"][0])
            assert common.workspace_overview("alice")[0]["path"] == ca["workspace_roots"][0]
        finally:
            for key, value in old.items():
                setattr(common, key, value)

    print("common user helper checks passed")


if __name__ == "__main__":
    main()

"""Check folder browsing and session projection helpers after extraction."""
import os
import sys
import tempfile
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import common  # noqa: E402
import common_browse  # noqa: E402


class FakeNative:
    def __init__(self):
        self.thread_id = "thread-1"
        self.convo_title = "Native title"
        self.last_activity = 123.5
        self.last_completed_at = 120.0
        self.current_turn_started_at = 119.0
        self.yolo = True

    def state(self):
        return "running"


class FakeIdleNative(FakeNative):
    def __init__(self):
        super().__init__()
        self.last_activity = 999.0
        self.last_completed_at = 120.0

    def state(self):
        return "idle"


def main():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td, "root")
        sub = root / "sub"
        other = root / "other"
        file_path = root / "file.txt"
        sub.mkdir(parents=True)
        other.mkdir()
        file_path.write_text("not listed", encoding="utf-8")

        assert common_browse.parent_of("") == ""
        assert common_browse.parent_of(str(root)) == str(root.parent)

        browsed = common_browse.browse(str(root))
        names = [entry["name"] for entry in browsed["entries"]]
        assert names == ["other", "sub"]
        assert browsed["path"] == os.path.abspath(str(root))
        assert browsed["parent"] == str(root.parent)

        denied = common_browse.browse(
            str(root),
            user="alice",
            path_allowed_fn=lambda _user, _path: False,
        )
        assert denied["error"] == "path is outside this user's workspaces"

        only_sub = os.path.abspath(str(sub))
        sub_view = common_browse.browse(
            str(sub),
            user="alice",
            path_allowed_fn=lambda _user, path: os.path.abspath(path) == only_sub,
        )
        assert sub_view["path"] == only_sub
        assert sub_view["parent"] == ""

        roots = [{"name": "Workspace", "path": str(root), "kind": "workspace"}]
        root_view = common_browse.browse(
            "",
            user="alice",
            workspace_overview_fn=lambda user: roots if user == "alice" else [],
        )
        assert root_view == {"path": "", "parent": "", "entries": roots, "roots": roots}

        missing = common_browse.browse(str(root / "missing"))
        assert missing["error"] == "not a directory"

        projected = common_browse.session_obj(
            "sid-1",
            {
                "dir": str(root),
                "title": "Stored title",
                "mode": "normal",
                "started": 42,
                "backend": "codex_native",
                "native": FakeNative(),
            },
            normalize_backend_fn=lambda backend: backend or "claude_native",
            is_codex_backend_fn=lambda backend: backend == "codex_native",
        )
        assert projected["sid"] == "sid-1"
        assert projected["title"] == "Native title"
        assert projected["provider"] == "codex"
        assert projected["session_id"] == "thread-1"
        assert projected["state"] == "running"
        assert projected["yolo"] is True
        assert projected["current_turn_started_at"] == 119.0
        assert projected["last_completed_at"] == 120.0
        assert projected["last_output_ts"] == 123.5

        idle_projected = common_browse.session_obj(
            "sid-idle",
            {
                "dir": str(root),
                "title": "Idle",
                "mode": "normal",
                "started": 42,
                "backend": "codex_native",
                "native": FakeIdleNative(),
            },
            normalize_backend_fn=lambda backend: backend or "claude_native",
            is_codex_backend_fn=lambda backend: backend == "codex_native",
        )
        assert idle_projected["state"] == "idle"
        assert idle_projected["last_input_ts"] == 999.0
        assert idle_projected["last_output_ts"] == 120.0

        fallback = common_browse.session_obj(
            "sid-2",
            {
                "dir": str(root),
                "title": "Fallback",
                "mode": "normal",
                "started": 43,
                "session_id": "stored-session",
                "yolo": True,
            },
            normalize_backend_fn=lambda backend: backend or "claude_native",
            is_codex_backend_fn=lambda backend: backend == "codex_native",
        )
        assert fallback["backend"] == "claude_native"
        assert fallback["provider"] == "claude"
        assert fallback["session_id"] == "stored-session"
        assert fallback["state"] == "idle"
        assert fallback["yolo"] is True

        old = {
            "USERS": common.USERS,
            "USER_DATA_DIR": common.USER_DATA_DIR,
            "DEFAULT_WORKSPACE_ROOT": common.DEFAULT_WORKSPACE_ROOT,
            "ALLOW_UNCONFIGURED_PATHS": common.ALLOW_UNCONFIGURED_PATHS,
        }
        try:
            common.USERS = {"alice": "pw"}
            common.USER_DATA_DIR = os.path.join(td, "users")
            common.DEFAULT_WORKSPACE_ROOT = os.path.join(td, "workspaces", "{uid}")
            common.ALLOW_UNCONFIGURED_PATHS = False
            workspace = common.user_context("alice")["workspace_roots"][0]
            assert common.browse("", user="alice")["roots"][0]["path"] == workspace
            assert common.browse(workspace, user="alice")["path"] == os.path.abspath(workspace)
            assert common.browse(str(root), user="alice")["error"] == "path is outside this user's workspaces"
        finally:
            for key, value in old.items():
                setattr(common, key, value)

    print("common browse helper checks passed")


if __name__ == "__main__":
    main()

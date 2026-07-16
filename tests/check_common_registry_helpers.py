"""Check persisted session registry helpers after extraction."""
import os
import sys
import tempfile
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import common  # noqa: E402
import common_registry  # noqa: E402


def main():
    with tempfile.TemporaryDirectory() as td:
        settings = common_registry.RegistrySettings(
            registry_path=os.path.join(td, "sessions.json"),
            scrollback_dir=os.path.join(td, "scrollback"),
            user_state_dir=lambda user: os.path.join(td, "users", user),
        )

        assert common_registry.registry_path(settings=settings) == settings.registry_path
        assert common_registry.registry_path(user="alice", settings=settings).endswith(
            os.path.join("users", "alice", "sessions.json")
        )
        explicit_state = os.path.join(td, "state")
        assert common_registry.registry_path(state_dir=explicit_state, settings=settings).endswith("sessions.json")

        common_registry.registry_save({"s1": {"dir": "a"}}, 123, settings=settings)
        reg = common_registry.registry_load(settings=settings)
        assert reg["manager_pid"] == 123
        assert reg["sessions"]["s1"]["dir"] == "a"

        common_registry.registry_upsert("s2", {"dir": "b"}, 456, settings=settings)
        reg = common_registry.registry_load(settings=settings)
        assert reg["manager_pid"] == 456
        assert set(reg["sessions"]) == {"s1", "s2"}

        os.makedirs(settings.scrollback_dir, exist_ok=True)
        Path(settings.scrollback_dir, "s2.log").write_text("old", encoding="utf-8")
        common_registry.registry_drop("s2", settings=settings)
        reg = common_registry.registry_load(settings=settings)
        assert set(reg["sessions"]) == {"s1"}
        assert not Path(settings.scrollback_dir, "s2.log").exists()

        common_registry.registry_clear(789, settings=settings)
        reg = common_registry.registry_load(settings=settings)
        assert reg["manager_pid"] == 789
        assert reg["sessions"] == {}

        old_registry = common.REGISTRY_PATH
        old_scrollback = common.SCROLLBACK_DIR
        try:
            common.REGISTRY_PATH = os.path.join(td, "common", "sessions.json")
            common.SCROLLBACK_DIR = os.path.join(td, "common", "scrollback")
            state_dir = os.path.join(td, "common-state")
            common.registry_upsert("s3", {"dir": "c"}, state_dir=state_dir)
            assert common.registry_load(state_dir=state_dir)["sessions"]["s3"]["dir"] == "c"
            common.registry_drop("s3", state_dir=state_dir)
            assert common.registry_load(state_dir=state_dir)["sessions"] == {}
        finally:
            common.REGISTRY_PATH = old_registry
            common.SCROLLBACK_DIR = old_scrollback

    print("common registry helper checks passed")


if __name__ == "__main__":
    main()

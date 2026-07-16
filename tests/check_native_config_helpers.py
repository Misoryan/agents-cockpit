"""Check extracted native config and argv helpers."""
import json
import os
import sys
import tempfile
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import common  # noqa: E402
import native_config  # noqa: E402


class FakeSession:
    def __init__(self, state_dir):
        self.sid = "s1"
        self.state_dir = state_dir
        self.user = "alice"
        self.claude_home = os.path.join(state_dir, "claude-home")
        self.claude_sid = ""
        self.plan_mode = False
        self.task_mode = False
        self.yolo = False


def main():
    with tempfile.TemporaryDirectory() as td:
        session = FakeSession(td)
        assert native_config.settings_path(session).endswith(os.path.join(td, "gate_settings_s1.json"))
        assert native_config.mcp_config_path(session).endswith(os.path.join(td, "gate_mcp_s1.json"))

        native_config.write_mcp_config(session, "gate_mcp.py", 7891)
        mcp = json.loads(Path(native_config.mcp_config_path(session)).read_text(encoding="utf-8"))
        cfg = mcp["mcpServers"]["cockpit"]
        assert cfg["args"] == ["gate_mcp.py", "s1", "7891", "alice", common.INTERNAL_AUTH]
        assert cfg["env"]["AGENT_COCKPIT_USER"] == "alice"

        native_config.write_gate_configs(session, ["Bash", "Edit"], "gate_mcp.py", 7891, allow_tools=False)
        settings = json.loads(Path(native_config.settings_path(session)).read_text(encoding="utf-8"))
        assert settings == {"permissions": {"ask": ["Bash", "Edit"]}}

        argv = native_config.build_argv(
            session, "hello", "claude", ["--stream"], ["AskUserQuestion"], ["Bash"],
            "gate_mcp.py", 7891, lambda: "system prompt")
        assert argv[:4] == ["claude", "-p", "hello", "--stream"]
        assert "--permission-mode" in argv and "default" in argv
        assert "--append-system-prompt" in argv and "system prompt" in argv

        session.yolo = True
        argv = native_config.build_argv(
            session, "hello", "claude", [], ["AskUserQuestion"], ["Bash"],
            "gate_mcp.py", 7891, lambda: "system prompt")
        assert "--dangerously-skip-permissions" in argv
        assert "--permission-prompt-tool" not in argv

        session.plan_mode = True
        session.yolo = True
        session.claude_sid = "claude-session"
        argv = native_config.build_argv(
            session, "hello", "claude", [], ["AskUserQuestion"], ["Bash"],
            "gate_mcp.py", 7891, lambda: "system prompt")
        assert ["--resume", "claude-session"] == argv[3:5]
        assert "--permission-mode" in argv and "plan" in argv
        settings = json.loads(Path(native_config.settings_path(session)).read_text(encoding="utf-8"))
        assert settings == {"permissions": {"allow": ["Bash"]}}

        env = native_config.process_env(session, base_env={"PATH": "x"})
        assert env["PATH"] == "x"
        assert env["CLAUDE_CONFIG_DIR"] == session.claude_home
        assert env["AGENT_COCKPIT_USER"] == "alice"
        assert os.path.isdir(session.claude_home)

    print("native config helper checks passed")


if __name__ == "__main__":
    main()

"""Check the Codex terminal interaction smoke covers the long-path contract."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "codex_terminal_smoke.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("codex_terminal_smoke", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    tool = _load_tool()
    result = tool.run_smoke(str(ROOT))
    assert result["ok"] is True
    assert result["writes"] == ["alpha\n", "beta\n", "done\n"]
    assert result["resize"] == {"processId": "proc-1", "size": {"cols": 120, "rows": 40}}
    assert result["terminate"] == {"processId": "proc-2"}
    assert result["terminal_interactions"] == 2
    assert result["terminal_input_sent"] == 2
    assert [event["process_id"] for event in result["terminal_closed"]] == ["proc-1", "proc-2"]
    assert result["terminal_closed"][1]["terminated"] is True
    assert "exceeds" in result["rejected_oversize"]
    assert result["rejected_resize"] == "terminal size out of range"
    assert result["rejected_after_close"] == "unknown terminal process"
    assert result["rejected_after_terminate"] == "unknown terminal process"
    print("codex terminal smoke helper checks passed")


if __name__ == "__main__":
    main()

"""Check state-changing API risk matrix coverage."""
import importlib.util
import sys
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "check_state_changing_api_risks.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("check_state_changing_api_risks", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    tool = _load_tool()
    result = tool.evaluate()
    assert result["ok"], result
    route_counts = {check["name"]: len(check["actual"]) for check in result["checks"]}
    assert route_counts["manager_user_api"] >= 14
    assert route_counts["manager_internal_api"] == 4
    assert route_counts["web"] == 4
    all_routes = {path for check in result["checks"] for path in check["actual"]}
    for route in (
        "/api/launch",
        "/api/nsend",
        "/api/nslash",
        "/api/nterminal",
        "/api/history_delete",
        "/api/codex_history_action",
        "/api/restart_manager",
        "/api/_stop",
        "/api/_perm_gate",
        "/api/_soft_exit",
    ):
        assert route in all_routes
    print("state-changing API risk checks passed")


if __name__ == "__main__":
    main()

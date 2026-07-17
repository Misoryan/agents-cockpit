"""Check the headless browser smoke keeps the intended visual-stability path."""
import importlib.util
import inspect
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "codex_browser_smoke.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("codex_browser_smoke", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    tool = _load_tool()
    src = inspect.getsource(tool)
    required = [
        "--headless=new",
        "/api/login",
        "showNativeSession",
        "window.NATIVE_DEBUG = true",
        "Emulation.setDeviceMetricsOverride",
        "--primary-width",
        "--mirror-width",
        "primary_layout_ok",
        "narrow_layout_ok",
        "composerVisible",
        "sidebarPosition",
        "/api/nslash",
        '"codex": {"sandbox": "danger-full-access", "approvalPolicy": "never"}',
        "/exec-stream ",
        "/api/nterminal",
        "_shell_exec_stdin_command",
        "exec_stream",
        "domText: st.root.textContent",
        "_wait_dom_text",
        "exec_final in (after.get(\"domText\") or \"\")",
        "exec_final in (primary.get(\"domText\") or \"\")",
        "/mcp-status tools",
        "MCP Status |",
        "_wait_dom_selector_count",
        ".mcp-status-card",
        "_first_mcp_browse_command",
        "MCP Resources |",
        ".mcp-resource-card",
        "mcp_status",
        "cards_primary",
        "cards_mirror",
        "resource_command",
        "resource_cards_mirror",
        "mcp_marker in (after.get(\"domText\") or \"\")",
        "_silence_open_ws",
        "_trigger_open_catchup",
        "nativeCatchupPoll(sid",
        "stale_open_catchup",
        "stale_name in before[\"text\"]",
        "open_catchup_dom_preserved",
        "before[\"lastSeq\"] >= before_open_catchup[\"lastSeq\"]",
        "ws.close()",
        "_force_reconnect",
        "nativeConnect(sid, {force:true})",
        "_mark_first_message_node",
        "dom_preserved_after_catchup",
        "dom_preserved_after_reconnect",
        "text_preserved_after_reconnect",
        "after_catchup",
        "after.get(\"firstNodeMarker\") == marker",
        "before_text in (after.get(\"text\") or \"\")",
        "after_catchup[\"childCount\"] >= before[\"childCount\"]",
        "after[\"childCount\"] >= after_catchup[\"childCount\"]",
        "second_name in after_catchup[\"text\"]",
        "third_name in after[\"text\"]",
        "third_name in primary[\"text\"]",
        "_layout_ok(after, expected_mobile=not args.mirror_desktop)",
        "_layout_ok(primary, expected_desktop=bool(primary_viewport))",
    ]
    missing = [token for token in required if token not in src]
    assert not missing, "browser smoke missing expected contracts: %r" % missing
    assert tool._password_from_auth_file("__missing_user__") == ""
    with tempfile.NamedTemporaryFile(delete=False) as handle:
        fake_browser = handle.name
    try:
        assert tool._find_browser(fake_browser) == fake_browser
    finally:
        Path(fake_browser).unlink(missing_ok=True)
    print("codex browser smoke helper checks passed")


if __name__ == "__main__":
    main()

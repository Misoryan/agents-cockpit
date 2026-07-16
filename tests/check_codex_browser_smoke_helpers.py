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
        "/api/nslash",
        "ws.close()",
        "_mark_first_message_node",
        "dom_preserved_after_reconnect",
        "text_preserved_after_reconnect",
        "after.get(\"firstNodeMarker\") == marker",
        "before_text in (after.get(\"text\") or \"\")",
        "after[\"childCount\"] >= before[\"childCount\"]",
        "second_name in after[\"text\"]",
        "second_name in primary[\"text\"]",
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

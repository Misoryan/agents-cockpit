"""Check the Codex visual smoke checklist and report template stay complete."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "codex-visual-smoke-checklist.md"
TOOL = ROOT / "tools" / "codex_visual_smoke_report.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("codex_visual_smoke_report", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    doc = DOC.read_text(encoding="utf-8")
    required_doc_tokens = [
        "多访问源同步",
        "会话加载不卡顿",
        "重连不全量刷新",
        "对话窗口不频繁闪烁",
        "python tools\\codex_ws_smoke.py --clients 2 --seconds 2 --launch-temp --cwd .",
        "python tools\\codex_mcp_smoke.py --cwd .",
        "V01",
        "V10",
        "WebSocket 1006",
        "raw JSON",
    ]
    missing = [token for token in required_doc_tokens if token not in doc]
    assert not missing, "visual smoke checklist missing tokens: %r" % missing

    tool = _load_tool()
    ids = [scenario["id"] for scenario in tool.SCENARIOS]
    assert ids == ["V%02d" % i for i in range(1, 11)]
    text = tool.render_report()
    for token in [
        "Codex 多端视觉 Smoke 记录",
        "Git commit",
        "Codex CLI",
        "Session id",
        "PASS / FAIL / SKIP",
        "Console close code / last seq / catch-up URL",
    ] + ids:
        assert token in text, "visual smoke report missing %r" % token
    print("codex visual smoke checklist checks passed")


if __name__ == "__main__":
    main()

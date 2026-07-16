"""Check CLI discovery and backend helpers after extraction."""
import os
import sys
import tempfile
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import common  # noqa: E402
import common_binaries  # noqa: E402


def _touch(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("", encoding="utf-8")


def main():
    with tempfile.TemporaryDirectory() as td:
        tool = os.path.join(td, "tool")
        tool_cmd = tool + ".cmd"
        _touch(tool_cmd)
        if os.name == "nt":
            assert common_binaries.prefer_windows_cmd(tool) == tool_cmd
            assert common_binaries.script_argv(tool + ".ps1", "x")[:5] == [
                "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"
            ]
        else:
            assert common_binaries.prefer_windows_cmd(tool) == tool
            assert common_binaries.script_argv(tool + ".ps1", "x") == [tool + ".ps1", "x"]

        codex_bin = os.path.join(td, "codex.cmd" if os.name == "nt" else "codex")
        _touch(codex_bin)
        assert common_binaries.resolve_codex_bin(codex_bin) == codex_bin
        assert common_binaries.codex_argv(codex_bin, "app-server") == [codex_bin, "app-server"]

        package_bin = os.path.join(td, "pkg", "codex.cmd" if os.name == "nt" else "codex")
        js = os.path.join(td, "pkg", "node_modules", "@openai", "codex", "bin", "codex.js")
        node = os.path.join(td, "pkg", "node.exe" if os.name == "nt" else "node")
        _touch(package_bin)
        _touch(js)
        _touch(node)
        argv = common_binaries.codex_argv(package_bin, "app-server", "--stdio")
        assert argv == [node, js, "app-server", "--stdio"]

        assert common_binaries.is_codex_backend("codex")
        assert common_binaries.is_codex_backend("codex_native")
        assert common_binaries.is_claude_backend("claude_native")
        assert common_binaries.normalize_backend("", codex_bin=None) == "claude_native"
        assert common_binaries.normalize_backend("", codex_bin=codex_bin) == "codex_native"
        assert common_binaries.normalize_backend("native", codex_bin=codex_bin) == "claude_native"

        claude_bin = os.path.join(td, "claude.cmd" if os.name == "nt" else "claude")
        _touch(claude_bin)
        discovered = common_binaries.discover_backends(claude_bin, codex_bin)
        assert discovered[0] == claude_bin
        assert discovered[1] == codex_bin
        assert set(discovered[2]) == {"claude_native", "codex_native"}
        assert common_binaries.discover_backends(claude_bin, codex_bin, stop_or_help=True) == (None, None, {})

        old_codex = common.CODEX_BIN
        try:
            common.CODEX_BIN = codex_bin
            assert common.normalize_backend("") == "codex_native"
            assert common.codex_argv("app-server") == [codex_bin, "app-server"]
        finally:
            common.CODEX_BIN = old_codex

    print("common binaries helper checks passed")


if __name__ == "__main__":
    main()

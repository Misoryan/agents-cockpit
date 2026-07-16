"""Check hardened profile validation helper."""
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "check_hardened_profile.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location("check_hardened_profile", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write(path, text):
    path.write_text(text.strip() + "\n", encoding="utf-8", newline="\n")


def main():
    tool = _load_tool()
    with tempfile.TemporaryDirectory() as td:
        hardened = Path(td, "hardened.ini")
        _write(hardened, """
        [server]
        host = 127.0.0.1
        use_https = 1
        http_port = 0
        [approval]
        auto_approve = 0
        [users]
        allow_unconfigured_paths = 0
        primary_user_uses_default_homes = 0
        [security]
        cookie_secure = 1
        csrf_origin_check = 1
        csrf_allow_missing_origin = 0
        session_ttl = 28800
        """)
        result = tool.evaluate(tool.load_config(str(hardened)))
        assert result["ok"] is True

        proxy = Path(td, "proxy.ini")
        _write(proxy, """
        [server]
        host = 127.0.0.1
        use_https = 0
        http_port = 0
        [approval]
        auto_approve = 0
        [users]
        allow_unconfigured_paths = 0
        primary_user_uses_default_homes = 0
        [security]
        cookie_secure = 1
        csrf_origin_check = 1
        csrf_allow_missing_origin = 0
        session_ttl = 1800
        """)
        assert tool.evaluate(tool.load_config(str(proxy)), behind_https_proxy=True)["ok"] is True
        assert tool.evaluate(tool.load_config(str(proxy)), behind_https_proxy=False)["ok"] is False

        weak = Path(td, "weak.ini")
        _write(weak, """
        [server]
        host = 0.0.0.0
        use_https = 0
        http_port = 7800
        [approval]
        auto_approve = 1
        [users]
        allow_unconfigured_paths = 1
        primary_user_uses_default_homes = 1
        [security]
        cookie_secure = 0
        csrf_origin_check = 0
        csrf_allow_missing_origin = 1
        session_ttl = 86400
        """)
        weak_result = tool.evaluate(tool.load_config(str(weak)))
        assert weak_result["ok"] is False
        failed = {item["key"] for item in weak_result["failed"]}
        assert "server.host" in failed
        assert "security.csrf_allow_missing_origin" in failed

        proc = subprocess.run(
            [sys.executable, str(TOOL), "--config", str(hardened), "--json"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert proc.returncode == 0
        assert '"ok": true' in proc.stdout

        proc = subprocess.run(
            [sys.executable, str(TOOL), "--config", str(weak)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert proc.returncode == 1
        assert "Hardened profile: FAIL" in proc.stdout

    print("hardened profile tool checks passed")


if __name__ == "__main__":
    main()

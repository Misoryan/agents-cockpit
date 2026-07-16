"""Check CC Switch helpers after extracting them from common.py."""
import json
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import common  # noqa: E402
import common_ccswitch  # noqa: E402


def _create_db(path, claude_base_url):
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE providers (app_type TEXT, name TEXT, is_current INTEGER, settings_config TEXT)"
        )
        conn.execute(
            "CREATE TABLE proxy_request_logs ("
            "created_at REAL, status_code INTEGER, total_cost_usd TEXT, input_tokens INTEGER, "
            "output_tokens INTEGER, cache_read_tokens INTEGER, cache_creation_tokens INTEGER, model TEXT)"
        )
        claude_cfg = {
            "env": {
                "ANTHROPIC_MODEL": "claude-sonnet",
                "ANTHROPIC_BASE_URL": claude_base_url,
                "ANTHROPIC_AUTH_TOKEN": "ak-test",
            }
        }
        openai_cfg = {
            "config": 'model = "gpt-5"\nbase_url = "https://api.example.com/v1"\n',
            "auth": {"OPENAI_API_KEY": "openai-key"},
        }
        conn.execute("INSERT INTO providers VALUES (?,?,?,?)", ("claude", "zhipu", 1, json.dumps(claude_cfg)))
        conn.execute("INSERT INTO providers VALUES (?,?,?,?)", ("openai", "other", 0, json.dumps(openai_cfg)))
        now = int(time.time())
        conn.execute("INSERT INTO proxy_request_logs VALUES (?,?,?,?,?,?,?,?)",
                     (now, 200, "0.1256", 10, 20, 3, 2, "claude-sonnet"))
        conn.execute("INSERT INTO proxy_request_logs VALUES (?,?,?,?,?,?,?,?)",
                     (now + 1, 500, "9.9", 999, 999, 0, 0, "ignored"))
        conn.commit()
        return now + 1
    finally:
        conn.close()


def main():
    with tempfile.TemporaryDirectory() as td:
        db_path = os.path.join(td, "cc-switch.db")
        last_ts = _create_db(db_path, "https://open.bigmodel.cn/api/anthropic")
        settings = common_ccswitch.CCSwitchSettings(db=db_path, usage_ttl=60, balance_ttl=60)
        common_ccswitch.reset_caches()

        assert common_ccswitch.toml_first('model = "gpt-5"', "model") == "gpt-5"
        assert common_ccswitch.provider_meta("", "claude")["model"] == ""
        openai_meta = common_ccswitch.provider_meta(
            json.dumps({"config": 'model = "gpt-5"\nbase_url = "https://api.example.com/v1"\n',
                        "auth": {"OPENAI_API_KEY": "k"}}),
            "openai",
        )
        assert openai_meta["model"] == "gpt-5"
        assert openai_meta["host"] == "api.example.com"
        assert openai_meta["api_key"] == "k"

        overview = common_ccswitch.overview(settings)
        assert overview["enabled"] is True
        assert overview["cached"] is False
        assert overview["providers"][0]["name"] == "zhipu"
        assert overview["providers"][0]["host"] == "open.bigmodel.cn"
        assert overview["usage"]["today"]["requests"] == 1
        assert overview["usage"]["today"]["cost"] == 0.1256
        assert overview["usage"]["today"]["cache_tokens"] == 5
        assert overview["usage"]["by_model"][0]["tokens"] == 35
        assert overview["usage"]["last_ts"] == last_ts

        cached = common_ccswitch.overview(settings)
        assert cached["cached"] is True

        assert common_ccswitch.current_zhipu(settings) == ("ak-test", "open.bigmodel.cn")
        assert common_ccswitch.zhipu_api_base("open.bigmodel.cn") == "https://open.bigmodel.cn"
        assert common_ccswitch.zhipu_api_base("api.z.ai") == "https://api.z.ai"
        assert common_ccswitch.zhipu_api_base("api.example.com") is None
        assert common_ccswitch.overview(common_ccswitch.CCSwitchSettings(db=os.path.join(td, "missing.db"))) == {
            "enabled": False
        }

        non_zhipu_db = os.path.join(td, "anthropic.db")
        _create_db(non_zhipu_db, "https://api.anthropic.com")
        assert common_ccswitch.balance(common_ccswitch.CCSwitchSettings(db=non_zhipu_db)) == {"supported": False}

        old = {
            "CCSWITCH_DB": common.CCSWITCH_DB,
            "CCSWITCH_USAGE_TTL": common.CCSWITCH_USAGE_TTL,
            "CCSWITCH_BALANCE_TTL": common.CCSWITCH_BALANCE_TTL,
        }
        try:
            common.CCSWITCH_DB = db_path
            common.CCSWITCH_USAGE_TTL = 60
            common.CCSWITCH_BALANCE_TTL = 60
            common_ccswitch.reset_caches()
            assert common.ccswitch_overview()["providers"][0]["model"] == "claude-sonnet"
            assert common._ccswitch_current_zhipu() == ("ak-test", "open.bigmodel.cn")
        finally:
            for key, value in old.items():
                setattr(common, key, value)
            common_ccswitch.reset_caches()

    print("common ccswitch helper checks passed")


if __name__ == "__main__":
    main()

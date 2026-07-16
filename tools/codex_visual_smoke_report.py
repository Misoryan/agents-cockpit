#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate a manual visual-smoke report template for Codex multi-client QA.

The protocol smokes prove reconnect/replay invariants at the socket layer. This
report template keeps the browser/mobile checks repeatable for the user-visible
parts that are hard to prove without a real rendered UI.
"""
import argparse
import datetime as _dt
import subprocess
from pathlib import Path


SCENARIOS = [
    {
        "id": "V01",
        "title": "双端打开同一 Codex 会话",
        "assertions": [
            "两端显示同一 session/title/model badge",
            "第二端加载只显示短暂 replay 状态，不触发第一端重绘",
        ],
    },
    {
        "id": "V02",
        "title": "普通流式回复同步",
        "assertions": [
            "两端增量文本顺序一致",
            "最终 assistant 内容不重复、不缺段",
        ],
    },
    {
        "id": "V03",
        "title": "Plan/pending 卡同步",
        "assertions": [
            "approval/ask/form/Plan 卡两端可见",
            "任一端处理后另一端同步更新",
        ],
    },
    {
        "id": "V04",
        "title": "工具卡 replay 一致",
        "assertions": [
            "command/diff/JSON/MCP 卡两端结构一致",
            "replay 后不退化成 raw JSON",
        ],
    },
    {
        "id": "V05",
        "title": "图片输入同步",
        "assertions": [
            "用户图片卡两端可见",
            "历史恢复后仍显示图片卡",
        ],
    },
    {
        "id": "V06",
        "title": "WebSocket 断开后恢复",
        "assertions": [
            "断网/恢复后不全量清空 DOM",
            "只补齐缺失增量且没有连续闪屏",
        ],
    },
    {
        "id": "V07",
        "title": "open 但疑似漏事件 catch-up",
        "assertions": [
            "后台/锁屏后切回能自动补齐",
            "scroll 不发生明显跳动",
        ],
    },
    {
        "id": "V08",
        "title": "历史/归档生命周期",
        "assertions": [
            "Archive/Unarchive/Fork/Rollback/Compact/Rename/Goal 状态由后端确认",
            "active/archived filter 不混入错误会话",
        ],
    },
    {
        "id": "V09",
        "title": "移动端窄屏输入",
        "assertions": [
            "输入框、slash menu、file mention menu 不遮挡确认卡",
            "手机发送内容同步到桌面端",
        ],
    },
    {
        "id": "V10",
        "title": "长会话加载",
        "assertions": [
            "首屏不长时间空白",
            "replay 完成后内容不重复、不闪烁",
        ],
    },
]


def _run_text(args):
    try:
        return subprocess.check_output(args, text=True, encoding="utf-8", errors="replace").strip()
    except Exception as exc:
        return "unavailable: %s" % exc


def _git_commit():
    return _run_text(["git", "rev-parse", "--short", "HEAD"])


def _git_status():
    return _run_text(["git", "status", "--short", "--branch"])


def _codex_version():
    direct = _run_text(["codex", "--version"])
    if not direct.startswith("unavailable:"):
        return direct
    return _run_text(["powershell", "-NoProfile", "-Command", "codex --version"])


def render_report():
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "# Codex 多端视觉 Smoke 记录",
        "",
        "- 时间：%s" % now,
        "- Git commit：`%s`" % _git_commit(),
        "- Git status：",
        "",
        "```text",
        _git_status(),
        "```",
        "",
        "- Codex CLI：`%s`" % _codex_version(),
        "- 主客户端：",
        "- 第二客户端/手机：",
        "- Session id：",
        "- 测试人：",
        "",
        "## 协议层基线",
        "",
        "```powershell",
        "python tools\\codex_ws_smoke.py --clients 2 --seconds 2 --launch-temp --cwd .",
        "python tools\\codex_mcp_smoke.py --cwd .",
        "```",
        "",
        "- WS smoke：PASS / FAIL / SKIP，证据：",
        "- MCP smoke：PASS / FAIL / SKIP，证据：",
        "",
        "## 视觉场景",
        "",
        "| ID | 场景 | 状态 | 断言 | 证据/备注 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for scenario in SCENARIOS:
        assertions = "<br>".join("- %s" % item for item in scenario["assertions"])
        lines.append("| {id} | {title} | PASS / FAIL / SKIP | {assertions} |  |".format(
            id=scenario["id"],
            title=scenario["title"],
            assertions=assertions,
        ))
    lines.extend([
        "",
        "## 失败详情",
        "",
        "- 失败场景：",
        "- 复现步骤：",
        "- 截图/录屏：",
        "- Console close code / last seq / catch-up URL：",
        "- 初步判断：",
    ])
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="", help="Write the markdown report to this path.")
    args = parser.parse_args(argv)
    text = render_report()
    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        print("wrote %s" % path)
    else:
        print(text, end="")


if __name__ == "__main__":
    main()

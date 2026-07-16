#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate a Codex app-server protocol coverage matrix.

The matrix is intentionally static about Agents Cockpit support status and
dynamic about the installed Codex CLI schema. It lets us notice protocol drift
without hand-scanning a large JSON Schema dump after every CLI upgrade.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


SCHEMA_FILES = {
    "server_notifications": "ServerNotification.json",
    "server_requests": "ServerRequest.json",
    "client_requests": "ClientRequest.json",
}


SUPPORT = {
    "server_notifications": {
        "supported": {
            "thread/started",
            "thread/status/changed",
            "thread/settings/updated",
            "turn/started",
            "turn/completed",
            "item/agentMessage/delta",
            "item/reasoning/summaryTextDelta",
            "item/reasoning/textDelta",
            "item/reasoning/summaryPartAdded",
            "item/started",
            "item/completed",
            "item/commandExecution/outputDelta",
            "item/fileChange/patchUpdated",
            "item/fileChange/outputDelta",
            "item/mcpToolCall/progress",
            "item/plan/delta",
            "turn/diff/updated",
            "turn/plan/updated",
            "thread/tokenUsage/updated",
            "thread/compacted",
            "thread/unarchived",
            "thread/goal/updated",
            "thread/goal/cleared",
            "item/commandExecution/terminalInteraction",
            "error",
            "warning",
            "guardianWarning",
            "configWarning",
            "deprecationNotice",
            "model/rerouted",
        },
        "degraded": {
            "item/commandExecution/terminalInteraction",
            "model/safetyBuffering/updated",
            "account/rateLimits/updated",
            "mcpServer/startupStatus/updated",
            "turn/moderationMetadata",
        },
    },
    "server_requests": {
        "supported": {
            "item/commandExecution/requestApproval",
            "item/fileChange/requestApproval",
            "item/permissions/requestApproval",
            "item/tool/requestUserInput",
            "mcpServer/elicitation/request",
        },
        "degraded": {
            "item/tool/call",
            "attestation/generate",
            "account/chatgptAuthTokens/refresh",
        },
    },
    "client_requests": {
        "supported": {
            "initialize",
            "account/read",
            "thread/start",
            "thread/resume",
            "turn/start",
            "turn/interrupt",
            "thread/read",
            "thread/list",
            "thread/delete",
            "thread/settings/update",
            "model/list",
            "permissionProfile/list",
            "config/read",
            "thread/compact/start",
            "thread/archive",
            "thread/fork",
            "thread/rollback",
            "thread/name/set",
            "thread/unarchive",
            "thread/goal/get",
            "thread/goal/set",
            "thread/goal/clear",
            "fuzzyFileSearch",
            "command/exec/write",
            "command/exec/resize",
            "command/exec/terminate",
            "mcpServer/tool/call",
            "mcpServer/resource/read",
            "turn/steer",
        },
        "planned_high_value": set(),
    },
}


NOTES = {
    "supported": "Implemented in current adapter path.",
    "degraded": "Visible in UI, but not full CLI parity yet.",
    "planned_high_value": "High-value CLI parity target.",
    "generic_visible": "Generic notice/error path only.",
    "not_integrated": "Not integrated in Agents Cockpit yet.",
}

METHOD_NOTES = {
    ("server_requests", "item/tool/call"):
        "Allowlisted MCP passthrough is implemented; unmapped tools fail visibly.",
    ("client_requests", "account/read"):
        "Read-only account status is shown in the Codex launch modal; login/logout are not integrated.",
}


def collect_methods(schema_obj):
    methods = []

    def walk(value):
        if isinstance(value, dict):
            title = value.get("title", "")
            if isinstance(title, str) and title.endswith("Method") and isinstance(value.get("enum"), list):
                methods.extend(item for item in value["enum"] if isinstance(item, str))
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(schema_obj)
    return sorted(set(methods))


def load_methods(schema_dir):
    out = {}
    for key, filename in SCHEMA_FILES.items():
        path = Path(schema_dir) / filename
        with path.open("r", encoding="utf-8") as handle:
            out[key] = collect_methods(json.load(handle))
    return out


def classify(kind, method):
    support = SUPPORT.get(kind, {})
    for status, methods in support.items():
        if method in methods:
            return status
    if kind == "server_notifications":
        if method.endswith("/updated"):
            return "degraded"
        return "generic_visible"
    if kind == "server_requests":
        return "generic_visible"
    return "not_integrated"


def generate_schema(out_dir, codex_bin="codex"):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(codex_argv(codex_bin, "app-server", "generate-json-schema", "--out", str(out_dir)), check=True)
    return out_dir


def render_markdown(methods_by_kind, codex_version=""):
    lines = [
        "# Codex App-Server Protocol Matrix",
        "",
        "This file is generated from the installed Codex app-server JSON Schema",
        "plus static Agents Cockpit coverage labels.",
        "",
    ]
    if codex_version:
        lines.extend(["- Codex CLI: `%s`" % codex_version, ""])
    for kind in ("server_notifications", "server_requests", "client_requests"):
        methods = methods_by_kind.get(kind, [])
        counts = {}
        rows = []
        for method in methods:
            status = classify(kind, method)
            counts[status] = counts.get(status, 0) + 1
            rows.append((method, status, METHOD_NOTES.get((kind, method), NOTES.get(status, ""))))
        summary = ", ".join("%s=%d" % (key, counts[key]) for key in sorted(counts))
        lines.extend([
            "## %s" % kind.replace("_", " ").title(),
            "",
            "- Total: %d%s" % (len(methods), ("; " + summary) if summary else ""),
            "",
            "| Method | Status | Notes |",
            "| --- | --- | --- |",
        ])
        for method, status, note in rows:
            lines.append("| `%s` | `%s` | %s |" % (method, status, note))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def codex_version(codex_bin="codex"):
    try:
        return subprocess.check_output(codex_argv(codex_bin, "--version"), text=True, encoding="utf-8", errors="replace").strip()
    except Exception:
        return ""


def codex_argv(codex_bin, *args):
    path = shutil.which(codex_bin) or shutil.which(codex_bin + ".ps1") or codex_bin
    if os.name == "nt" and str(path).lower().endswith(".ps1"):
        shell = shutil.which("powershell") or shutil.which("pwsh") or "powershell"
        return [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path] + list(args)
    return [path] + list(args)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--schema-dir", help="Directory containing Codex app-server schema JSON files.")
    parser.add_argument("--codex-bin", default="codex", help="Codex executable to use when --schema-dir is omitted.")
    parser.add_argument("--out", default="", help="Write markdown to this path instead of stdout.")
    args = parser.parse_args(argv)

    tmp = None
    try:
        schema_dir = args.schema_dir
        if not schema_dir:
            tmp = tempfile.mkdtemp(prefix="codex-schema-")
            schema_dir = str(generate_schema(tmp, args.codex_bin))
        methods = load_methods(schema_dir)
        markdown = render_markdown(methods, codex_version(args.codex_bin))
        if args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(markdown, encoding="utf-8", newline="\n")
        else:
            sys.stdout.write(markdown)
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()

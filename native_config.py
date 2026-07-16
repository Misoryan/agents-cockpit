# -*- coding: utf-8 -*-
"""Per-session Claude gate configuration and argv helpers."""
import json
import os
import sys
import traceback

import common


def settings_path(session):
    return os.path.join(session.state_dir, "gate_settings_%s.json" % session.sid)


def mcp_config_path(session):
    return os.path.join(session.state_dir, "gate_mcp_%s.json" % session.sid)


def write_mcp_config(session, gate_bin, manager_port):
    os.makedirs(session.state_dir, exist_ok=True)
    mcp = {"mcpServers": {"cockpit": {
        "command": sys.executable,
        "args": [gate_bin, session.sid, str(manager_port), session.user, common.INTERNAL_AUTH],
        "env": {
            "AGENT_COCKPIT_USER": session.user,
            "AGENT_COCKPIT_INTERNAL_AUTH": common.INTERNAL_AUTH,
        }}}}
    with open(mcp_config_path(session), "w", encoding="utf-8") as handle:
        json.dump(mcp, handle, ensure_ascii=False)


def write_gate_configs(session, ask_tools, gate_bin, manager_port, allow_tools=False):
    os.makedirs(session.state_dir, exist_ok=True)
    key = "allow" if allow_tools else "ask"
    with open(settings_path(session), "w", encoding="utf-8") as handle:
        json.dump({"permissions": {key: list(ask_tools)}}, handle, ensure_ascii=False)
    write_mcp_config(session, gate_bin, manager_port)


def build_argv(session, prompt, claude_bin, claude_args, disabled_tools, ask_tools,
               gate_bin, manager_port, mode_system_fn):
    argv = [claude_bin, "-p", prompt] + list(claude_args)
    if session.claude_sid:
        argv += ["--resume", session.claude_sid]
    sys_prompt = mode_system_fn()
    argv += ["--disallowedTools"] + list(disabled_tools)
    if session.plan_mode:
        try:
            write_gate_configs(session, ask_tools, gate_bin, manager_port, allow_tools=session.yolo)
        except OSError:
            traceback.print_exc()
        argv += ["--permission-mode", "plan",
                 "--settings", settings_path(session),
                 "--mcp-config", mcp_config_path(session),
                 "--permission-prompt-tool", "mcp__cockpit__approve",
                 "--strict-mcp-config"]
        if sys_prompt:
            argv += ["--append-system-prompt", sys_prompt]
        return argv
    if session.yolo:
        try:
            write_mcp_config(session, gate_bin, manager_port)
        except OSError:
            traceback.print_exc()
        argv += ["--dangerously-skip-permissions",
                 "--mcp-config", mcp_config_path(session),
                 "--strict-mcp-config"]
        if sys_prompt:
            argv += ["--append-system-prompt", sys_prompt]
        return argv
    try:
        write_gate_configs(session, ask_tools, gate_bin, manager_port, allow_tools=False)
    except OSError:
        traceback.print_exc()
    argv += ["--permission-mode", "default",
             "--settings", settings_path(session),
             "--mcp-config", mcp_config_path(session),
             "--permission-prompt-tool", "mcp__cockpit__approve",
             "--strict-mcp-config",
             "--append-system-prompt", sys_prompt]
    return argv


def process_env(session, base_env=None):
    env = dict(os.environ if base_env is None else base_env)
    if session.claude_home:
        os.makedirs(session.claude_home, exist_ok=True)
        env["CLAUDE_CONFIG_DIR"] = session.claude_home
    if session.user:
        env["AGENT_COCKPIT_USER"] = session.user
    return env

# -*- coding: utf-8 -*-
"""CLI discovery and backend normalization helpers."""
import os
import subprocess


def prefer_windows_cmd(path):
    if os.name != "nt" or not path:
        return path
    _root, ext = os.path.splitext(path)
    if ext.lower() in (".cmd", ".bat", ".exe"):
        return path
    for suffix in (".cmd", ".exe", ".bat", ".ps1"):
        candidate = path + suffix
        if os.path.isfile(candidate):
            return candidate
    return path


def resolve_cli_bin(name, override=None):
    if override and os.path.isfile(override):
        return prefer_windows_cmd(override)
    try:
        cmd = ("where %s" % name) if os.name == "nt" else ("command -v %s" % name)
        out = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL, timeout=10).decode(errors="replace")
        for line in out.splitlines():
            shim = prefer_windows_cmd(line.strip())
            if shim and os.path.isfile(shim):
                return shim
    except Exception:
        pass
    return None


def resolve_claude_bin(override=None):
    return resolve_cli_bin("claude", override)


def resolve_codex_bin(override=None):
    return resolve_cli_bin("codex", override)


def script_argv(path, *args):
    if not path:
        return []
    ext = os.path.splitext(path)[1].lower()
    if os.name == "nt" and ext == ".ps1":
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path] + list(args)
    return [path] + list(args)


def codex_argv(codex_bin, *args):
    if codex_bin:
        base = os.path.dirname(codex_bin)
        js = os.path.join(base, "node_modules", "@openai", "codex", "bin", "codex.js")
        if os.path.isfile(js):
            node = os.path.join(base, "node.exe") if os.name == "nt" else os.path.join(base, "node")
            if not os.path.isfile(node):
                node = "node"
            return [node, js] + list(args)
    return script_argv(codex_bin, *args)


def is_codex_backend(backend):
    return backend in ("codex", "codex_native")


def is_claude_backend(backend):
    return backend in ("claude", "native", "claude_native")


def normalize_backend(backend, codex_bin=None):
    if is_codex_backend(backend):
        return "codex_native"
    if is_claude_backend(backend):
        return "claude_native"
    if codex_bin:
        return "codex_native"
    return "claude_native"


def discover_backends(claude_override=None, codex_override=None, stop_or_help=False):
    if stop_or_help:
        return None, None, {}
    claude_bin = resolve_claude_bin(claude_override)
    codex_bin = resolve_codex_bin(codex_override)
    backends = {}
    if claude_bin and os.path.isfile(claude_bin):
        backends["claude_native"] = {"bin": claude_bin, "label": "Claude"}
    if codex_bin and os.path.isfile(codex_bin):
        backends["codex_native"] = {"bin": codex_bin, "label": "Codex"}
    return claude_bin, codex_bin, backends

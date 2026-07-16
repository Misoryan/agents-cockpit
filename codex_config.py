# -*- coding: utf-8 -*-
"""Codex launch configuration helpers.

Keep UI-submitted Codex options small and schema-shaped so the web app does
not expose fields that the app-server will silently ignore.
"""

APPROVAL_POLICIES = ("untrusted", "on-failure", "on-request", "never")
SANDBOX_MODES = ("read-only", "workspace-write", "danger-full-access")
WEB_SEARCH_MODES = ("disabled", "cached", "indexed", "live")
GOAL_STATUSES = ("active", "paused", "blocked", "usageLimited", "budgetLimited", "complete")


def _clean_text(value):
    if value is None:
        return ""
    return str(value).strip()


def normalize_launch_config(value):
    """Return a trusted Codex launch config subset from browser input."""
    if not isinstance(value, dict):
        return {}
    out = {}
    model = _clean_text(value.get("model"))
    if model:
        out["model"] = model

    approval = _clean_text(
        value.get("approvalPolicy")
        or value.get("approval_policy")
        or value.get("approval")
    )
    if approval in APPROVAL_POLICIES:
        out["approval_policy"] = approval

    sandbox = _clean_text(
        value.get("sandbox")
        or value.get("sandboxMode")
        or value.get("sandbox_mode")
    )
    if sandbox in SANDBOX_MODES:
        out["sandbox"] = sandbox

    search = value.get("webSearch")
    if search is None:
        search = value.get("web_search")
    if search is None:
        search = value.get("search")
    if isinstance(search, bool):
        search = "live" if search else "disabled"
    search = _clean_text(search)
    if search in WEB_SEARCH_MODES:
        out["web_search"] = search
    return out


def thread_config(config):
    """Build the `config` override object for thread/start."""
    config = normalize_launch_config(config)
    out = {}
    if config.get("web_search"):
        out["web_search"] = config["web_search"]
    return out


def sandbox_policy(mode, cwd=""):
    """Map CLI-style sandbox mode to app-server turn sandboxPolicy."""
    if mode == "danger-full-access":
        return {"type": "dangerFullAccess"}
    if mode == "read-only":
        return {"type": "readOnly"}
    if mode == "workspace-write":
        policy = {"type": "workspaceWrite"}
        if cwd:
            policy["writableRoots"] = [cwd]
        return policy
    return None


def default_launch_options(error=""):
    return {
        "models": [],
        "permission_profiles": [],
        "config": {},
        "approval_policies": list(APPROVAL_POLICIES),
        "sandbox_modes": list(SANDBOX_MODES),
        "web_search_modes": ["default"] + list(WEB_SEARCH_MODES),
        "error": error or "",
    }


def _page_request(client, method, params, key="data", limit=100, timeout=10):
    out = []
    cursor = None
    while True:
        req = dict(params or {})
        req["limit"] = limit
        if cursor:
            req["cursor"] = cursor
        res = client.request(method, req, timeout=timeout)
        if isinstance(res, dict):
            data = res.get(key)
            if isinstance(data, list):
                out.extend(data)
            cursor = res.get("nextCursor")
            if cursor:
                continue
        break
    return out


def load_launch_options(client, cwd=""):
    """Read live Codex capabilities for the launch modal.

    The result always includes static safe choices. Individual app-server
    failures are reported in `error` while keeping the modal usable.
    """
    out = default_launch_options()
    errors = []
    try:
        out["models"] = _page_request(
            client, "model/list", {"includeHidden": False}, timeout=12)
    except Exception as exc:
        errors.append("model/list: %s" % exc)
    try:
        out["permission_profiles"] = _page_request(
            client, "permissionProfile/list", {"cwd": cwd or None}, timeout=12)
    except Exception as exc:
        errors.append("permissionProfile/list: %s" % exc)
    try:
        res = client.request(
            "config/read", {"cwd": cwd or None, "includeLayers": False}, timeout=12)
        if isinstance(res, dict):
            out["config"] = res.get("config") or {}
    except Exception as exc:
        errors.append("config/read: %s" % exc)
    out["error"] = "; ".join(errors)
    return out

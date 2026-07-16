# -*- coding: utf-8 -*-
"""Read-only Codex skills and plugin inventory helpers."""
import time

import codex_text


SKILL_MODES = {"": "all", "all": "all", "enabled": "enabled", "disabled": "disabled"}
PLUGIN_MODES = {
    "": ("installed", "plugin/installed"),
    "installed": ("installed", "plugin/installed"),
    "available": ("available", "plugin/list"),
    "marketplace": ("available", "plugin/list"),
    "marketplaces": ("available", "plugin/list"),
}


def _words(arg):
    return str(arg or "").strip().split()


def _bool_or_none(value):
    if isinstance(value, bool):
        return value
    return None


def _text(value, limit=320):
    value = str(value or "").strip()
    if limit and len(value) > limit:
        return value[:limit - 1].rstrip() + "..."
    return value


def skill_summary(skill):
    if not isinstance(skill, dict):
        return {}
    interface = skill.get("interface") or {}
    short = interface.get("shortDescription") or skill.get("shortDescription")
    desc = "" if short else skill.get("description")
    out = {
        "name": _text(skill.get("name"), 120),
        "displayName": _text(interface.get("displayName") or skill.get("displayName"), 160),
        "shortDescription": _text(short, 180),
        "description": _text(desc, 220),
        "scope": _text(skill.get("scope"), 80),
        "enabled": bool(skill.get("enabled")),
    }
    return {key: value for key, value in out.items() if value not in ("", None)}


def skills_payload(response, mode="all"):
    roots = []
    total = enabled = disabled = 0
    scopes = {}
    for group in (response.get("data") if isinstance(response, dict) else []) or []:
        if not isinstance(group, dict):
            continue
        items = []
        for skill in group.get("skills") or []:
            item = skill_summary(skill)
            if not item:
                continue
            if mode == "enabled" and not item.get("enabled"):
                continue
            if mode == "disabled" and item.get("enabled"):
                continue
            items.append(item)
            total += 1
            if item.get("enabled"):
                enabled += 1
            else:
                disabled += 1
            scope = item.get("scope") or "unknown"
            scopes[scope] = scopes.get(scope, 0) + 1
        roots.append({
            "cwd": _text(group.get("cwd"), 260),
            "skills": items,
        })
    return {
        "mode": mode,
        "total": total,
        "enabled": enabled,
        "disabled": disabled,
        "scopes": scopes,
        "roots": roots,
    }


def _plugin_id(plugin):
    for key in ("id", "pluginId", "name", "slug"):
        value = _text(plugin.get(key), 160)
        if value:
            return value
    return ""


def plugin_summary(plugin):
    if not isinstance(plugin, dict):
        return {}
    interface = plugin.get("interface") or {}
    name = plugin.get("name") or interface.get("displayName") or plugin.get("title") or _plugin_id(plugin)
    description = (
        plugin.get("description")
        or interface.get("shortDescription")
        or interface.get("description")
        or plugin.get("summary")
    )
    out = {
        "id": _plugin_id(plugin),
        "name": _text(name, 180),
        "description": _text(description, 220),
        "version": _text(plugin.get("version"), 80),
        "installed": _bool_or_none(plugin.get("installed")),
        "enabled": _bool_or_none(plugin.get("enabled")),
    }
    return {key: value for key, value in out.items() if value not in ("", None)}


def _marketplace_plugins(marketplace):
    for key in ("plugins", "items", "entries"):
        value = marketplace.get(key)
        if isinstance(value, list):
            return value
    return []


def plugins_payload(response, mode="installed"):
    marketplaces = []
    total = installed = enabled = 0
    for marketplace in (response.get("marketplaces") if isinstance(response, dict) else []) or []:
        if not isinstance(marketplace, dict):
            continue
        plugins = [plugin_summary(item) for item in _marketplace_plugins(marketplace) if isinstance(item, dict)]
        plugins = [item for item in plugins if item]
        total += len(plugins)
        installed += sum(1 for item in plugins if item.get("installed") is True)
        enabled += sum(1 for item in plugins if item.get("enabled") is True)
        marketplaces.append({
            "id": _text(marketplace.get("id") or marketplace.get("name"), 160),
            "name": _text(marketplace.get("name") or marketplace.get("title") or marketplace.get("id"), 180),
            "plugins": plugins,
        })
    errors = response.get("marketplaceLoadErrors") if isinstance(response, dict) else []
    safe_errors = []
    for err in errors if isinstance(errors, list) else []:
        if isinstance(err, dict):
            safe_errors.append(_text(err.get("message") or err.get("error") or err.get("code") or "marketplace load error", 300))
        else:
            safe_errors.append(_text(err, 300))
    featured = response.get("featuredPluginIds") if isinstance(response, dict) else []
    return {
        "mode": mode,
        "total": total,
        "installed": installed,
        "enabled": enabled,
        "marketplaces": marketplaces,
        "marketplaceLoadErrors": safe_errors,
        "featuredPluginIds": [_text(item, 160) for item in featured] if isinstance(featured, list) else [],
    }


def _emit_result(session, call_id, name, input_obj, result, method):
    if hasattr(session, "_mcp_result_events"):
        session._mcp_result_events(call_id, name, input_obj, result, method)
        return True
    if not hasattr(session, "_record_and_broadcast"):
        return False
    session._record_and_broadcast({
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "id": call_id, "name": name, "input": input_obj or {}}]},
    })
    session._record_and_broadcast({
        "type": "user",
        "message": {"content": [{
            "type": "tool_result",
            "tool_use_id": call_id,
            "content": codex_text.compact_json(result or {}, 5000),
        }]},
    })
    return True


def list_skills(session, arg):
    words = _words(arg)
    if len(words) > 1:
        return {"ok": False, "error": "usage: /skills [all|enabled|disabled]"}
    mode = SKILL_MODES.get(words[0].lower() if words else "")
    if not mode:
        return {"ok": False, "error": "usage: /skills [all|enabled|disabled]"}
    params = {"cwd": getattr(session, "cwd", "")}
    response = session._client().request("skills/list", params, timeout=30) or {}
    payload = skills_payload(response, mode=mode)
    _emit_result(
        session,
        "codex-skills-%d" % int(time.time() * 1000),
        "codex.skills",
        {"mode": mode, "cwd": params["cwd"]},
        payload,
        "skills/list",
    )
    session._codex_notice(
        "Codex skills: %d total, %d enabled, %d disabled" % (
            payload.get("total") or 0,
            payload.get("enabled") or 0,
            payload.get("disabled") or 0,
        ),
        "skills/list",
        payload,
    )
    return {"ok": True, "command": "skills", "mode": mode, "skills": payload.get("total") or 0}


def list_plugins(session, arg):
    words = _words(arg)
    if len(words) > 1:
        return {"ok": False, "error": "usage: /plugins [installed|available]"}
    mode_method = PLUGIN_MODES.get(words[0].lower() if words else "")
    if not mode_method:
        return {"ok": False, "error": "usage: /plugins [installed|available]"}
    mode, method = mode_method
    params = {}
    response = session._client().request(method, params, timeout=30) or {}
    payload = plugins_payload(response, mode=mode)
    _emit_result(
        session,
        "codex-plugins-%d" % int(time.time() * 1000),
        "codex.plugins",
        {"mode": mode},
        payload,
        method,
    )
    errors = len(payload.get("marketplaceLoadErrors") or [])
    suffix = ", %d marketplace load errors" % errors if errors else ""
    session._codex_notice(
        "Codex plugins: %d listed%s" % (payload.get("total") or 0, suffix),
        method,
        payload,
    )
    return {"ok": True, "command": "plugins", "mode": mode, "plugins": payload.get("total") or 0}

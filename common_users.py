# -*- coding: utf-8 -*-
"""Per-user state, workspace roots, and request identity helpers."""
import hashlib
import json
import os
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class UserSettings:
    base_dir: str
    user_data_dir: str
    default_workspace_root: str
    allow_unconfigured_paths: bool
    primary_user_uses_default_homes: bool
    claude_home: str
    users: dict


def safe_user_id(user):
    """Stable filesystem-safe id for a login name."""
    raw = (user or "").strip() or "user"
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw).strip(".-")[:32] or "user"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return "%s-%s" % (slug, digest)


def format_user_path(template, user, uid, settings):
    val = (template or "").replace("{user}", user or "").replace("{uid}", uid or "")
    if not val:
        return ""
    return os.path.abspath(os.path.join(settings.base_dir, val) if not os.path.isabs(val) else val)


def user_state_dir(user, settings):
    return os.path.join(settings.user_data_dir, safe_user_id(user))


def primary_user(settings):
    try:
        return next(iter(settings.users.keys()))
    except StopIteration:
        return ""


def user_uses_default_homes(user, settings):
    return bool(settings.primary_user_uses_default_homes and user and user == primary_user(settings))


def user_claude_home(user, settings, state_dir=None):
    if user_uses_default_homes(user, settings):
        return os.path.abspath(settings.claude_home)
    return os.path.join(state_dir or user_state_dir(user, settings), "claude-home")


def user_codex_home(user, settings, state_dir=None):
    if user_uses_default_homes(user, settings):
        return ""
    return os.path.join(state_dir or user_state_dir(user, settings), "codex-home")


def user_profile_path(user, settings):
    return os.path.join(user_state_dir(user, settings), "profile.json")


def load_user_profile(user, settings):
    try:
        with open(user_profile_path(user, settings), "r", encoding="utf-8") as f:
            obj = json.load(f)
        return obj if isinstance(obj, dict) else {}
    except (OSError, ValueError):
        return {}


def user_workspace_roots(user, settings):
    uid = safe_user_id(user)
    roots = []
    profile = load_user_profile(user, settings)
    raw = profile.get("workspace_roots")
    if isinstance(raw, list):
        roots.extend(x for x in raw if isinstance(x, str) and x.strip())
    default_root = format_user_path(settings.default_workspace_root, user or "", uid, settings)
    if default_root:
        roots.append(default_root)
    out, seen = [], set()
    for root in roots:
        path = format_user_path(root, user or "", uid, settings)
        key = os.path.normcase(os.path.abspath(path))
        if key and key not in seen:
            seen.add(key)
            out.append(os.path.abspath(path))
    return out


def ensure_user_dirs(user, settings):
    state_dir = user_state_dir(user, settings)
    os.makedirs(state_dir, exist_ok=True)
    for root in user_workspace_roots(user, settings):
        try:
            os.makedirs(root, exist_ok=True)
        except OSError:
            pass
    return state_dir


def user_context(user, settings):
    user = (user or "").strip()
    if not user or user not in settings.users:
        return None
    ensure_user_dirs(user, settings)
    state_dir = user_state_dir(user, settings)
    return {
        "user": user,
        "uid": safe_user_id(user),
        "state_dir": state_dir,
        "registry_path": os.path.join(state_dir, "sessions.json"),
        "workspace_roots": user_workspace_roots(user, settings),
        "claude_home": user_claude_home(user, settings),
        "codex_home": user_codex_home(user, settings),
        "uses_default_homes": user_uses_default_homes(user, settings),
        "profile": load_user_profile(user, settings),
    }


def request_user(handler, settings, verify_session_token):
    """Return the authenticated user from a web cookie or trusted manager header."""
    huser = (handler.headers.get("X-Agent-Cockpit-User") or "").strip()
    if huser and huser in settings.users:
        return huser
    cookie = handler.headers.get("Cookie", "")
    token = ""
    for part in cookie.split(";"):
        part = part.strip()
        if part.partition("=")[0] == "ac_session":
            token = part.partition("=")[2]
            break
    return verify_session_token(token) if token else None


def path_allowed_for_user(user, path, settings):
    if settings.allow_unconfigured_paths:
        return True
    roots = user_workspace_roots(user, settings)
    if not roots:
        return True
    try:
        target = os.path.normcase(os.path.abspath(path))
        for root in roots:
            allowed = os.path.normcase(os.path.abspath(root))
            if target == allowed or target.startswith(allowed.rstrip("\\/") + os.sep):
                return True
    except (TypeError, ValueError):
        pass
    return False


def workspace_overview(user, settings):
    return [{"name": os.path.basename(r.rstrip("\\/")) or r, "path": r}
            for r in user_workspace_roots(user, settings)]

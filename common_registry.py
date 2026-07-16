# -*- coding: utf-8 -*-
"""Persisted native-session registry helpers."""
import json
import os
import threading
from dataclasses import dataclass

REG_LOCK = threading.Lock()


@dataclass(frozen=True)
class RegistrySettings:
    registry_path: str
    scrollback_dir: str
    user_state_dir: object


def registry_path(user=None, state_dir=None, settings=None):
    if state_dir:
        return os.path.join(state_dir, "sessions.json")
    if user and settings and settings.user_state_dir:
        return os.path.join(settings.user_state_dir(user), "sessions.json")
    return settings.registry_path


def registry_load(user=None, state_dir=None, settings=None):
    path = registry_path(user, state_dir, settings)
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        return obj or {}
    except (OSError, ValueError):
        return {}


def registry_read(user=None, state_dir=None, settings=None):
    obj = registry_load(user, state_dir, settings)
    if not isinstance(obj, dict):
        obj = {"version": 1, "sessions": {}}
    if not isinstance(obj.get("sessions"), dict):
        obj["sessions"] = {}
    return obj


def registry_write(obj, user=None, state_dir=None, settings=None):
    path = registry_path(user, state_dir, settings)
    with REG_LOCK:
        registry_write_unlocked(obj, user, state_dir, settings, path=path)


def registry_write_unlocked(obj, user=None, state_dir=None, settings=None, path=None):
    path = path or registry_path(user, state_dir, settings)
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def registry_save(entries, manager_pid, user=None, state_dir=None, settings=None):
    registry_write({"version": 1, "manager_pid": manager_pid, "sessions": entries}, user, state_dir, settings)


def registry_upsert(sid, entry, manager_pid, user=None, state_dir=None, settings=None):
    with REG_LOCK:
        obj = registry_read(user, state_dir, settings)
        obj["sessions"][sid] = entry
        obj["manager_pid"] = manager_pid
        registry_write_unlocked(obj, user, state_dir, settings)


def registry_drop(sid, user=None, state_dir=None, settings=None):
    changed = False
    with REG_LOCK:
        obj = registry_read(user, state_dir, settings)
        if sid in obj["sessions"]:
            obj["sessions"].pop(sid, None)
            changed = True
        if changed:
            registry_write_unlocked(obj, user, state_dir, settings)
    try:
        os.unlink(os.path.join(settings.scrollback_dir, "%s.log" % sid))
    except OSError:
        pass


def registry_clear(manager_pid, user=None, state_dir=None, settings=None):
    registry_write({"version": 1, "manager_pid": manager_pid, "sessions": {}}, user, state_dir, settings)

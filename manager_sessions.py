# -*- coding: utf-8 -*-
"""Session lifecycle, persistence, and recovery helpers for the manager."""
import os
import threading
import time

import common
from codex_native import CodexSession, shutdown_app_server
from native import NativeSession


# sid -> {dir, title, started, mode, session_id, backend, provider, native}
sessions = {}
lock = threading.Lock()
sid_counter = [0]
_reattached = False


def sid_num(sid):
    try:
        return int(sid[1:]) if sid.startswith("s") and sid[1:].isdigit() else 0
    except Exception:
        return 0


def state_sid_taken(sid, state_dir):
    state_dir = state_dir or common.STATE_DIR
    return (
        os.path.exists(os.path.join(state_dir, "codex_%s.json" % sid))
        or os.path.exists(os.path.join(state_dir, "native_%s.json" % sid))
    )


def seed_sid_from_state_dir(state_dir):
    try:
        names = os.listdir(state_dir or common.STATE_DIR)
    except OSError:
        return
    max_sid = 0
    for name in names:
        if not (name.startswith("codex_s") or name.startswith("native_s")) or not name.endswith(".json"):
            continue
        sid = name.rsplit(".", 1)[0].split("_", 1)[1]
        max_sid = max(max_sid, sid_num(sid))
    if max_sid:
        with lock:
            sid_counter[0] = max(sid_counter[0], max_sid)


def prune_dead():
    dead = []
    dead_state = {}
    with lock:
        for sid, session in sessions.items():
            native = session.get("native")
            if not native or not native.alive:
                dead.append(sid)
                dead_state[sid] = session.get("state_dir")
        for sid in dead:
            sessions.pop(sid, None)
    for sid in dead:
        common.registry_drop(sid, state_dir=dead_state.get(sid))


def kill_session(sid):
    with lock:
        session = sessions.pop(sid, None)
    if not session:
        return False
    native = session.get("native")
    if native:
        try:
            native.close()
        except Exception:
            pass
    common.registry_drop(sid, state_dir=session.get("state_dir"))
    return True


def kill_all():
    with lock:
        sids = list(sessions.keys())
    for sid in sids:
        kill_session(sid)
    try:
        shutdown_app_server()
    except Exception:
        pass


def persist_sessions():
    """Persist live session registry without closing sessions."""
    try:
        with lock:
            snap = {sid: dict(session) for sid, session in sessions.items()}
        by_state = {}
        for sid, session in snap.items():
            state_dir = session.get("state_dir") or common.STATE_DIR
            by_state.setdefault(state_dir, {})[sid] = common._registry_safe_entry(sid, session)
        for state_dir, entries in by_state.items():
            common.registry_save(entries, state_dir=state_dir)
    except Exception:
        pass


def idle_sweaper(interval=60, ttl=1800):
    """Release idle, disconnected Claude sessions while keeping transcript history."""
    while True:
        try:
            time.sleep(interval)
            now = time.time()
            to_kill = []
            with lock:
                for sid, session in list(sessions.items()):
                    if common.is_codex_backend(session.get("backend", "")):
                        continue
                    native = session.get("native")
                    if not native or getattr(native, "_closed", False) or not getattr(native, "alive", False):
                        continue
                    if getattr(native, "clients", None):
                        continue
                    proc = getattr(native, "_proc", None)
                    if proc is not None and proc.poll() is None:
                        continue
                    if getattr(native, "_pending", None):
                        continue
                    if now - float(getattr(native, "last_activity", 0) or 0) > ttl:
                        to_kill.append(sid)
            for sid in to_kill:
                try:
                    kill_session(sid)
                except Exception:
                    pass
        except Exception:
            pass


def session_title(cwd, title):
    return title or os.path.basename(cwd.rstrip(os.sep)) or cwd


def backend_available(backend):
    backend = common.normalize_backend(backend)
    return backend in common.BACKENDS


def _session_class(backend):
    backend = common.normalize_backend(backend)
    if backend == "claude_native":
        if not common.CLAUDE_BIN or not os.path.isfile(common.CLAUDE_BIN):
            raise RuntimeError("Claude CLI was not found. Install claude or set [binaries] claude in config.ini.")
        return backend, "claude", NativeSession
    if backend == "codex_native":
        if not common.CODEX_BIN or not os.path.isfile(common.CODEX_BIN):
            raise RuntimeError("Codex CLI was not found. Install codex or set [binaries] codex in config.ini.")
        return backend, "codex", CodexSession
    raise RuntimeError("unsupported backend: %s" % backend)


def launch_native(cwd, title="", auto_approve=None, mode="new", session_id=None,
                  events=None, backend=None, ctx=None, codex_config=None):
    """Create one web-rendered agent session."""
    ctx = ctx or {}
    user = ctx.get("user", "")
    uid = ctx.get("uid", "")
    state_dir = ctx.get("state_dir") or common.STATE_DIR
    claude_home = ctx.get("claude_home")
    codex_home = ctx.get("codex_home")
    backend, provider, cls = _session_class(backend)
    prune_dead()
    if auto_approve is None:
        auto_approve = common.AUTO_APPROVE
    with lock:
        kwargs = {"user": user, "uid": uid, "state_dir": state_dir}
        while True:
            sid_counter[0] += 1
            sid = "s%d" % sid_counter[0]
            if not state_sid_taken(sid, state_dir):
                break
        if provider == "claude":
            kwargs["claude_home"] = claude_home
        else:
            kwargs["codex_home"] = codex_home
        if provider == "codex":
            kwargs["cfg"] = codex_config or {}
        native = cls(sid, cwd, yolo=bool(auto_approve), **kwargs)
        if provider == "claude" and session_id:
            native.claude_sid = session_id
        elif provider == "codex" and session_id:
            native.thread_id = session_id
        if events:
            if provider == "codex" and hasattr(native, "_adopt_history_replay"):
                native._adopt_history_replay(events)
            else:
                native.events = list(events)
        if provider == "codex" and not session_id:
            native._persist()
        elif provider == "codex" and getattr(native, "thread_id", None):
            native._client().register(native.thread_id, native)
        sessions[sid] = {
            "dir": cwd,
            "backend": backend,
            "provider": provider,
            "title": session_title(cwd, title),
            "started": time.time(),
            "mode": mode,
            "session_id": session_id,
            "thread_id": getattr(native, "thread_id", None),
            "user": user,
            "uid": uid,
            "state_dir": state_dir,
            "claude_home": claude_home,
            "codex_home": codex_home,
            "codex_config": codex_config or {},
            "native": native,
        }
        snap = dict(sessions[sid])
    common.registry_upsert(sid, common._registry_safe_entry(sid, snap), state_dir=state_dir)
    return sid


def reattach_sessions():
    """Recover persisted native sessions after a manager restart."""
    global _reattached
    if _reattached:
        return
    _reattached = True
    try:
        os.makedirs(common.STATE_DIR, exist_ok=True)
    except OSError:
        pass
    sources = []
    for user in sorted(common.USERS.keys()):
        ctx = common.user_context(user)
        if ctx:
            sources.append((ctx, common.registry_load(state_dir=ctx.get("state_dir"))))
    # Compatibility: old single-user state is assigned to the first configured user.
    if common.USERS:
        first_user = next(iter(common.USERS.keys()))
        legacy = common.registry_load()
        if isinstance(legacy.get("sessions") if isinstance(legacy, dict) else None, dict):
            ctx = common.user_context(first_user)
            if ctx:
                legacy_ctx = dict(ctx)
                legacy_ctx["state_dir"] = common.STATE_DIR
                sources.append((legacy_ctx, legacy))
    for ctx, registry in sources:
        seed_sid_from_state_dir(ctx.get("state_dir"))
        persisted_sessions = registry.get("sessions") if isinstance(registry, dict) else None
        if not isinstance(persisted_sessions, dict) or not persisted_sessions:
            continue
        for sid, entry in list(persisted_sessions.items()):
            reattach_one(ctx, sid, entry)


def reattach_one(ctx, sid, entry):
    if not isinstance(entry, dict):
        common.registry_drop(sid, state_dir=ctx.get("state_dir"))
        return
    backend = common.normalize_backend(entry.get("backend") or (
        "codex_native" if entry.get("provider") == "codex" else "claude_native"
    ))
    provider = "codex" if common.is_codex_backend(backend) else "claude"
    state_dir = entry.get("state_dir") or ctx.get("state_dir") or common.STATE_DIR
    claude_home = entry.get("claude_home") or ctx.get("claude_home")
    codex_home = entry.get("codex_home") or ctx.get("codex_home")
    if provider == "codex":
        native = CodexSession.recover(sid, entry.get("dir", ""), entry.get("thread_id") or entry.get("session_id"),
                                      user=ctx.get("user", ""), uid=ctx.get("uid", ""), state_dir=state_dir,
                                      codex_home=codex_home)
    else:
        native = NativeSession.recover(sid, entry.get("dir", ""),
                                       user=ctx.get("user", ""), uid=ctx.get("uid", ""), state_dir=state_dir,
                                       claude_home=claude_home)
    if not native:
        common.registry_drop(sid, state_dir=state_dir)
        return
    if "yolo" in entry:
        try:
            native.yolo = bool(entry.get("yolo"))
        except Exception:
            pass
    with lock:
        sessions[sid] = {
            "dir": entry.get("dir", getattr(native, "cwd", "")),
            "backend": backend,
            "provider": provider,
            "title": entry.get("title", ""),
            "started": entry.get("started", time.time()),
            "mode": entry.get("mode", "new"),
            "session_id": entry.get("session_id") or getattr(native, "claude_sid", None) or getattr(native, "thread_id", None),
            "thread_id": entry.get("thread_id") or getattr(native, "thread_id", None),
            "user": ctx.get("user", ""),
            "uid": ctx.get("uid", ""),
            "state_dir": state_dir,
            "claude_home": claude_home,
            "codex_home": codex_home,
            "native": native,
        }
        sid_counter[0] = max(sid_counter[0], sid_num(sid))


def owned_session(sid, ctx):
    with lock:
        session = sessions.get(sid)
    if not session:
        return None
    if ctx and session.get("user") and session.get("user") != ctx.get("user"):
        return None
    return session


def session_items_for_user(user, host=""):
    prune_dead()
    with lock:
        items = [common.session_obj(sid, session, host)
                 for sid, session in sessions.items() if session.get("user") == user]
    items.sort(key=lambda item: item["started"], reverse=True)
    return items


def owned_sids(user):
    with lock:
        return [sid for sid, session in sessions.items() if session.get("user") == user]


def history_belongs_to_other_user(history_sid, user):
    if not history_sid:
        return False
    with lock:
        current = list(sessions.values())
    return any(
        session.get("user") != user
        and (
            getattr(session.get("native"), "claude_sid", None) == history_sid
            or getattr(session.get("native"), "thread_id", None) == history_sid
        )
        for session in current
    )

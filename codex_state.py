# -*- coding: utf-8 -*-
"""Codex session state persistence and recovery helpers."""
import json
import os


class CodexSessionState:
    def __init__(self, session, replay_max_events):
        self.session = session
        self.replay_max_events = replay_max_events

    def path(self):
        return os.path.join(self.session.state_dir, "codex_%s.json" % self.session.sid)

    def payload(self):
        session = self.session
        return {
            "thread_id": session.thread_id,
            "last_turn_id": session.last_turn_id,
            "cwd": session.cwd,
            "yolo": session.yolo,
            "cfg": session.cfg,
            "user": session.user,
            "uid": session.uid,
            "codex_home": session.codex_home,
            "model": session.model,
            "model_provider": session.model_provider,
            "service_tier": session.service_tier,
            "busy": bool(session._busy),
            "current_turn_started_at": session.current_turn_started_at,
            "awaiting_plan_decision": bool(getattr(session, "_awaiting_plan_decision", False)),
            "events": session.events[-50:],
            "timeline": session.timeline[-self.replay_max_events:],
            "next_seq": session._next_seq,
        }

    def persist(self):
        try:
            os.makedirs(self.session.state_dir, exist_ok=True)
            with open(self.path(), "w", encoding="utf-8") as handle:
                json.dump(self.payload(), handle, ensure_ascii=False)
            return True
        except OSError:
            return False

    def apply_recovered(self, data, expected_thread_id=None, drop_noise_fn=None):
        session = self.session
        drop_noise_fn = drop_noise_fn or (lambda events: events)
        session.thread_id = expected_thread_id or data.get("thread_id")
        session.last_turn_id = data.get("last_turn_id")
        session.model = data.get("model") or ""
        session.model_provider = data.get("model_provider") or ""
        session.service_tier = data.get("service_tier") or ""
        session._busy = bool(data.get("busy"))
        session.current_turn_started_at = data.get("current_turn_started_at") if session._busy else None
        session._awaiting_plan_decision = bool(data.get("awaiting_plan_decision"))
        session.events = drop_noise_fn(data.get("events") or [])
        session.timeline = drop_noise_fn(data.get("timeline") or list(session.events))
        try:
            seqs = [int(event.get("seq") or 0) for event in session.timeline]
            seqs.append(int(data.get("next_seq") or 1) - 1)
            session._next_seq = max(seqs) + 1
        except Exception:
            session._next_seq = int(data.get("next_seq") or 1)
        return session


def state_path(state_dir, sid):
    return os.path.join(state_dir, "codex_%s.json" % sid)


def load_state_data(state_dir, sid):
    with open(state_path(state_dir, sid), "r", encoding="utf-8") as handle:
        return json.load(handle)


def recover_session(session_cls, sid, cwd, expected_thread_id=None, user="", uid="",
                    state_dir=None, codex_home=None, default_state_dir=None,
                    replay_max_events=400, drop_noise_fn=None):
    state_dir = state_dir or default_state_dir
    if not state_dir:
        return None
    try:
        data = load_state_data(state_dir, sid)
        session = session_cls(
            sid,
            data.get("cwd") or cwd,
            yolo=bool(data.get("yolo")),
            cfg=data.get("cfg") or {},
            user=user or data.get("user", ""),
            uid=uid or data.get("uid", ""),
            state_dir=state_dir,
            codex_home=codex_home or data.get("codex_home"),
        )
        CodexSessionState(session, replay_max_events).apply_recovered(
            data, expected_thread_id=expected_thread_id, drop_noise_fn=drop_noise_fn)
        if session.thread_id:
            # Startup recovery must stay local-only; thread/read starts the
            # Codex app-server and can stall the whole manager on boot.
            session._client().register(session.thread_id, session)
        return session
    except (OSError, ValueError):
        return None

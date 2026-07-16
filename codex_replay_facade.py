# -*- coding: utf-8 -*-
"""Facade for Codex replay/timeline coordination.

This keeps CodexSession's public compatibility methods intact while moving the
replay-specific seams behind one small object.
"""
import time

import codex_replay


class CodexReplayFacade:
    def __init__(self, session, max_events, stream_max_chars, persist_interval=1.5):
        self.session = session
        self.max_events = max_events
        self.stream_max_chars = stream_max_chars
        self.persist_interval = persist_interval

    @staticmethod
    def is_dangerous(text):
        return codex_replay.is_dangerous(text)

    @staticmethod
    def tool_result_id(event):
        return codex_replay.tool_result_id(event)

    @staticmethod
    def replay_content_score(events):
        return codex_replay.replay_content_score(events)

    @staticmethod
    def drop_recover_noise(events):
        return codex_replay.drop_recover_noise(events)

    @staticmethod
    def event_after_seq(event, after_seq):
        return codex_replay.event_after_seq(event, after_seq)

    def event_identity_locked(self, event):
        return codex_replay.event_identity(self.session, event)

    def record_timeline_locked(self, event):
        return codex_replay.record_timeline(
            self.session, event, self.max_events, self.stream_max_chars)

    def merge_timeline_event_locked(self, event):
        return codex_replay.merge_timeline_event(
            self.session, event, self.stream_max_chars)

    def adopt_history_replay(self, events):
        return codex_replay.adopt_history_replay(
            self.session, events, self.max_events, self.stream_max_chars)

    def decorate_for_broadcast(self, event):
        with self.session._lock:
            return self.record_timeline_locked(event)

    @staticmethod
    def should_poll_event(event):
        return (event or {}).get("type") not in ("replay_batch", "state_snapshot", "codex_usage")

    @staticmethod
    def should_persist_event(event):
        typ = (event or {}).get("type") if isinstance(event, dict) else ""
        return typ in ("assistant", "user", "result", "pending_approval", "pending_ask",
                       "pending_form", "interrupted")

    def record_poll_event(self, event):
        if not self.should_poll_event(event):
            return
        with self.session._lock:
            self.session.poll_events.append(dict(event))
            if len(self.session.poll_events) > self.max_events:
                self.session.poll_events = self.session.poll_events[-self.max_events:]

    def prepare_broadcast(self, event):
        out = self.decorate_for_broadcast(event)
        self.record_poll_event(out)
        return out

    def persist_if_due(self, event, now_fn=None):
        now = (now_fn or time.time)()
        if self.should_persist_event(event) or now - self.session._last_persist >= self.persist_interval:
            self.session._last_persist = now
            self.session._persist()
            return True
        return False

    def events_after_seq(self, after_seq=0):
        return codex_replay.events_after_seq(self.session, after_seq)

    def replay_payload(self, after_seq=0):
        return codex_replay.replay_payload(self.session, after_seq)

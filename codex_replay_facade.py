# -*- coding: utf-8 -*-
"""Facade for Codex replay/timeline coordination.

This keeps CodexSession's public compatibility methods intact while moving the
replay-specific seams behind one small object.
"""
import codex_replay


class CodexReplayFacade:
    def __init__(self, session, max_events, stream_max_chars):
        self.session = session
        self.max_events = max_events
        self.stream_max_chars = stream_max_chars

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

    def events_after_seq(self, after_seq=0):
        return codex_replay.events_after_seq(self.session, after_seq)

    def replay_payload(self, after_seq=0):
        return codex_replay.replay_payload(self.session, after_seq)

# -*- coding: utf-8 -*-
"""Codex notification adapter facade."""
import codex_session_events


class CodexNotificationAdapter:
    def __init__(self, session):
        self.session = session

    def remember_codex_debug_notice(self, message, method=None, params=None):
        return codex_session_events.remember_codex_debug_notice(
            self.session, message, method=method, params=params)

    def remember_route_debug(self, message, method=None, params=None):
        return codex_session_events.remember_route_debug(
            self.session, message, method=method, params=params)

    def codex_notice(self, message, method=None, params=None, level=None, silent=False):
        return codex_session_events.codex_notice(
            self.session, message, method=method, params=params, level=level, silent=silent)

    @staticmethod
    def updated_event_notice_message(params):
        return codex_session_events.updated_event_notice_message(params)

    def handle_updated_event(self, method, params):
        return codex_session_events.handle_updated_event(self.session, method, params)

    def handle_notification(self, method, params):
        return codex_session_events.handle_notification(self.session, method, params)

    def on_turn_completed(self, turn):
        return codex_session_events.on_turn_completed(self.session, turn)

    def on_item_started(self, item):
        return codex_session_events.on_item_started(self.session, item)

    def on_item_completed(self, item):
        return codex_session_events.on_item_completed(self.session, item)

    def flush_pending_plan_items(self):
        return codex_session_events.flush_pending_plan_items(self.session)

    def on_plan_updated(self, params):
        return codex_session_events.on_plan_updated(self.session, params)

    def on_thread_settings_updated(self, settings):
        return codex_session_events.on_thread_settings_updated(self.session, settings)

    @staticmethod
    def usage_for_meta(usage):
        return codex_session_events.usage_for_meta(usage)

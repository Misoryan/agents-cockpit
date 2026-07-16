# -*- coding: utf-8 -*-
"""Broadcast and push-notification helpers for Codex sessions."""
import json
import threading
import time


def push_notify_worker(notify_module, title, body, event, webhook_body=None):
    try:
        notify_module.push_notify(title, body, event, webhook_body=webhook_body)
    except Exception:
        pass


class CodexBroadcastAdapter:
    def __init__(self, session, ws_send_fn, notify_module,
                 thread_factory=None, time_fn=None):
        self.session = session
        self.ws_send = ws_send_fn
        self.notify = notify_module
        self.thread_factory = thread_factory or threading.Thread
        self.time_fn = time_fn or time.time

    @staticmethod
    def encode_event(event):
        return json.dumps(event, ensure_ascii=False).encode("utf-8")

    def send_to_clients(self, event):
        data = self.encode_event(event)
        with self.session.clients_lock:
            clients = list(self.session.clients)
        dead = []
        for client in clients:
            try:
                self.ws_send(client, data, 0x1)
            except OSError:
                dead.append(client)
        if dead:
            with self.session.clients_lock:
                for client in dead:
                    self.session.clients.discard(client)

    def broadcast_transient(self, event):
        self.send_to_clients(event)

    def broadcast(self, event):
        event = self.session._replay.prepare_broadcast(event)
        self.send_to_clients(event)
        self.session._persist_if_due(event)
        return event

    def send_one(self, sock, event):
        try:
            self.ws_send(sock, self.encode_event(event), 0x1)
        except OSError:
            with self.session.clients_lock:
                self.session.clients.discard(sock)

    def push(self, event, title, body, webhook_body=None):
        try:
            if not self.notify._notify_enabled_for(event):
                return False
            now = self.time_fn()
            if now - self.session._last_notify.get(event, 0.0) < self.notify.NOTIFY_MIN_INTERVAL:
                return False
            self.session._last_notify[event] = now
        except Exception:
            pass
        worker = self.thread_factory(
            target=push_notify_worker,
            args=(self.notify, title or "", body or "", event, webhook_body),
            daemon=True,
        )
        worker.start()
        return True

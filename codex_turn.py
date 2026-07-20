# -*- coding: utf-8 -*-
"""Codex turn/thread lifecycle helpers."""
import time

import codex_config


TASK_SYSTEM = (
    "Task mode: for multi-step work, keep a concise todo list and update it as "
    "you make progress so the user can follow the task state."
)


class CodexTurnRunner:
    def __init__(self, session):
        self.session = session

    def thread_params(self):
        session = self.session
        params = {"cwd": session.cwd}
        if session.cfg.get("model"):
            params["model"] = session.cfg["model"]
        if session.cfg.get("approval_policy"):
            params["approvalPolicy"] = session.cfg["approval_policy"]
        if session.cfg.get("sandbox"):
            params["sandbox"] = session.cfg["sandbox"]
        if session.cfg.get("service_tier"):
            params["serviceTier"] = session.cfg["service_tier"]
        config = codex_config.thread_config(session.cfg)
        if config:
            params["config"] = config
        if session.yolo:
            params["approvalPolicy"] = "never"
            params["sandbox"] = "danger-full-access"
        return params

    def turn_params(self, prompt, image_inputs=None):
        session = self.session
        text = prompt
        if session.task_mode:
            text = TASK_SYSTEM + "\n\n" + text
        params = {
            "threadId": session.thread_id,
            "cwd": session.cwd,
            "input": session._user_input_items(text, image_inputs=image_inputs),
            "collaborationMode": self.collaboration_mode(),
        }
        if session.cfg.get("model"):
            params["model"] = session.cfg["model"]
        if session.cfg.get("service_tier"):
            params["serviceTier"] = session.cfg["service_tier"]
        if session.cfg.get("reasoning_effort"):
            params["effort"] = session.cfg["reasoning_effort"]
        if session.cfg.get("reasoning_summary"):
            params["summary"] = session.cfg["reasoning_summary"]
        if session.yolo:
            params["approvalPolicy"] = "never"
            params["sandboxPolicy"] = {"type": "dangerFullAccess"}
        else:
            if session.cfg.get("approval_policy"):
                params["approvalPolicy"] = session.cfg["approval_policy"]
            sandbox = codex_config.sandbox_policy(
                session.cfg.get("sandbox"), session.cwd, session.cfg.get("writable_roots"))
            if sandbox:
                params["sandboxPolicy"] = sandbox
        return params

    def collaboration_mode(self):
        session = self.session
        return {
            "mode": "plan" if session.plan_mode else "default",
            "settings": {
                "model": session.model or session.cfg.get("model") or "",
                "reasoning_effort": session.cfg.get("reasoning_effort") or None,
                "developer_instructions": None,
            },
        }

    def sync_collaboration_mode(self):
        session = self.session
        if not session.thread_id:
            return
        try:
            session._client().request(
                "thread/settings/update",
                {"threadId": session.thread_id, "collaborationMode": self.collaboration_mode()},
                timeout=15,
            )
        except Exception as exc:
            session._codex_notice(
                "Failed to update Codex Plan mode",
                "thread/settings/update",
                {"mode": "plan" if session.plan_mode else "default", "error": str(exc)},
            )

    def apply_thread_response(self, response):
        session = self.session
        if not isinstance(response, dict):
            return
        thread = response.get("thread") or {}
        new_thread_id = thread.get("id") or thread.get("sessionId")
        if session.thread_id and new_thread_id and new_thread_id != session.thread_id:
            session._codex_notice(
                "Ignored Codex thread update for a different thread",
                "thread/started",
                {"currentThreadId": session.thread_id, "incomingThreadId": new_thread_id},
                level="debug",
                silent=True,
            )
            return
        session.thread_id = new_thread_id or session.thread_id
        session.model = response.get("model") or session.model or session.cfg.get("model") or ""
        session.model_provider = response.get("modelProvider") or session.model_provider
        session.service_tier = response.get("serviceTier") or session.service_tier
        if session.thread_id:
            session._client().register(session.thread_id, session)
        if session.model:
            session._record_and_broadcast({
                "type": "system",
                "model": session.model,
                "version": thread.get("cliVersion"),
            })

    def ensure_thread(self):
        session = self.session
        client = session._client()
        client.ensure()
        if session.thread_id:
            client.register(session.thread_id, session)
        if session._thread_ready:
            return
        if session.thread_id:
            response = client.request(
                "thread/resume",
                {"threadId": session.thread_id, "cwd": session.cwd, "excludeTurns": True},
                timeout=30,
            )
            self.apply_thread_response(response)
            session._thread_ready = True
        else:
            session.start()

    def run_turn(self, prompt, image_inputs=None):
        session = self.session
        session._busy = True
        if not session.current_turn_started_at:
            session.current_turn_started_at = time.time()
        session.last_activity = time.time()
        try:
            self.ensure_thread()
            self.sync_collaboration_mode()
            response = session._client().request(
                "turn/start", self.turn_params(prompt, image_inputs=image_inputs), timeout=30)
            turn = (response or {}).get("turn") or {}
            session.last_turn_id = turn.get("id") or session.last_turn_id
            if session.last_turn_id:
                session._client().register_turn(session.last_turn_id, session)
            session._persist()
        except Exception as exc:
            session.last_completed_at = time.time()
            session._busy = False
            session.current_turn_started_at = None
            session._record_and_broadcast({"type": "result", "error": "Codex turn failed: %s" % exc})
            session._persist()

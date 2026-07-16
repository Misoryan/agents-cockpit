# -*- coding: utf-8 -*-
"""Codex app-server process and JSON-RPC client."""
import json
import os
import subprocess
import threading
import time
import traceback

import codex_routing
import codex_text
import common


_UNROUTED_MAX = 120
_UNROUTED_TTL = 10.0


class AppServerRequestError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = int(code)
        self.message = str(message)


class CodexAppServerClient:
    def __init__(self, user="", uid="", state_dir=None, codex_home=None):
        self.user = user or ""
        self.uid = uid or "default"
        self.state_dir = state_dir
        self.codex_home = os.path.join(state_dir, "codex-home") if codex_home is None and state_dir else codex_home
        self.proc = None
        self.lock = threading.RLock()
        self.next_id = 1
        self.pending = {}
        self.sessions = {}
        self.turn_sessions = {}
        self.item_sessions = {}
        self.command_exec_output_handlers = {}
        self.unrouted_events = []
        self.stderr_tail = []
        self.initialized = False
        self.dead = False
        self._starting = False
        self._start_done = threading.Event()
        self._start_done.set()
        self._expected_exit_procs = set()

    def ensure(self):
        while True:
            with self.lock:
                if self.proc and self.proc.poll() is None and self.initialized:
                    return
                if not self._starting:
                    self._starting = True
                    self._start_done = threading.Event()
                    break
                wait_for = self._start_done
            if not wait_for.wait(45):
                raise RuntimeError("Codex app-server start timed out")
        self._start_locked()

    def _start_locked(self):
        try:
            with self.lock:
                self.shutdown()
                argv = common.codex_argv("app-server", "--stdio")
                if not argv:
                    raise RuntimeError("Codex CLI was not found. Install codex or set [binaries] codex in config.ini.")
                env = dict(os.environ)
                if self.codex_home:
                    os.makedirs(self.codex_home, exist_ok=True)
                    env["CODEX_HOME"] = self.codex_home
                if self.user:
                    env["AGENT_COCKPIT_USER"] = self.user
                self.dead = False
                self.initialized = False
                self.proc = subprocess.Popen(
                    argv,
                    cwd=common.HERE,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    creationflags=common.CREATE_NO_WINDOW if os.name == "nt" else 0,
                    env=env,
                )
                threading.Thread(target=self._read_stdout, daemon=True).start()
                threading.Thread(target=self._read_stderr, daemon=True).start()
            res = self.request(
                "initialize",
                {
                    "clientInfo": {"name": "agents-cockpit", "title": "Agents Cockpit", "version": "0", "user": self.user},
                    "capabilities": {
                        "experimentalApi": True,
                        "mcpServerOpenaiFormElicitation": True,
                        "requestAttestation": False,
                    },
                },
                timeout=15,
                ensure_started=False,
            )
            if res is None:
                raise RuntimeError("Codex app-server initialize returned no response")
            with self.lock:
                if not self.proc or self.proc.poll() is not None:
                    raise RuntimeError("Codex app-server exited during initialize")
                self.initialized = True
        except Exception:
            self.shutdown()
            raise
        finally:
            with self.lock:
                self._starting = False
                self._start_done.set()

    def _read_stdout(self):
        proc = self.proc
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                self._dispatch(msg)
        except Exception:
            traceback.print_exc()
        finally:
            with self.lock:
                expected = id(proc) in self._expected_exit_procs
                self._expected_exit_procs.discard(id(proc))
                current = self.proc is proc
                if current:
                    self.proc = None
                    self.initialized = False
                    self.dead = True
                pending = list(self.pending.values()) if current else []
                if current:
                    self.pending.clear()
            for waiter in pending:
                waiter["error"] = "Codex app-server exited"
                waiter["event"].set()
            if not expected:
                for session in list(self.sessions.values()):
                    try:
                        session.on_client_exit()
                    except Exception:
                        pass

    def _read_stderr(self):
        proc = self.proc
        try:
            for line in proc.stderr:
                line = line.rstrip()
                if not line:
                    continue
                self._log_tail(line)
        except Exception:
            pass

    def _log_tail(self, line):
        self.stderr_tail.append(str(line))
        if len(self.stderr_tail) > 40:
            self.stderr_tail = self.stderr_tail[-40:]

    def _dispatch(self, msg):
        if "id" in msg and ("result" in msg or "error" in msg):
            with self.lock:
                waiter = self.pending.pop(str(msg.get("id")), None)
            if waiter:
                waiter["result"] = msg.get("result")
                waiter["error"] = msg.get("error")
                waiter["event"].set()
            return
        if "id" in msg and msg.get("method"):
            threading.Thread(target=self._handle_server_request, args=(msg,), daemon=True).start()
            return
        method = msg.get("method")
        params = msg.get("params") or {}
        if method == "command/exec/outputDelta" and self._handle_command_exec_output(params):
            return
        session = self._session_from_params(params)
        if session:
            self._remember_item_route(params, session)
            session.handle_notification(method, params)
            return
        # Many Codex notifications are scoped only by turnId/itemId. If the
        # turn/item route has not been learned yet, keep a short buffer and
        # replay it once a later notification or response establishes ownership.
        if method and self._has_route_hint(params):
            fallback = self._single_busy_session()
            if fallback:
                self._remember_item_route(params, fallback)
                fallback._remember_route_debug("single-busy fallback", method, params)
                fallback.handle_notification(method, params)
                return
            self._buffer_unrouted(method, params)
            return
        if method and not method.endswith("/updated"):
            fallback = self._single_busy_session()
            if fallback:
                fallback._remember_route_debug("single-busy global fallback", method, params)
                fallback.handle_notification(method, params)
                return
            self._log_tail("unrouted notification: %s %s" % (method, codex_text.compact_json(params)[:500]))

    @staticmethod
    def _thread_id_from_params(params):
        return codex_routing.thread_id_from_params(params)

    @staticmethod
    def _turn_id_from_params(params):
        return codex_routing.turn_id_from_params(params)

    @staticmethod
    def _item_id_from_params(params):
        return codex_routing.item_id_from_params(params)

    def _session_from_params(self, params):
        return codex_routing.session_from_params(
            params, self.sessions, self.turn_sessions, self.item_sessions)

    def _has_route_hint(self, params):
        return codex_routing.has_route_hint(params)

    def _remember_item_route(self, params, session):
        thread_id, turn_id, item_id = codex_routing.remember_item_route(
            params, session, self.sessions, self.turn_sessions, self.item_sessions)
        if thread_id or turn_id or item_id:
            self._flush_unrouted(session, thread_id=thread_id, turn_id=turn_id, item_id=item_id)

    def _single_busy_session(self):
        return codex_routing.single_busy_session(self.sessions)

    def _buffer_unrouted(self, method, params):
        now = time.time()
        entry = codex_routing.unrouted_entry(method, params, now)
        with self.lock:
            self.unrouted_events = codex_routing.buffered_unrouted(
                self.unrouted_events, entry, now, _UNROUTED_TTL, _UNROUTED_MAX)
        if method and not method.endswith("/updated"):
            self._log_tail("buffered unrouted notification: %s %s" % (method, codex_text.compact_json(params)[:500]))

    def _flush_unrouted(self, session, thread_id=None, turn_id=None, item_id=None):
        now = time.time()
        with self.lock:
            if not self.unrouted_events:
                return
            self.unrouted_events, replay = codex_routing.split_unrouted_for_session(
                self.unrouted_events, session, thread_id=thread_id, turn_id=turn_id, item_id=item_id,
                now=now, ttl=_UNROUTED_TTL, max_events=_UNROUTED_MAX)
        for entry in replay:
            params = entry.get("params") or {}
            ethread, eturn, eitem = codex_routing.route_ids(params)
            if ethread:
                self.sessions[ethread] = session
            if eturn:
                self.turn_sessions[eturn] = session
            if eitem:
                self.item_sessions[eitem] = session
            session._remember_route_debug("drained buffered event", entry.get("method"), params)
            session.handle_notification(entry.get("method"), params)

    def add_command_exec_output_handler(self, process_id, handler):
        process_id = str(process_id or "").strip()
        if not process_id or not callable(handler):
            return False
        with self.lock:
            self.command_exec_output_handlers[process_id] = handler
        return True

    def remove_command_exec_output_handler(self, process_id, handler=None):
        process_id = str(process_id or "").strip()
        if not process_id:
            return
        with self.lock:
            if handler is None or self.command_exec_output_handlers.get(process_id) is handler:
                self.command_exec_output_handlers.pop(process_id, None)

    def _handle_command_exec_output(self, params):
        process_id = str((params or {}).get("processId") or "").strip()
        if not process_id:
            return False
        with self.lock:
            handler = self.command_exec_output_handlers.get(process_id)
        if not handler:
            return False
        try:
            handler(params or {})
        except Exception as exc:
            self._log_tail("command/exec output handler failed: %s" % exc)
        return True

    def _handle_server_request(self, msg):
        req_id = msg.get("id")
        method = msg.get("method")
        params = msg.get("params") or {}
        session = self._session_from_params(params)
        if not session and self._has_route_hint(params):
            session = self._single_busy_session()
            if session:
                session._remember_route_debug("single-busy request fallback", method, params)
        try:
            if session:
                self._remember_item_route(params, session)
                result = session.handle_server_request(str(req_id), method, params)
                self.respond(req_id, result)
            elif method == "currentTime/read":
                self.respond(req_id, {"utcTimestampMs": int(time.time() * 1000)})
            else:
                self.respond_error(req_id, -32601, "unsupported app-server request: %s" % method)
        except AppServerRequestError as e:
            self.respond_error(req_id, e.code, e.message)
        except Exception as e:
            self.respond_error(req_id, -32000, str(e))

    def request(self, method, params=None, timeout=60, ensure_started=True):
        if ensure_started:
            self.ensure()
        with self.lock:
            req_id = str(self.next_id)
            self.next_id += 1
            waiter = {"event": threading.Event(), "result": None, "error": None}
            self.pending[req_id] = waiter
            line = json.dumps({"id": req_id, "method": method, "params": params}, ensure_ascii=False)
            try:
                self.proc.stdin.write(line + "\n")
                self.proc.stdin.flush()
            except Exception:
                self.pending.pop(req_id, None)
                raise
        if not waiter["event"].wait(timeout):
            with self.lock:
                self.pending.pop(req_id, None)
            raise RuntimeError("Codex app-server request timed out: %s" % method)
        if waiter["error"]:
            raise RuntimeError(codex_text.json_text(waiter["error"]))
        return waiter["result"]

    def respond(self, req_id, result):
        self._write({"id": req_id, "result": result})

    def respond_error(self, req_id, code, message):
        self._write({"id": req_id, "error": {"code": code, "message": message}})

    def _write(self, obj):
        with self.lock:
            if not self.proc or self.proc.poll() is not None:
                return
            self.proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()

    def register(self, thread_id, session):
        if thread_id:
            self.sessions[thread_id] = session
            self._flush_unrouted(session, thread_id=thread_id)

    def register_turn(self, turn_id, session):
        if turn_id:
            self.turn_sessions[turn_id] = session
            self._flush_unrouted(session, turn_id=turn_id)

    def unregister(self, session):
        for thread_id, existing in list(self.sessions.items()):
            if existing is session:
                self.sessions.pop(thread_id, None)
        for turn_id, existing in list(self.turn_sessions.items()):
            if existing is session:
                self.turn_sessions.pop(turn_id, None)
        for item_id, existing in list(self.item_sessions.items()):
            if existing is session:
                self.item_sessions.pop(item_id, None)

    def shutdown(self):
        with self.lock:
            proc = self.proc
            self.proc = None
            self.initialized = False
            if proc:
                self._expected_exit_procs.add(id(proc))
            pending = list(self.pending.values())
            self.pending.clear()
            self.command_exec_output_handlers.clear()
        for waiter in pending:
            waiter["error"] = "Codex app-server stopped"
            waiter["event"].set()
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass



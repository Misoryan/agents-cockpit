# -*- coding: utf-8 -*-
"""
Agents Cockpit — terminal hub.

One persistent upstream websocket to a per-session ttyd (which owns the
codex/claude PTY), multiplexing many browser clients onto it: broadcasts CLI
output to all clients, forwards any client's input upstream, and replays a
buffered history to clients joining mid-task.

Phase B additions over the original Hub:
  - open_scrollback(sid): persist every output frame to a length-prefixed log
    so a restarted manager can replay scrollback when re-attaching to a
    surviving ttyd.
  - replay_frame(): load historical frames into the buffer WITHOUT broadcasting
    or re-writing to disk (used during re-attach).
  - alive flag: lets manager.prune_dead() detect re-attached sessions whose
    upstream ttyd died (no Popen handle to poll).
"""
import os
import re
import json
import time
import socket
import base64
import threading

from common import ws_send, ws_recv, BUF_CAP, SCROLLBACK_DIR

_CONFIRM_RE = re.compile(rb"(?i)(\bapprove\b|\ballow\b|\bconfirm\b|\[y/?n\]|\(yes/no\)|\(y/n\)|\byes/no\b)")


class Hub:
    def __init__(self, ttyd_port):
        self.ttyd_port = ttyd_port
        self.sid = None
        self.sb_path = None          # per-sid scrollback log (length-prefixed frames)
        self.sb_bytes = 0
        self.clients = set()         # browser raw sockets
        self.frames = []             # buffered output payloads (ttyd "0"+data), for replay
        self.frames_size = 0
        self.upstream = None         # raw socket to ttyd
        self.clock = threading.Lock()
        self.started = time.time()
        self.last_output_ts = time.time()
        self.last_input_ts = time.time()
        self.awaiting_confirm = False
        self.confirm_ts = 0.0
        self.cols = 0
        self.rows = 0
        self.client_sizes = {}       # client_id -> (cols, rows)
        self.alive = True
        self._connect_upstream()

    def open_scrollback(self, sid):
        """Bind this hub to a sid and open (or size) its scrollback log."""
        self.sid = sid
        try:
            os.makedirs(SCROLLBACK_DIR, exist_ok=True)
        except OSError:
            pass
        self.sb_path = os.path.join(SCROLLBACK_DIR, "%s.log" % sid)
        try:
            self.sb_bytes = os.path.getsize(self.sb_path) if os.path.exists(self.sb_path) else 0
        except OSError:
            self.sb_bytes = 0

    def apply_resize(self, client_id, cols, rows):
        # shrink-to-min: codex takes the SMALLEST size among connected clients,
        # so every device's xterm grid is >= codex size -> no garble anywhere
        # (bigger screens just show the smaller terminal with side margins).
        try:
            cols = int(cols); rows = int(rows)
        except (TypeError, ValueError):
            return
        if cols <= 0 or rows <= 0:
            return
        with self.clock:
            self.client_sizes[client_id] = (cols, rows)
            self._recompute_size_locked()

    def drop_client_size(self, client_id):
        with self.clock:
            self.client_sizes.pop(client_id, None)
            self._recompute_size_locked()

    def _recompute_size_locked(self):
        sizes = [s for s in self.client_sizes.values() if s[0] and s[1]]
        if not sizes:
            return
        cols = min(s[0] for s in sizes); rows = min(s[1] for s in sizes)
        if cols and rows and (cols, rows) != (self.cols, self.rows):
            self.cols, self.rows = cols, rows
            self.send_upstream(("1" + json.dumps({"columns": cols, "rows": rows})).encode(), 0x1)

    def state(self, now):
        if self.awaiting_confirm and (now - self.confirm_ts) < 600:
            return "confirm"
        if (now - self.last_output_ts) < 4:
            return "running"
        return "idle"

    def _connect_upstream(self):
        s = socket.create_connection(("127.0.0.1", self.ttyd_port), 10)
        key = base64.b64encode(os.urandom(16)).decode()
        req = ("GET /ws HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nUpgrade: websocket\r\n"
               "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n"
               "Sec-WebSocket-Protocol: tty\r\n\r\n" % (self.ttyd_port, key))
        s.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            c = s.recv(4096)
            if not c:
                raise OSError("ttyd no 101")
            buf += c
        self.upstream = s
        # init frame ttyd expects: {AuthToken, columns, rows}
        init = json.dumps({"AuthToken": "", "columns": 100, "rows": 30}).encode()
        ws_send(s, init, 0x1, mask=True)
        threading.Thread(target=self._reader, daemon=True).start()

    def _store(self, payload):
        self.frames.append(payload)
        self.frames_size += len(payload)
        while self.frames_size > BUF_CAP and len(self.frames) > 1:
            old = self.frames.pop(0)
            self.frames_size -= len(old)
        if self.sb_path:
            try:
                with open(self.sb_path, "ab") as f:       # length-prefixed, append-only
                    f.write(len(payload).to_bytes(4, "big"))
                    f.write(payload)
                self.sb_bytes += 4 + len(payload)
            except OSError:
                pass

    def replay_frame(self, payload):
        """Load a historical frame into the buffer only (no broadcast, no disk write)."""
        self.frames.append(payload)
        self.frames_size += len(payload)
        while self.frames_size > BUF_CAP and len(self.frames) > 1:
            old = self.frames.pop(0)
            self.frames_size -= len(old)

    def _broadcast(self, payload, opcode):
        dead = []
        for c in self.clients:
            try:
                ws_send(c, payload, opcode)
            except OSError:
                dead.append(c)
        for c in dead:
            self.clients.discard(c)

    def _reader(self):
        s = self.upstream
        while True:
            try:
                op, payload = ws_recv(s)
            except OSError:
                break
            if op is None or op == 0x8:
                break
            if op in (0x1, 0x2):
                self.last_output_ts = time.time()
                if _CONFIRM_RE.search(payload):
                    self.awaiting_confirm = True
                    self.confirm_ts = time.time()
                with self.clock:
                    self._store(payload)
                    self._broadcast(payload, op)
        # upstream gone
        self.alive = False
        try:
            for c in list(self.clients):
                c.close()
        except OSError:
            pass
        self.clients.clear()

    def send_upstream(self, payload, opcode):
        if self.upstream:
            try:
                ws_send(self.upstream, payload, opcode, mask=True)
            except OSError:
                pass

    def add_client(self, sock):
        # replay buffered frames so late joiners see history
        with self.clock:
            snapshot = list(self.frames)
        for fr in snapshot:
            try:
                ws_send(sock, fr, 0x2)
            except OSError:
                return
        with self.clock:
            self.clients.add(sock)
        cid = id(sock)
        try:
            first = True
            while True:
                op, payload = ws_recv(sock)
                if op is None or op == 0x8:
                    break
                if op not in (0x1, 0x2):
                    continue
                p0 = payload[:1]
                if first:
                    first = False
                    if p0 == b"{":  # ttyd client init {AuthToken, columns, rows}
                        try:
                            o = json.loads(payload.decode("utf-8", "replace"))
                            self.apply_resize(cid, o.get("columns"), o.get("rows"))
                        except Exception:
                            pass
                        continue
                if p0 == b"1":  # resize -> shrink-to-min
                    try:
                        o = json.loads(payload[1:].decode("utf-8", "replace"))
                        self.apply_resize(cid, o.get("columns"), o.get("rows"))
                    except Exception:
                        pass
                    continue
                # input + others: forward and mark activity
                self.last_input_ts = time.time()
                self.awaiting_confirm = False
                self.send_upstream(payload, op)
        except OSError:
            pass
        finally:
            with self.clock:
                self.clients.discard(sock)
            self.drop_client_size(cid)
            try:
                sock.close()
            except OSError:
                pass

    def close(self):
        self.alive = False
        try:
            if self.upstream:
                self.upstream.close()
        except OSError:
            pass
        for c in list(self.clients):
            try:
                c.close()
            except OSError:
                pass
        self.clients.clear()

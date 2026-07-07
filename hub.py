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
from common import RUN_GRACE_CODEX, RUN_GRACE_CLAUDE, PLAN_THRESHOLD

# ---- terminal output parsing (operate on decoded visible text, not raw bytes) ----
# Strip ANSI CSI/OSC/charset escapes + bare CR/NUL so we see what the user sees.
_ANSI_RE = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]"
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"
    r"|\x1b[NMc=>]"
    r"|\x1b[()*+][A-Za-z0-9]"
    r"|[\r\x00]")
# Normalize one visible line: drop spinner / progress glyphs / percentages / block bars,
# so a TUI redraw that only changes a spinner frame yields an UNCHANGED line-set digest.
_SPINNER_RE = re.compile(
    r"[⠀-⣿]"                         # braille spinner block
    r"|[⏵-⏿⌚-⌛]"            # ⏵⏶⏷⏸⏹⏺… / ⌚⌛
    r"|[✅✔✓✗✖✕❌⚡✶✳✨⚑]"
    r"|[▀-▟]"                         # block elements █ ▓ ▒ ░
    r"|\d{1,3}\s*%")
# Tool / command approval prompts. Constrained (approve must sit next to a [y/n]) so a
# streamed diff that merely mentions "approve" / "yes/no" text does NOT trigger a false hit.
_CONFIRM_RE = re.compile(
    r"(?i)(\[y/?n\]|\(y/?n\)|\(yes/?no\)|\byes\s*/\s*no\b"
    r"|apply\s+patch\b|run\s+command\b"
    r"|do\s+you\s+want\s+to\s+(allow|run|proceed|execute)"
    r"|yes,?\s+and\s+(?:do\s+not|don['’]?t)\s+ask\s+again"
    r"|approve\b.{0,40}\[[yn]|proceed\?\s*\[)")
# Claude plan-mode signals. Scored, never a single literal ("plan" alone is too common).
_PLAN_WEAK = re.compile(r"(?i)\bplan\b|计划")
_PLAN_STRONG = [
    re.compile(r"(?i)plan[ _-]mode|计划模式"),
    re.compile(r"(?i)exit[ _-]plan(?:[ _-]mode)?|退出计划"),
    re.compile(r"(?i)shift\s*\+\s*tab"),
    re.compile(r"(?i)would you like me to (?:proceed|start|continue)|是否(?:开始|继续)"),
    re.compile(r"(?i)ready to (?:proceed|build|implement|start)|准备好(?:实现|开始)"),
    re.compile(r"(?i)adjust (?:this|the) plan|调整(?:这个|此)?计划"),
    re.compile(r"(?i)let(?:'s| us) (?:proceed|start|begin|implement)"),
]


def _plan_score(s):
    sc = 1 if _PLAN_WEAK.search(s) else 0
    for rx in _PLAN_STRONG:
        if rx.search(s):
            sc += 2
    return sc


def _frame_digest(vis):
    """frozenset of normalized non-empty lines in one frame's visible text. Stable across
    TUI repaints whose only change is a spinner frame; changes when real text grows."""
    return frozenset(ln for ln in (_SPINNER_RE.sub("", x).strip() for x in vis.split("\n")) if ln)


class Hub:
    def __init__(self, ttyd_port, backend="codex"):
        self.ttyd_port = ttyd_port
        self.backend = backend       # codex / claude — drives RUN_GRACE & prompt shapes
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
        self.last_content_ts = time.time()   # last frame that carried NEW visible text
        self._last_vis = ""                  # most recent non-empty frame's visible text
        self._frame_digest = None            # normalized line-set of the last frame
        self.ever_input = False              # has the user ever typed into this session?
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

    def _send_pty_resize_locked(self):
        """Push the current PTY size (self.cols/rows) upstream to ttyd/codex."""
        if self.cols and self.rows:
            self.send_upstream(
                ("1" + json.dumps({"columns": self.cols, "rows": self.rows})).encode(), 0x1)

    def apply_resize(self, client_id, cols, rows):
        # A client reports its own viewport size. We NO LONGER shrink-to-min.
        # The PTY size is adopted ONCE (the first client's fit) and after that
        # only changes via adapt() (the per-terminal "适配本屏" button). So a
        # phone joining, leaving, or rotating never resizes the terminal out
        # from under the PC — devices no longer perturb each other. Every device
        # still gets a non-garbled view because the injected terminal page forces
        # its local xterm to the PTY size and CSS-scales it to fit
        # (see common._inject_terminal_controls).
        try:
            cols = int(cols); rows = int(rows)
        except (TypeError, ValueError):
            return
        if cols <= 0 or rows <= 0:
            return
        with self.clock:
            self.client_sizes[client_id] = (cols, rows)
            if not self.cols or not self.rows:          # first fit wins as the initial PTY size
                self.cols, self.rows = cols, rows
                self._send_pty_resize_locked()

    def drop_client_size(self, client_id):
        # PTY size is sticky: a client disconnecting must NOT change it. That was
        # exactly the "phone leaves -> PC snaps back" jump we are removing.
        with self.clock:
            self.client_sizes.pop(client_id, None)

    def adapt(self, cols, rows):
        """Explicit "make THIS screen optimal": set the PTY to the given size.
        Invoked from POST /api/adapt (the "适配本屏" button injected into the
        ttyd page). Last writer wins; any device can reclaim by pressing again."""
        try:
            cols = int(cols); rows = int(rows)
        except (TypeError, ValueError):
            return False
        if cols <= 0 or rows <= 0:
            return False
        with self.clock:
            if (cols, rows) != (self.cols, self.rows):
                self.cols, self.rows = cols, rows
                self._send_pty_resize_locked()
        return True

    def state(self, now):
        # Snapshot under the lock (_reader writes these from another thread), decide outside.
        with self.clock:
            vis = self._last_vis
            last_content = self.last_content_ts
            ever_in = self.ever_input
        grace = RUN_GRACE_CLAUDE if self.backend == "claude" else RUN_GRACE_CODEX
        if (now - last_content) < grace:
            return "running"
        if _CONFIRM_RE.search(vis):
            return "confirm"
        if _plan_score(vis) >= PLAN_THRESHOLD:
            return "plan"
        if not ever_in:
            return "new"
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
                now = time.time()
                # ttyd output frame = leading "0" type byte + raw PTY bytes
                raw = payload[1:] if payload[:1] == b"0" else payload
                vis = _ANSI_RE.sub("", raw.decode("utf-8", "replace"))
                fset = _frame_digest(vis)
                with self.clock:
                    self.last_output_ts = now
                    if vis.strip():
                        self._last_vis = vis
                    # Only NEW visible content (line-set changed) refreshes "running".
                    # Spinner / cursor repaints leave the digest unchanged -> stays idle.
                    if fset and fset != self._frame_digest:
                        self.last_content_ts = now
                        self._frame_digest = fset
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
                self.ever_input = True
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

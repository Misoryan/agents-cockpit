# -*- coding: utf-8 -*-
"""
Agent Cockpit — web process (the "后端接入层" facing the browser).

Serves index.html, enforces basic-auth, and reverse-proxies every /api/* and /t/*
to the manager over plain TCP (HTTP + raw websocket bytes). The web process is
DISPOSABLE: it can be restarted (restart_web) without touching the manager or
any CLI session. It also supervises the manager: a heartbeat thread respawns the
manager if it dies (crash or soft restart), so editing manager logic and applying
it no longer kills the running codex/claude processes.
"""
import sys
import time
import socket
import threading
import http.client
import urllib.parse

import common
from common import BaseHandler, ThreadingServer

_server = [None]


# ---------- restart paths (all os._exit; never os.execv — unreliable on Win) ----------
def restart_web_soon():
    def _restart():
        time.sleep(0.35)
        srv = _server[0]
        if srv:
            try:
                srv.shutdown()
            except Exception:
                pass
            try:
                srv.server_close()
            except Exception:
                pass
        os._exit(0)  # manager + all CLI sessions survive (children of manager, not web)
    threading.Thread(target=_restart, daemon=True).start()


def restart_manager_soon():
    """Soft-restart the manager only: ask it to _soft_exit (children survive),
    then the watchdog respawns it within ~MANAGER_HEARTBEAT_GRACE*INTERVAL seconds."""
    def _go():
        time.sleep(0.4)   # let the HTTP response flush back to the browser
        try:
            c = http.client.HTTPConnection(common.MANAGER_HOST, common.MANAGER_PORT, timeout=2)
            c.request("POST", "/api/_soft_exit", body=b"{}",
                      headers={"Authorization": common.EXPECTED_AUTH, "Content-Type": "application/json"})
            c.getresponse().read(); c.close()
        except Exception:
            pass
        # watchdog will respawn the manager
    threading.Thread(target=_go, daemon=True).start()


def _ask_manager_to_exit():
    """让 manager 杀掉所有会话并退出(最多重试几秒,返回是否已下线)。"""
    for _ in range(8):
        try:
            c = http.client.HTTPConnection(common.MANAGER_HOST, common.MANAGER_PORT, timeout=2)
            c.request("POST", "/api/_exit", body=b"{}",
                      headers={"Authorization": common.EXPECTED_AUTH, "Content-Type": "application/json"})
            c.getresponse().read(); c.close()
        except Exception:
            pass
        time.sleep(0.3)
        if not common.manager_available():
            return True
    return not common.manager_available()


def restart_server_soon():
    """完全重启:先让 manager 杀掉全部会话并退出,再退出本(web)进程(由启动器循环立即重启);
    新 web 启动时 ensure_manager() 会用磁盘上的最新代码拉起全新 manager。"""
    def _restart():
        time.sleep(0.4)             # 让 HTTP 响应先 flush 回浏览器
        _ask_manager_to_exit()
        time.sleep(0.2)
        srv = _server[0]
        if srv:
            try: srv.shutdown()
            except Exception: pass
            try: srv.server_close()
            except Exception: pass
        os._exit(0)  # 退出进程,交由启动器(start.cmd 的循环)立即重启
    threading.Thread(target=_restart, daemon=True).start()


def _manager_watchdog():
    """Respawn the manager if it disappears (crash or intentional soft restart).
    Idempotent: ensure_manager() port-probes before spawning."""
    consec = 0
    while True:
        time.sleep(common.MANAGER_HEARTBEAT_INTERVAL)
        if common.manager_available():
            consec = 0
        else:
            consec += 1
            if consec >= common.MANAGER_HEARTBEAT_GRACE:
                consec = 0
                try:
                    common.ensure_manager()
                except Exception:
                    pass


# ---------- HTTP handler (web mode) ----------
class WebHandler(BaseHandler):
    def _auth(self):
        if self.headers.get("Authorization", "") == common.EXPECTED_AUTH:
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="agent-cockpit"')
        self.send_header("Content-Length", "12"); self.end_headers()
        self.wfile.write(b"auth required")
        return False

    def _proxy_manager_http(self, method, body=None):
        if not common.ensure_manager():
            self._json({"error": "manager not available"}, 503); return
        headers = {}
        ctype = self.headers.get("Content-Type")
        if ctype:
            headers["Content-Type"] = ctype
        conn = None
        try:
            conn = http.client.HTTPConnection(common.MANAGER_HOST, common.MANAGER_PORT, timeout=60)
            conn.request(method, self.path, body=body, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
            self.send_response(resp.status)
            for k, v in resp.getheaders():
                lk = k.lower()
                if lk in ("connection", "transfer-encoding", "keep-alive", "proxy-authenticate",
                          "proxy-authorization", "te", "trailers", "upgrade", "content-length"):
                    continue
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except OSError as e:
            self._json({"error": "manager proxy failed: %s" % e}, 502)
        finally:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass

    def _proxy_manager_ws(self):
        if not common.ensure_manager():
            self.send_response(503); self.send_header("Content-Length", "0"); self.end_headers(); return
        key = self.headers.get("Sec-WebSocket-Key")
        if not key:
            self.send_response(400); self.send_header("Content-Length", "0"); self.end_headers(); return
        try:
            upstream = socket.create_connection((common.MANAGER_HOST, common.MANAGER_PORT), 10)
            req = [
                "GET %s HTTP/1.1" % self.path,
                "Host: %s:%d" % (common.MANAGER_HOST, common.MANAGER_PORT),
                "Upgrade: websocket",
                "Connection: Upgrade",
                "Sec-WebSocket-Key: %s" % key,
                "Sec-WebSocket-Version: %s" % (self.headers.get("Sec-WebSocket-Version") or "13"),
            ]
            proto = self.headers.get("Sec-WebSocket-Protocol")
            if proto:
                req.append("Sec-WebSocket-Protocol: %s" % proto)
            upstream.sendall(("\r\n".join(req) + "\r\n\r\n").encode())
            resp = b""
            while b"\r\n\r\n" not in resp:
                chunk = upstream.recv(4096)
                if not chunk:
                    raise OSError("manager websocket handshake failed")
                resp += chunk
            if b" 101 " not in resp.split(b"\r\n", 1)[0]:
                self.connection.sendall(resp)
                upstream.close()
                return
            self.close_connection = True
            self.connection.sendall(resp)

            def pipe(src, dst):
                try:
                    while True:
                        data = src.recv(65536)
                        if not data:
                            break
                        dst.sendall(data)
                except OSError:
                    pass
                finally:
                    try: dst.shutdown(socket.SHUT_RDWR)
                    except OSError: pass
                    try: dst.close()
                    except OSError: pass

            t = threading.Thread(target=pipe, args=(upstream, self.connection), daemon=True)
            t.start()
            pipe(self.connection, upstream)
        except OSError:
            try:
                self.send_response(502); self.send_header("Content-Length", "0"); self.end_headers()
            except OSError:
                pass

    def _web_get(self, path):
        if path in ("/", "/index.html"):
            self._serve_index(); return
        if path.startswith("/t/") and path.endswith("/ws"):
            self._proxy_manager_ws(); return
        if path.startswith("/t/") or path.startswith("/api/"):
            self._proxy_manager_http("GET"); return
        self._json({"error": "not found"}, 404)

    def _web_post(self, path, raw):
        if path == "/api/restart_web":
            self._json({"ok": True, "message": "web restarting"})
            restart_web_soon()
            return
        if path == "/api/restart_manager":
            self._json({"ok": True, "restarting": True, "soft": True})
            restart_manager_soon()
            return
        if path == "/api/restart":
            self._json({"ok": True, "restarting": True})
            restart_server_soon()
            return
        if path.startswith("/api/"):
            self._proxy_manager_http("POST", raw); return
        self._json({"error": "not found"}, 404)

    def do_GET(self):
        if not self._auth():
            return
        path = urllib.parse.urlparse(self.path).path
        self._web_get(path)

    def do_POST(self):
        if not self._auth():
            return
        pr = urllib.parse.urlparse(self.path)
        n = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(n) if n else b"{}"
        self._web_post(pr.path, raw)


def run():
    common.ensure_manager()
    threading.Thread(target=_manager_watchdog, daemon=True).start()
    ip = common.lan_ip()
    print("=" * 56)
    print(" Agent Cockpit  (三层拆分: 前端 / web / manager 各自可独立重启)")
    print(" 控制台(手机/电脑打开): http://%s:%d" % (ip, common.PICKER_PORT))
    print(" Manager(本机): http://%s:%d" % (common.MANAGER_HOST, common.MANAGER_PORT))
    print(" 账号: %s  密码: ***" % common.CRED.split(":", 1)[0])
    print(" codex : %s" % (common.CODEX_BIN or "(未找到)"))
    print(" claude: %s" % (common.CLAUDE_BIN or "(未找到)"))
    print(" 重启网站/后端层不影响运行中的会话;完全重启才会重载全部代码")
    print("=" * 56)
    try:
        try:
            _server[0] = ThreadingServer((common.HOST, common.PICKER_PORT), WebHandler)
        except OSError as e:
            print("ERROR: 控制台端口 %d 已被旧 Web 占用：%s" % (common.PICKER_PORT, e))
            print("请关闭旧的 start.cmd/Python 窗口后再启动，或结束占用该端口的旧 Web 进程。")
            sys.exit(1)
        _server[0].serve_forever()
    except KeyboardInterrupt:
        print("web bye")

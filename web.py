# -*- coding: utf-8 -*-
"""
Agents Cockpit — web process (the "后端接入层" facing the browser).

Serves index.html, enforces basic-auth, and proxies /api/* plus session paths
to the manager over plain TCP (HTTP + raw websocket bytes). The web process is
DISPOSABLE: it can be restarted (restart_web) without touching the manager or
any CLI session. It also supervises the manager: a heartbeat thread respawns the
manager if it dies (crash or soft restart), so editing manager logic and applying
it no longer kills the running Claude sessions.
"""
import sys
import time
import socket
import threading
import http.client
import urllib.parse
import json
import hmac
import os
import ssl

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


WEB_STOP_EXIT_CODE = 42   # the supervisor treats this as "intentional stop, don't relaunch"


def stop_soon():
    """完全停止(由 POST /api/_stop 触发,`app.py --stop` 调用)。通过 common.STOPPING
    冻结看门狗与 ensure_manager 重生,让 manager 杀掉全部会话并退出,然后本进程以
    退出码 42 退出 —— start.cmd 见 42 即停止重启循环。Win32 Job Object 保证我们
    退出时残留的子进程(若有)一并被内核回收。"""
    def _go():
        time.sleep(0.3)            # 让 HTTP 响应先 flush 回调用方
        try:
            _ask_manager_to_exit()
        except Exception:
            pass
        time.sleep(0.2)
        srv = _server[0]
        if srv:
            try: srv.shutdown()
            except Exception: pass
            try: srv.server_close()
            except Exception: pass
        os._exit(WEB_STOP_EXIT_CODE)
    threading.Thread(target=_go, daemon=True).start()


def _manager_watchdog():
    """Respawn the manager if it disappears (crash or intentional soft restart).
    Stops entirely once common.STOPPING is set (full stop in progress), so it
    never resurrects the manager out from under `app.py --stop`."""
    consec = 0
    while not common.STOPPING:
        time.sleep(common.MANAGER_HEARTBEAT_INTERVAL)
        if common.STOPPING:
            break
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
    def _cookie(self, name):
        h = self.headers.get("Cookie", "")
        if not h:
            return ""
        for part in h.split(";"):
            part = part.strip()
            if "=" in part and part.partition("=")[0] == name:
                return part.partition("=")[2]
        return ""

    def _auth(self):
        # 会话化登录(cookie / Bearer token)。common.py 升级后启用;未升级时回退到
        # Basic auth 并用常量时间比较(顺手堵住时序侧信道),保证过渡期 App 不中断。
        # 内部管理通道:本机进程持内部凭证(`app.py --stop` 等本地工具)直接放行,
        # 与 manager 信任本机的模型一致 —— 这样 stop 命令无需浏览器 cookie 即可调用重启/停止接口。
        if common._is_local_client(self.client_address) and \
           hmac.compare_digest(self.headers.get("Authorization", ""), common.EXPECTED_AUTH):
            self._auth_user = common.request_user(self) or getattr(common, "_legacy_user", "")
            return True
        if hasattr(common, "verify_session_token"):
            tok = self._cookie("ac_session")
            user = common.verify_session_token(tok) if tok else None
            if not user:
                ah = self.headers.get("Authorization", "")
                if ah.startswith("Bearer "):
                    user = common.verify_session_token(ah[7:].strip())
            if user:
                self._auth_user = user
                return True
            self._json({"error": "auth required"}, 401)
            return False
        if hmac.compare_digest(self.headers.get("Authorization", ""), common.EXPECTED_AUTH):
            self._auth_user = getattr(common, "_legacy_user", "")
            return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="agent-cockpit"')
        self.send_header("Content-Length", "12"); self.end_headers()
        self.wfile.write(b"auth required")
        return False

    def _whoami(self):
        tok = self._cookie("ac_session")
        user = common.verify_session_token(tok) if tok else None
        if user:
            self._json({"user": user, "workspaces": common.workspace_overview(user),
                        "uid": common.safe_user_id(user)})
        else:
            self._json({"error": "not authed"}, 401)

    def _login(self, raw):
        if not hasattr(common, "USERS"):
            self._json({"error": "会话登录未启用(common.py 待升级)"}, 503); return
        # 限速按"访客"区分:优先用 ac_visitor cookie(内网穿透后每人唯一),
        # 缺失时回退来源 IP —— 避免一个访问者登录失败连坐锁定所有公网同 IP 访问者。
        ip = (self.client_address or ("",))[0]
        lock_key = self._cookie("ac_visitor") or ("ip:" + ip)
        allowed, wait = common.check_lockout(lock_key)
        if not allowed:
            self._json({"error": "登录失败次数过多,请 %d 秒后再试" % wait}, 429); return
        try:
            data = json.loads((raw or b"{}").decode("utf-8") or "{}")
        except ValueError:
            data = {}
        u = (data.get("user") or "").strip()
        stored = common.USERS.get(u)
        if stored is not None and common.verify_password(data.get("password") or "", stored):
            common.register_login_success(lock_key)
            _secure = common.COOKIE_SECURE and isinstance(self.connection, ssl.SSLSocket)
            tok = common.make_session_token(u)
            body = json.dumps({"ok": True, "user": u}, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Set-Cookie", common.session_cookie_header("ac_session", tok, secure=_secure))
            self.send_header("Content-Length", str(len(body))); self.end_headers()
            self.wfile.write(body)
        else:
            locked = common.register_login_fail(lock_key)
            self._json({"error": "用户名或密码错误" + (";连续失败过多,已临时锁定" if locked else "")}, 401)

    def _logout(self):
        body = json.dumps({"ok": True}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        if hasattr(common, "session_cookie_header"):
            _secure = common.COOKIE_SECURE and isinstance(self.connection, ssl.SSLSocket)
            self.send_header("Set-Cookie", common.session_cookie_header("ac_session", "", max_age=0, secure=_secure))
        self.send_header("Content-Length", str(len(body))); self.end_headers()
        self.wfile.write(body)

    def _proxy_manager_http(self, method, body=None):
        if not common.ensure_manager():
            self._json({"error": "manager not available"}, 503); return
        headers = {}
        ctype = self.headers.get("Content-Type")
        if ctype:
            headers["Content-Type"] = ctype
        headers["Authorization"] = common.EXPECTED_AUTH
        user = getattr(self, "_auth_user", None) or common.request_user(self)
        if user:
            headers["X-Agent-Cockpit-User"] = user
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
            try:
                self._json({"error": "manager proxy failed: %s" % e}, 502)
            except OSError:
                # Browser/frp clients often cancel polling requests; do not turn
                # normal disconnects into noisy traceback storms.
                pass
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
                "Authorization: %s" % common.EXPECTED_AUTH,
            ]
            user = getattr(self, "_auth_user", None) or common.request_user(self)
            if user:
                req.append("X-Agent-Cockpit-User: %s" % user)
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
        if path.startswith(self.static_url_prefix):
            self._serve_static(path); return
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
        if path == "/api/_stop":
            # 完全停止:冻结看门狗 → 让 manager 杀光会话并退出 → 本进程退出码 42,
            # 启动器见 42 即不再重启。Job Object 保证子进程随本进程一起被回收。
            common.STOPPING = True
            self._json({"ok": True, "stopping": True})
            stop_soon()
            return
        if path.startswith("/api/"):
            self._proxy_manager_http("POST", raw); return
        self._json({"error": "not found"}, 404)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        # 会话化登录启用后,/ 与 /api/whoami 公开(登录页内嵌在 index.html);未启用时保持原 Basic 行为
        if hasattr(common, "verify_session_token"):
            if path in ("/", "/index.html"):
                self._serve_index(); return
            if path.startswith(self.static_url_prefix):
                self._serve_static(path); return
            if path == "/api/whoami":
                self._whoami(); return
        if not self._auth():
            return
        self._web_get(path)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        n = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(n) if n else b"{}"
        # 会话化登录启用后,登录/登出公开
        if hasattr(common, "USERS") and path == "/api/login":
            self._login(raw); return
        if hasattr(common, "session_cookie_header") and path == "/api/logout":
            self._logout(); return
        if not self._auth():
            return
        self._web_post(path, raw)


def run():
    # Win32: bind a KILL_ON_JOB_CLOSE job object BEFORE spawning the manager, so
    # the whole tree (web -> manager -> claude) dies with us if we crash
    # or the console window is closed. No-op + fallback on POSIX / old hosts.
    common.bind_to_kill_on_close_job()
    if os.name == "posix":
        # start.sh sends SIGTERM to the process group on shutdown; do a clean stop.
        import signal as _sig
        _sig.signal(_sig.SIGTERM, lambda *_: (setattr(common, "STOPPING", True), stop_soon()))
    common.ensure_manager()
    threading.Thread(target=_manager_watchdog, daemon=True).start()
    ip = common.lan_ip()
    scheme = "https" if common.USE_HTTPS else "http"
    print("=" * 56)
    print(" Agents Cockpit  (三层拆分: 前端 / web / manager 各自可独立重启)")
    print(" 控制台(手机/电脑打开): %s://%s:%d" % (scheme, ip, common.PICKER_PORT))
    if common.USE_HTTPS:
        print(" HTTPS 已启用(自签证书)。浏览器首次访问会提示不安全 → 高级/继续。")
        print(" 经 tcp 隧道(openfrp 等)暴露时,穿透商看不到明文,口令/Cookie 端到端加密。")
    print(" Manager(本机): http://%s:%d" % (common.MANAGER_HOST, common.MANAGER_PORT))
    print(" 账号: %s  密码: ***" % common.CRED.split(":", 1)[0])
    print(" claude: %s" % (common.CLAUDE_BIN or "(not found)"))
    print(" 重启网站/后端层不影响运行中的会话;完全重启才会重载全部代码")
    print("=" * 56)
    try:
        try:
            _server[0] = ThreadingServer((common.HOST, common.PICKER_PORT), WebHandler)
        except OSError as e:
            print("ERROR: 控制台端口 %d 已被旧 Web 占用：%s" % (common.PICKER_PORT, e))
            print("请关闭旧的 start.cmd/Python 窗口后再启动，或结束占用该端口的旧 Web 进程。")
            sys.exit(1)
        if common.USE_HTTPS:
            try:
                common.ensure_self_signed_cert(common.CERT_FILE, common.KEY_FILE)
                _ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                _ctx.load_cert_chain(common.CERT_FILE, common.KEY_FILE)
                _server[0].socket = _ctx.wrap_socket(_server[0].socket, server_side=True)
            except Exception as e:
                print("ERROR: 启用 HTTPS 失败(%s)。" % e)
                print("请在 config.ini 设 [server] use_https = 0,或 pip install cryptography,或提供 cert_file/key_file。")
                sys.exit(1)
            if common.LAN_HTTP_PORT > 0:
                try:
                    _http_srv = ThreadingServer((common.HOST, common.LAN_HTTP_PORT), WebHandler)
                    threading.Thread(target=_http_srv.serve_forever, daemon=True).start()
                    print(" 局域网明文入口(本机/局域网方便访问,无证书警告): http://%s:%d" % (ip, common.LAN_HTTP_PORT))
                except OSError as e:
                    print("WARNING: 局域网 HTTP 端口 %d 启动失败:%s(忽略,继续只用 HTTPS 端口)" % (common.LAN_HTTP_PORT, e))
        _server[0].serve_forever()
    except KeyboardInterrupt:
        print("web bye")

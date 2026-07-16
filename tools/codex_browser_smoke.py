#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Headless browser smoke for Codex multi-client replay/reconnect behavior.

This complements the socket-level smoke by rendering the real web UI in two
headless Chromium/Edge tabs. It verifies that two browser clients can attach to
the same Codex session, receive the same backend-confirmed notice, and keep
existing DOM content while one WebSocket is deliberately closed and recovered
through the replay/catch-up path.
"""
import argparse
import base64
import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import common  # noqa: E402


DEFAULT_BROWSER_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def _free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _headers(user):
    headers = {"Authorization": common.EXPECTED_AUTH}
    if user:
        headers["X-Agent-Cockpit-User"] = user
    return headers


def _user_from_config(explicit=""):
    if explicit:
        return explicit
    return getattr(common, "_legacy_user", "") or next(iter(getattr(common, "USERS", {}) or {}), "")


def _api_post_json(path, user, payload):
    body = json.dumps(payload or {}).encode("utf-8")
    headers = _headers(user)
    headers["Content-Type"] = "application/json"
    headers["Content-Length"] = str(len(body))
    conn = http.client.HTTPConnection(common.MANAGER_HOST, common.MANAGER_PORT, timeout=20)
    try:
        conn.request("POST", path, body=body, headers=headers)
        res = conn.getresponse()
        data = res.read()
    finally:
        conn.close()
    text = data.decode("utf-8", "replace")
    if res.status >= 400:
        raise RuntimeError("POST %s -> %s %s" % (path, res.status, text[:400]))
    return json.loads(text or "{}")


def _launch_temp_session(user, cwd):
    result = _api_post_json("/api/launch", user, {
        "dir": os.path.abspath(cwd or os.getcwd()),
        "title": "Codex browser smoke",
        "backend": "codex_native",
        "yolo": False,
    })
    sid = result.get("sid")
    if not sid:
        raise RuntimeError("temporary Codex launch did not return sid: %s" % result)
    return sid


def _stop_session(user, sid):
    if not sid:
        return
    try:
        _api_post_json("/api/stop", user, {"sid": sid})
    except Exception as exc:
        print("WARN: failed to stop temporary session %s: %s" % (sid, exc), file=sys.stderr)


def _http_json(host, port, method, path, body=None, timeout=5):
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        payload = None if body is None else json.dumps(body).encode("utf-8")
        headers = {}
        if payload is not None:
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = str(len(payload))
        conn.request(method, path, body=payload, headers=headers)
        res = conn.getresponse()
        data = res.read()
    finally:
        conn.close()
    text = data.decode("utf-8", "replace")
    if res.status >= 400:
        raise RuntimeError("%s %s -> %s %s" % (method, path, res.status, text[:400]))
    return json.loads(text or "{}")


def _find_browser(explicit=""):
    if explicit:
        path = Path(explicit)
        if path.is_file():
            return str(path)
        raise RuntimeError("browser path does not exist: %s" % explicit)
    for candidate in DEFAULT_BROWSER_PATHS:
        if Path(candidate).is_file():
            return candidate
    found = shutil.which("chrome") or shutil.which("msedge")
    if found:
        return found
    raise RuntimeError("Chrome/Edge executable not found; pass --browser")


def _password_from_auth_file(user):
    path = Path("auth.txt")
    if not path.is_file():
        return ""
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw or raw.lstrip().startswith("#") or ":" not in raw:
            continue
        name, _, password = raw.partition(":")
        if name.strip() == user:
            return password.strip()
    return ""


class CdpPage:
    def __init__(self, ws_url, label):
        self.ws_url = ws_url
        self.label = label
        self.sock = None
        self.next_id = 1

    def connect(self):
        parsed = urllib.parse.urlparse(self.ws_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 80
        path = parsed.path + (("?" + parsed.query) if parsed.query else "")
        sock = socket.create_connection((host, port), 8)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        req = [
            "GET %s HTTP/1.1" % path,
            "Host: %s:%d" % (host, port),
            "Upgrade: websocket",
            "Connection: Upgrade",
            "Sec-WebSocket-Key: %s" % key,
            "Sec-WebSocket-Version: 13",
            "",
            "",
        ]
        sock.sendall("\r\n".join(req).encode("ascii"))
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = sock.recv(4096)
            if not chunk:
                break
            resp += chunk
        first = resp.split(b"\r\n", 1)[0].decode("latin1", "replace")
        if " 101 " not in first:
            sock.close()
            raise RuntimeError("CDP websocket handshake failed for %s: %s" % (self.label, first))
        self.sock = sock
        self.call("Runtime.enable")
        self.call("Page.enable")

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None

    def call(self, method, params=None, timeout=10):
        msg_id = self.next_id
        self.next_id += 1
        common.ws_send(self.sock, json.dumps({
            "id": msg_id,
            "method": method,
            "params": params or {},
        }).encode("utf-8"), opcode=0x1, mask=True)
        deadline = time.time() + timeout
        while time.time() < deadline:
            op, payload = common.ws_recv(self.sock)
            if op is None:
                break
            if op in (0x9, 0xA):
                continue
            data = json.loads(payload.decode("utf-8", "replace"))
            if data.get("id") == msg_id:
                if data.get("error"):
                    raise RuntimeError("CDP %s failed on %s: %s" % (method, self.label, data["error"]))
                return data.get("result") or {}
        raise TimeoutError("CDP %s timed out on %s" % (method, self.label))

    def eval(self, expression, timeout=10):
        result = self.call("Runtime.evaluate", {
            "expression": expression,
            "awaitPromise": True,
            "returnByValue": True,
        }, timeout=timeout)
        obj = result.get("result") or {}
        if obj.get("subtype") == "error":
            raise RuntimeError("browser eval failed on %s: %s" % (self.label, obj))
        return obj.get("value")


class Browser:
    def __init__(self, exe, url):
        self.exe = exe
        self.url = url
        self.port = _free_port()
        self.user_data = tempfile.mkdtemp(prefix="codex-browser-smoke-")
        self.proc = None
        self.pages = []

    def start(self):
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.proc = subprocess.Popen([
            self.exe,
            "--headless=new",
            "--disable-gpu",
            "--disable-background-networking",
            "--no-first-run",
            "--no-default-browser-check",
            "--remote-debugging-port=%d" % self.port,
            "--user-data-dir=%s" % self.user_data,
            "about:blank",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                _http_json("127.0.0.1", self.port, "GET", "/json/version")
                return
            except Exception:
                if self.proc.poll() is not None:
                    raise RuntimeError("browser exited early with code %s" % self.proc.returncode)
                time.sleep(0.2)
        raise TimeoutError("browser remote debugging port did not become ready")

    def new_page(self, label):
        target = _http_json(
            "127.0.0.1",
            self.port,
            "PUT",
            "/json/new?%s" % urllib.parse.quote(self.url, safe=":/?&=%"),
        )
        page = CdpPage(target["webSocketDebuggerUrl"], label)
        page.connect()
        self.pages.append(page)
        return page

    def close(self):
        for page in self.pages:
            page.close()
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        shutil.rmtree(self.user_data, ignore_errors=True)


def _wait_eval(page, expression, expected=True, timeout=10, interval=0.2):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = page.eval(expression, timeout=timeout)
        if expected is None:
            if last:
                return last
        elif last == expected:
            return last
        time.sleep(interval)
    raise TimeoutError("wait failed on %s for %s; last=%r" % (page.label, expression, last))


def _login_page(page, user, password):
    if not user or not password:
        raise RuntimeError("browser smoke needs a web login password; pass --password or add auth.txt")
    result = page.eval("""(async function(){
      var r = await fetch('/api/login', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({user: %s, password: %s})
      });
      var j = await r.json().catch(function(){ return {}; });
      return {status:r.status, ok:!!j.ok, error:j.error||''};
    })()""" % (json.dumps(user), json.dumps(password)), timeout=10)
    if not result or not result.get("ok"):
        raise RuntimeError("web login failed for %s: %s" % (user, result))


def _attach_page(page, sid, title):
    escaped_sid = json.dumps(sid)
    escaped_title = json.dumps(title)
    _wait_eval(page, "document.readyState === 'complete'", True, timeout=12)
    _wait_eval(page, "typeof showNativeSession === 'function' && typeof nativeConnect === 'function'", True, timeout=12)
    page.eval("window.NATIVE_DEBUG = true; showNativeSession(%s, %s); true" % (escaped_sid, escaped_title))
    _wait_eval(page, "!!(window.nativeStages && nativeStages[%s] && nativeStages[%s].root)" % (escaped_sid, escaped_sid), True)
    _wait_eval(page, "!!(window.nativeWs && nativeWs[%s] && nativeWs[%s].readyState === 1)" % (escaped_sid, escaped_sid), True, timeout=12)


def _page_summary(page, sid):
    escaped_sid = json.dumps(sid)
    return page.eval("""(function(){
      var st=(window.nativeStages||{})[%s];
      if(!st || !st.root) return null;
      return {
        sid: %s,
        lastSeq: st.lastSeq || 0,
        childCount: st.root.children.length,
        hasContent: !!(window.nStageHasReplayContent && nStageHasReplayContent(st)),
        text: st.root.innerText || "",
        planMode: !!st.planMode,
        wsState: (window.nativeWs && nativeWs[%s]) ? nativeWs[%s].readyState : -1
      };
    })()""" % (escaped_sid, escaped_sid, escaped_sid, escaped_sid))


def _wait_text(page, sid, text, timeout=10):
    escaped_sid = json.dumps(sid)
    escaped_text = json.dumps(text)
    return _wait_eval(
        page,
        """(function(){
          var st=(window.nativeStages||{})[%s];
          return !!(st && st.root && (st.root.innerText||"").indexOf(%s) >= 0);
        })()""" % (escaped_sid, escaped_text),
        True,
        timeout=timeout,
    )


def run_smoke(args):
    user = _user_from_config(args.user)
    password = args.password or _password_from_auth_file(user)
    sid = args.sid or _launch_temp_session(user, args.cwd)
    temp_sid = "" if args.sid else sid
    browser = Browser(_find_browser(args.browser), args.url or "http://127.0.0.1:%d/" % common.PICKER_PORT)
    try:
        browser.start()
        page_a = browser.new_page("primary")
        page_b = browser.new_page("mirror")
        _login_page(page_a, user, password)
        _login_page(page_b, user, password)
        _attach_page(page_a, sid, "Codex browser smoke")
        _attach_page(page_b, sid, "Codex browser smoke")

        first_name = "Browser smoke %d" % int(time.time())
        _api_post_json("/api/nslash", user, {"sid": sid, "command": "/rename " + first_name})
        _wait_text(page_a, sid, first_name)
        _wait_text(page_b, sid, first_name)
        before = _page_summary(page_b, sid)

        page_b.eval("""(function(){
          var sid=%s, ws=(window.nativeWs||{})[sid];
          if(ws) ws.close();
          return true;
        })()""" % json.dumps(sid))
        time.sleep(0.4)
        second_name = first_name + " recovered"
        _api_post_json("/api/nslash", user, {"sid": sid, "command": "/rename " + second_name})
        _wait_text(page_b, sid, second_name, timeout=15)
        after = _page_summary(page_b, sid)
        primary = _page_summary(page_a, sid)

        ok = bool(
            before
            and after
            and primary
            and after["childCount"] >= before["childCount"]
            and second_name in after["text"]
            and second_name in primary["text"]
            and after["lastSeq"] >= before["lastSeq"]
        )
        return {
            "ok": ok,
            "sid": sid,
            "user": user,
            "url": browser.url,
            "browser": browser.exe,
            "temporary_session": temp_sid or None,
            "before_reconnect": before,
            "after_reconnect": after,
            "primary": primary,
        }
    finally:
        browser.close()
        if temp_sid:
            _stop_session(user, temp_sid)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--sid", default="", help="Existing Codex session id. Defaults to a temporary session.")
    parser.add_argument("--user", default="", help="Auth user context. Defaults to first configured user.")
    parser.add_argument("--cwd", default=os.getcwd(), help="Working directory for temporary Codex sessions.")
    parser.add_argument("--url", default="", help="Browser-facing web URL. Defaults to local picker port.")
    parser.add_argument("--browser", default="", help="Chrome/Edge executable path.")
    parser.add_argument("--password", default="", help="Web login password. Defaults to auth.txt for the selected user.")
    args = parser.parse_args(argv)
    result = run_smoke(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

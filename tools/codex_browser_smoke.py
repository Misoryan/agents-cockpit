#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Headless browser smoke for Codex multi-client replay/reconnect behavior.

This complements the socket-level smoke by rendering the real web UI in two
headless Chromium/Edge tabs. It verifies that two browser clients can attach to
the same Codex session, receive the same backend-confirmed notice, share a
streamed /exec command with stdin, render a replayable MCP status card, keep the
mirror tab usable in a narrow/mobile viewport, and preserve existing DOM content
while one WebSocket is deliberately closed and recovered through the
replay/catch-up path.
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
        "codex": {"sandbox": "danger-full-access", "approvalPolicy": "never"},
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


def _set_viewport(page, width, height, mobile=False, device_scale_factor=1):
    width = int(width or 0)
    height = int(height or 0)
    if width <= 0 or height <= 0:
        return None
    params = {
        "width": width,
        "height": height,
        "deviceScaleFactor": float(device_scale_factor or 1),
        "mobile": bool(mobile),
    }
    page.call("Emulation.setDeviceMetricsOverride", params)
    return params


def _page_summary(page, sid):
    escaped_sid = json.dumps(sid)
    return page.eval("""(function(){
      var st=(window.nativeStages||{})[%s];
      if(!st || !st.root) return null;
      function visible(sel){
        var el=document.querySelector(sel);
        if(!el) return false;
        var r=el.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < window.innerHeight;
      }
      var stage=document.getElementById('nativemsgs');
      var send=document.getElementById('nativesend');
      var input=document.getElementById('nativeinput');
      var sidebar=document.getElementById('sidebar');
      var stageRect=stage ? stage.getBoundingClientRect() : null;
      return {
        sid: %s,
        lastSeq: st.lastSeq || 0,
        childCount: st.root.children.length,
        hasContent: !!(window.nStageHasReplayContent && nStageHasReplayContent(st)),
        text: st.root.innerText || "",
        domText: st.root.textContent || "",
        firstNodeMarker: st.root.children[0] && st.root.children[0].dataset ? (st.root.children[0].dataset.smokeMarker || "") : "",
        planMode: !!st.planMode,
        wsState: (window.nativeWs && nativeWs[%s]) ? nativeWs[%s].readyState : -1,
        viewport: {
          width: window.innerWidth || 0,
          height: window.innerHeight || 0,
          dpr: window.devicePixelRatio || 1,
          visualWidth: window.visualViewport ? window.visualViewport.width : 0,
          visualHeight: window.visualViewport ? window.visualViewport.height : 0
        },
        mobileLayout: {
          composerVisible: visible('#nativesend'),
          inputVisible: visible('#nativeinput'),
          submitVisible: visible('#nativesubmit'),
          stageWidth: stageRect ? Math.round(stageRect.width) : 0,
          stageHeight: stageRect ? Math.round(stageRect.height) : 0,
          sidebarPosition: sidebar ? getComputedStyle(sidebar).position : '',
          sendBottom: send ? Math.round(send.getBoundingClientRect().bottom) : 0,
          inputTop: input ? Math.round(input.getBoundingClientRect().top) : 0
        }
      };
    })()""" % (escaped_sid, escaped_sid, escaped_sid, escaped_sid))


def _layout_ok(summary, expected_mobile=False, expected_desktop=False):
    if not summary:
        return False
    layout = summary.get("mobileLayout") or {}
    if not (layout.get("composerVisible") and layout.get("inputVisible") and layout.get("submitVisible")):
        return False
    if int(layout.get("stageWidth") or 0) <= 0 or int(layout.get("stageHeight") or 0) <= 0:
        return False
    if expected_mobile and layout.get("sidebarPosition") != "fixed":
        return False
    if expected_desktop and layout.get("sidebarPosition") == "fixed":
        return False
    return True


def _mark_first_message_node(page, sid, marker):
    escaped_sid = json.dumps(sid)
    escaped_marker = json.dumps(marker)
    result = page.eval("""(function(){
      var st=(window.nativeStages||{})[%s];
      if(!st || !st.root || !st.root.children.length) return {ok:false, childCount:0};
      st.root.children[0].dataset.smokeMarker=%s;
      return {ok:true, childCount:st.root.children.length, marker:st.root.children[0].dataset.smokeMarker};
    })()""" % (escaped_sid, escaped_marker))
    if not result or not result.get("ok"):
        raise RuntimeError("failed to mark existing message node for %s: %s" % (sid, result))
    return result


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


def _wait_dom_text(page, sid, text, timeout=10):
    escaped_sid = json.dumps(sid)
    escaped_text = json.dumps(text)
    return _wait_eval(
        page,
        """(function(){
          var st=(window.nativeStages||{})[%s];
          return !!(st && st.root && (st.root.textContent||"").indexOf(%s) >= 0);
        })()""" % (escaped_sid, escaped_text),
        True,
        timeout=timeout,
    )


def _wait_dom_selector_count(page, sid, selector, minimum=1, timeout=10):
    escaped_sid = json.dumps(sid)
    escaped_selector = json.dumps(selector)
    expression = """(function(){
      var st=(window.nativeStages||{})[%s];
      if(!st || !st.root) return 0;
      return st.root.querySelectorAll(%s).length;
    })()""" % (escaped_sid, escaped_selector)
    _wait_eval(
        page,
        """(function(){
          var st=(window.nativeStages||{})[%s];
          if(!st || !st.root) return 0;
          return st.root.querySelectorAll(%s).length >= %d;
        })()""" % (escaped_sid, escaped_selector, minimum),
        True,
        timeout=timeout,
    )
    return int(page.eval(expression, timeout=5) or 0)


def _first_mcp_browse_command(page, sid):
    escaped_sid = json.dumps(sid)
    return page.eval(
        """(function(){
          var st=(window.nativeStages||{})[%s];
          if(!st || !st.root) return "";
          var btn=st.root.querySelector(".mcp-status-card .mcp-action");
          if(!btn) return "";
          return (btn.dataset && btn.dataset.mcpCommand) || "";
        })()""" % escaped_sid,
        timeout=5,
    ) or ""


def _silence_open_ws(page, sid):
    escaped_sid = json.dumps(sid)
    return page.eval(
        """(function(){
          var ws=(window.nativeWs||{})[%s];
          if(!ws || ws.readyState !== 1) return false;
          ws.onmessage=function(){};
          return true;
        })()""" % escaped_sid,
        timeout=5,
    )


def _trigger_session_signal_poll(page):
    return page.eval(
        """(function(){
          if(typeof api !== 'function' || typeof rememberSessions !== 'function') return Promise.resolve(false);
          return api('/api/sessions').then(function(r){
            rememberSessions((r&&r.sessions)||[]);
            return true;
          });
        })()""",
        timeout=5,
    )


def _shell_exec_stdin_command(token):
    py = sys.executable
    code = (
        "import sys; "
        "print(%r, flush=True); "
        "data=sys.stdin.read(); "
        "print(%r + data.strip(), flush=True)"
    ) % ("%s ready" % token, "%s stdin:" % token)
    if os.name == "nt":
        return '& "%s" -u -c "%s"' % (py, code)
    return "'%s' -u -c \"%s\"" % (py.replace("'", "'\\''"), code)


def _force_reconnect(page, sid, timeout=15):
    escaped_sid = json.dumps(sid)
    page.eval("""(function(){
      var sid=%s;
      if(typeof nativeConnect !== 'function') return false;
      nativeConnect(sid, {force:true});
      return true;
    })()""" % escaped_sid)
    _wait_eval(
        page,
        "!!(window.nativeWs && nativeWs[%s] && nativeWs[%s].readyState === 1)" % (escaped_sid, escaped_sid),
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
        primary_viewport = _set_viewport(
            page_a,
            args.primary_width,
            args.primary_height,
            mobile=False,
            device_scale_factor=args.primary_dpr,
        )
        mirror_viewport = None
        if not args.mirror_desktop:
            mirror_viewport = _set_viewport(
                page_b,
                args.mirror_width,
                args.mirror_height,
                mobile=True,
                device_scale_factor=args.mirror_dpr,
            )
        _login_page(page_a, user, password)
        _login_page(page_b, user, password)
        _attach_page(page_a, sid, "Codex browser smoke")
        _attach_page(page_b, sid, "Codex browser smoke")

        first_name = "Browser smoke %d" % int(time.time())
        _api_post_json("/api/nslash", user, {"sid": sid, "command": "/rename " + first_name})
        _wait_text(page_a, sid, first_name)
        _wait_text(page_b, sid, first_name)

        exec_token = "exec-stream-smoke-%d" % int(time.time() * 1000)
        exec_started = _api_post_json("/api/nslash", user, {
            "sid": sid,
            "command": "/exec-stream " + _shell_exec_stdin_command(exec_token),
        })
        exec_process_id = exec_started.get("process_id") or ""
        if not exec_process_id:
            raise RuntimeError("/exec-stream did not return process_id: %s" % exec_started)
        _wait_dom_text(page_a, sid, exec_token + " ready", timeout=20)
        _wait_dom_text(page_b, sid, exec_token + " ready", timeout=20)
        _api_post_json("/api/nterminal", user, {
            "sid": sid,
            "process_id": exec_process_id,
            "action": "write",
            "input": "from-browser-smoke\n",
            "close": True,
        })
        exec_final = exec_token + " stdin:from-browser-smoke"
        _wait_dom_text(page_a, sid, exec_final, timeout=20)
        _wait_dom_text(page_b, sid, exec_final, timeout=20)

        _api_post_json("/api/nslash", user, {"sid": sid, "command": "/mcp-status tools"})
        mcp_marker = "MCP Status |"
        _wait_dom_text(page_a, sid, mcp_marker, timeout=20)
        _wait_dom_text(page_b, sid, mcp_marker, timeout=20)
        mcp_cards_primary = _wait_dom_selector_count(page_a, sid, ".mcp-status-card", timeout=20)
        mcp_cards_mirror = _wait_dom_selector_count(page_b, sid, ".mcp-status-card", timeout=20)
        mcp_resource_command = _first_mcp_browse_command(page_a, sid)
        mcp_resource_marker = "MCP Resources |"
        mcp_resource_cards_primary = 0
        mcp_resource_cards_mirror = 0
        if mcp_resource_command:
            _api_post_json("/api/nslash", user, {"sid": sid, "command": mcp_resource_command})
            _wait_dom_text(page_a, sid, mcp_resource_marker, timeout=20)
            _wait_dom_text(page_b, sid, mcp_resource_marker, timeout=20)
            mcp_resource_cards_primary = _wait_dom_selector_count(
                page_a, sid, ".mcp-resource-card", timeout=20
            )
            mcp_resource_cards_mirror = _wait_dom_selector_count(
                page_b, sid, ".mcp-resource-card", timeout=20
            )

        marker = "keep-dom-%d" % int(time.time() * 1000)
        marked = _mark_first_message_node(page_b, sid, marker)
        before_open_catchup = _page_summary(page_b, sid)
        before_open_text = before_open_catchup.get("text") if before_open_catchup else ""

        stale_name = first_name + " stale-open"
        signal_poll_before = bool(_trigger_session_signal_poll(page_b))
        stale_ws_silenced = bool(_silence_open_ws(page_b, sid))
        _api_post_json("/api/nslash", user, {"sid": sid, "command": "/rename " + stale_name})
        _wait_text(page_a, sid, stale_name, timeout=15)
        signal_poll_after = bool(_trigger_session_signal_poll(page_b))
        _wait_text(page_b, sid, stale_name, timeout=20)
        after_open_catchup = _page_summary(page_b, sid)
        open_catchup_dom_preserved = bool(
            after_open_catchup and after_open_catchup.get("firstNodeMarker") == marker
        )
        open_catchup_text_preserved = bool(
            before_open_text and after_open_catchup and before_open_text in (after_open_catchup.get("text") or "")
        )
        before = after_open_catchup
        before_text = before.get("text") if before else ""

        page_b.eval("""(function(){
          var sid=%s, ws=(window.nativeWs||{})[sid];
          if(ws) ws.close();
          return true;
        })()""" % json.dumps(sid))
        time.sleep(0.4)
        second_name = first_name + " recovered"
        _api_post_json("/api/nslash", user, {"sid": sid, "command": "/rename " + second_name})
        _wait_text(page_b, sid, second_name, timeout=15)
        after_catchup = _page_summary(page_b, sid)

        _force_reconnect(page_b, sid)
        third_name = second_name + " reconnected"
        _api_post_json("/api/nslash", user, {"sid": sid, "command": "/rename " + third_name})
        _wait_text(page_b, sid, third_name, timeout=15)
        _wait_text(page_a, sid, third_name, timeout=15)
        after = _page_summary(page_b, sid)
        primary = _page_summary(page_a, sid)
        catchup_dom_preserved = bool(after_catchup and after_catchup.get("firstNodeMarker") == marker)
        catchup_text_preserved = bool(before_text and after_catchup and before_text in (after_catchup.get("text") or ""))
        dom_preserved = bool(after and after.get("firstNodeMarker") == marker)
        text_preserved = bool(before_text and after and before_text in (after.get("text") or ""))
        narrow_layout_ok = _layout_ok(after, expected_mobile=not args.mirror_desktop)
        primary_layout_ok = _layout_ok(primary, expected_desktop=bool(primary_viewport))

        ok = bool(
            before
            and before_open_catchup
            and after_catchup
            and after
            and primary
            and signal_poll_before
            and signal_poll_after
            and stale_ws_silenced
            and before["childCount"] >= before_open_catchup["childCount"]
            and after_catchup["childCount"] >= before["childCount"]
            and after["childCount"] >= after_catchup["childCount"]
            and stale_name in before["text"]
            and second_name in after_catchup["text"]
            and third_name in after["text"]
            and third_name in primary["text"]
            and exec_final in (after.get("domText") or "")
            and exec_final in (primary.get("domText") or "")
            and mcp_marker in (after.get("domText") or "")
            and mcp_marker in (primary.get("domText") or "")
            and mcp_cards_mirror >= 1
            and mcp_cards_primary >= 1
            and (
                not mcp_resource_command
                or (
                    mcp_resource_marker in (after.get("domText") or "")
                    and mcp_resource_marker in (primary.get("domText") or "")
                    and mcp_resource_cards_mirror >= 1
                    and mcp_resource_cards_primary >= 1
                )
            )
            and after_catchup["lastSeq"] >= before["lastSeq"]
            and before["lastSeq"] >= before_open_catchup["lastSeq"]
            and after["lastSeq"] >= after_catchup["lastSeq"]
            and open_catchup_dom_preserved
            and open_catchup_text_preserved
            and catchup_dom_preserved
            and catchup_text_preserved
            and dom_preserved
            and text_preserved
            and narrow_layout_ok
            and primary_layout_ok
        )
        return {
            "ok": ok,
            "sid": sid,
            "user": user,
            "url": browser.url,
            "browser": browser.exe,
            "primary_viewport": primary_viewport,
            "primary_layout_ok": primary_layout_ok,
            "mirror_viewport": mirror_viewport,
            "narrow_layout_ok": narrow_layout_ok,
            "temporary_session": temp_sid or None,
            "exec_stream": {
                "process_id": exec_process_id,
                "ready_text": exec_token + " ready",
                "final_text": exec_final,
                "seen_primary": exec_final in (primary.get("domText") or "") if primary else False,
                "seen_mirror": exec_final in (after.get("domText") or "") if after else False,
            },
            "mcp_status": {
                "marker": mcp_marker,
                "seen_primary": mcp_marker in (primary.get("domText") or "") if primary else False,
                "seen_mirror": mcp_marker in (after.get("domText") or "") if after else False,
                "cards_primary": mcp_cards_primary,
                "cards_mirror": mcp_cards_mirror,
                "resource_command": mcp_resource_command,
                "resource_cards_primary": mcp_resource_cards_primary,
                "resource_cards_mirror": mcp_resource_cards_mirror,
            },
            "dom_marker": marked,
            "stale_open_catchup": {
                "ws_silenced": stale_ws_silenced,
                "session_poll_before": signal_poll_before,
                "session_poll_after": signal_poll_after,
                "rename": stale_name,
                "dom_preserved": open_catchup_dom_preserved,
                "text_preserved": open_catchup_text_preserved,
                "before": before_open_catchup,
                "after": after_open_catchup,
            },
            "dom_preserved_after_catchup": catchup_dom_preserved,
            "text_preserved_after_catchup": catchup_text_preserved,
            "dom_preserved_after_reconnect": dom_preserved,
            "text_preserved_after_reconnect": text_preserved,
            "before_reconnect": before,
            "after_catchup": after_catchup,
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
    parser.add_argument("--primary-width", type=int, default=1280, help="Primary tab desktop viewport width.")
    parser.add_argument("--primary-height", type=int, default=900, help="Primary tab desktop viewport height.")
    parser.add_argument("--primary-dpr", type=float, default=1.0, help="Primary tab device pixel ratio.")
    parser.add_argument("--mirror-width", type=int, default=390, help="Mirror tab viewport width; defaults to a phone-like narrow viewport.")
    parser.add_argument("--mirror-height", type=int, default=844, help="Mirror tab viewport height.")
    parser.add_argument("--mirror-dpr", type=float, default=2.0, help="Mirror tab device pixel ratio.")
    parser.add_argument("--mirror-desktop", action="store_true", help="Keep the mirror tab at the browser default desktop viewport.")
    args = parser.parse_args(argv)
    result = run_smoke(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

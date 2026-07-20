# -*- coding: utf-8 -*-
"""External notification helpers for desktop, Telegram, Bark, and webhooks."""
import base64
import hashlib
import hmac
import http.client
import json
import os
import subprocess
import time
import urllib.parse
from dataclasses import dataclass


@dataclass(frozen=True)
class NotifySettings:
    enabled: bool
    events: set
    telegram_token: str = ""
    telegram_chat: str = ""
    bark_key: str = ""
    webhook_url: str = ""
    webhook_secret: str = ""
    timeout: float = 6.0
    desktop_toast: bool = False
    create_no_window: int = 0


def notify_enabled_for(event, settings):
    return bool(settings.enabled and event in settings.events)


def notify_result_text(events, limit=3500):
    """Return the latest assistant text message, excluding thinking/tool process."""
    for ev in reversed(events or []):
        if not isinstance(ev, dict) or ev.get("type") != "assistant":
            continue
        msg = ev.get("message") or {}
        content = msg.get("content")
        parts = []
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text") or "")
        text = "\n".join(p for p in parts if p).strip()
        if text:
            if limit and len(text) > limit:
                suffix = "\n\n...(result text truncated)"
                text = text[:max(0, limit - len(suffix))].rstrip() + suffix
            return text
    return ""


def notify_project(cwd):
    raw = str(cwd or "").strip()
    if not raw:
        return "当前会话"
    norm = raw.rstrip("\\/")
    base = norm.replace("\\", "/").split("/")[-1]
    return base or norm or raw


def notify_compact(text, limit=260):
    value = " ".join(str(text or "").split())
    if limit and len(value) > limit:
        value = value[:max(0, limit - 3)].rstrip() + "..."
    return value


def notify_copy(kind, cwd, actor="Agent", detail="", danger=False):
    """Compose short, action-first notification copy for push and desktop banners."""
    project = notify_project(cwd)
    if kind == "plan":
        title, hint = "计划待审阅 · " + project, "点击打开会话审阅计划"
    elif kind in ("ask", "form"):
        title, hint = "需要输入 · " + project, "点击打开会话回复"
    elif kind == "done":
        title, hint = "任务完成 · " + project, "等待下一条指令"
    elif kind == "confirm":
        title = ("高危操作待确认 · " if danger else "需要确认 · ") + project
        hint = "点击打开会话处理确认"
    else:
        title, hint = "Agent 通知 · " + project, "点击打开会话查看"
    lines = [str(actor or "Agent").strip()]
    compact_detail = notify_compact(detail)
    if compact_detail:
        lines.append(compact_detail)
    if hint:
        lines.append(hint)
    if cwd:
        lines.append(str(cwd))
    return title, "\n".join(line for line in lines if line)


def ps_quote(value):
    return str(value).replace("\r", " ").replace("\n", " ").replace("'", "''")


DESKTOP_TOAST_PS = r"""[void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
$t='<T>'; $b='<B>'
$tpl = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($tpl.GetXml())
$nodes = $xml.GetElementsByTagName('text')
$nodes.Item(0).InnerText = $t
$nodes.Item(1).InnerText = $b
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
$ok=$false
foreach($a in @('Microsoft.Windows.Explorer','Microsoft.Windows.Shell.RunDialog')){
  try { [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($a).Show($toast); $ok=$true; break }
  catch {}
}
if(-not $ok){ try { [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier().Show($toast) } catch { exit 3 } }"""


def desktop_notify(title, body="", settings=None):
    if os.name != "nt" or not (settings and settings.desktop_toast):
        return False
    title = (str(title).strip() or "notice")[:200]
    body = str(body).strip()[:400]
    try:
        script = DESKTOP_TOAST_PS.replace("<T>", ps_quote(title)).replace("<B>", ps_quote(body))
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=8, creationflags=settings.create_no_window)
        return result.returncode == 0
    except Exception as exc:
        print("notify desktop toast failed: %s" % exc)
        return False


def push_notify(title, body, event, settings, webhook_body=None):
    """Send a notification over every configured channel. Returns True on any 2xx."""
    if not notify_enabled_for(event, settings):
        return False
    try:
        desktop_notify(title, body, settings=settings)
    except Exception:
        pass
    ok = False
    full = (str(title) + "\n" + str(body)).strip()
    if settings.telegram_token and settings.telegram_chat:
        try:
            data = urllib.parse.urlencode({"chat_id": settings.telegram_chat, "text": full}).encode()
            conn = http.client.HTTPSConnection("api.telegram.org", timeout=settings.timeout)
            try:
                conn.request("POST", "/bot%s/sendMessage" % settings.telegram_token, body=data,
                             headers={"Content-Type": "application/x-www-form-urlencoded"})
                resp = conn.getresponse()
                resp.read()
                ok = ok or 200 <= resp.status < 300
            finally:
                conn.close()
        except Exception as exc:
            print("notify telegram failed: %s" % exc)
    if settings.bark_key:
        try:
            if settings.bark_key.lower().startswith("http"):
                parsed = urllib.parse.urlsplit(settings.bark_key)
                scheme, host, basepath = parsed.scheme or "https", parsed.netloc, parsed.path.rstrip("/")
            else:
                scheme, host, basepath = "https", "api.day.app", "/" + settings.bark_key.strip("/")
            path = "%s/%s/%s" % (basepath,
                                 urllib.parse.quote(str(title).strip() or "notice", safe=""),
                                 urllib.parse.quote(str(body).strip(), safe=""))
            cls = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
            conn = cls(host, timeout=settings.timeout)
            try:
                conn.request("GET", path)
                resp = conn.getresponse()
                resp.read()
                ok = ok or 200 <= resp.status < 300
            finally:
                conn.close()
        except Exception as exc:
            print("notify bark failed: %s" % exc)
    if settings.webhook_url:
        try:
            if webhook_send(settings.webhook_url, settings.webhook_secret, title, body, event,
                            timeout=settings.timeout, webhook_body=webhook_body):
                ok = True
        except Exception as exc:
            print("notify webhook failed: %s" % exc)
    return ok


def webhook_is_feishu(url):
    url = url.lower()
    return "feishu.cn" in url or "larksuite" in url or "open-apis/bot" in url


def webhook_send(url, secret, title, body, event, timeout=6.0, webhook_body=None):
    parsed = urllib.parse.urlsplit(url)
    path_q = (parsed.path or "/") + (("?" + parsed.query) if parsed.query else "")
    cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    webhook_text = body if webhook_body is None else webhook_body
    if webhook_is_feishu(url):
        text = (str(title) + "\n" + str(webhook_text)).strip()
        data = {"msg_type": "text", "content": {"text": text}}
        if secret:
            ts = str(int(time.time()))
            sign = base64.b64encode(
                hmac.new(("%s\n%s" % (ts, secret)).encode("utf-8"),
                         digestmod=hashlib.sha256).digest()).decode("utf-8")
            data["timestamp"] = ts
            data["sign"] = sign
        payload = json.dumps(data).encode()
    else:
        payload = json.dumps({"title": str(title), "body": str(webhook_text), "event": event}).encode()
    conn = cls(parsed.netloc, timeout=timeout)
    try:
        conn.request("POST", path_q, body=payload, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        raw = resp.read()
        success = 200 <= resp.status < 300
        if success and webhook_is_feishu(url):
            try:
                obj = json.loads(raw.decode("utf-8", "replace"))
                code = obj.get("code", obj.get("StatusCode", 0))
                if code not in (0, None):
                    success = False
                    print("notify feishu rejected: %s" % (
                        obj.get("msg") or obj.get("StatusMessage") or raw[:200]))
            except Exception:
                pass
        return success
    finally:
        conn.close()

# -*- coding: utf-8 -*-
"""Claude/Codex history and recent-directory helpers."""
import json
import os
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class HistorySettings:
    claude_home: str
    claude_scan_cap: int
    codex_enabled: bool = False


def iso_to_epoch(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0


def claude_user_text(obj):
    """Pull the human-typed text out of a Claude 'user' record."""
    msg = obj.get("message") or {}
    content = msg.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text") or "")
        return " ".join(part for part in parts if part).strip()
    return ""


def claude_projects_dir(settings, ctx=None):
    home = (ctx or {}).get("claude_home") if isinstance(ctx, dict) else None
    return os.path.join(home or settings.claude_home, "projects")


def transcript_is_human_turn(obj):
    """True if a Claude transcript 'user' record is a human message, not tool_result."""
    content = (obj.get("message") or {}).get("content")
    if isinstance(content, str):
        return True
    if isinstance(content, list):
        has_text = any(isinstance(b, dict) and b.get("type") == "text" for b in content)
        has_result = any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
        return has_text and not has_result
    return False


def load_claude_transcript_events(claude_sid, settings, cap=100, ctx=None):
    """Reconstruct native replay events from ~/.claude/projects/*/<session>.jsonl."""
    out = []
    target = (claude_sid or "").strip() + ".jsonl"
    projects_dir = claude_projects_dir(settings, ctx)
    if not target or not os.path.isdir(projects_dir):
        return out
    path = None
    for dirpath, _dirs, files in os.walk(projects_dir):
        if target in files:
            path = os.path.join(dirpath, target)
            break
    if not path:
        return out
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return out
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        typ = obj.get("type")
        if typ not in ("user", "assistant"):
            continue
        if typ == "user" and transcript_is_human_turn(obj) and out:
            out.append({"type": "result"})
        out.append(obj)
    if out:
        out.append({"type": "result"})
    return out[-cap:] if cap else out


def load_claude_history(settings, ctx=None):
    """Scan Claude transcripts and mark every restorable item as a native web session."""
    out = []
    projects_dir = claude_projects_dir(settings, ctx)
    if not os.path.isdir(projects_dir):
        return out
    for dirpath, _dirs, files in os.walk(projects_dir):
        for filename in files:
            if not filename.endswith(".jsonl"):
                continue
            if os.path.basename(dirpath) == "subagents" or filename.startswith("agent-"):
                continue
            sid = filename[:-6]
            cwd = ts_str = first_user = ai_title = ""
            try:
                with open(os.path.join(dirpath, filename), "r", encoding="utf-8") as f:
                    for idx, line in enumerate(f):
                        if idx >= settings.claude_scan_cap:
                            break
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                        except ValueError:
                            continue
                        if not cwd and obj.get("cwd"):
                            cwd = obj["cwd"]
                        if not ts_str and obj.get("timestamp"):
                            ts_str = obj["timestamp"]
                        typ = obj.get("type")
                        if typ == "ai-title" and not ai_title:
                            ai_title = (obj.get("aiTitle") or "").strip()
                        elif typ == "summary" and not ai_title:
                            ai_title = (obj.get("summary") or "").strip()
                        elif typ == "user" and not first_user:
                            text = claude_user_text(obj)
                            if text:
                                first_user = text
                        if cwd and ts_str and ai_title:
                            break
            except OSError:
                continue
            if not cwd:
                continue
            out.append({
                "session_id": sid,
                "cwd": cwd,
                "ts": iso_to_epoch(ts_str),
                "title": (ai_title or first_user or "(Untitled)").strip(),
                "originator": "",
                "backend": "claude_native",
            })
    return out


def _load_codex_history(limit, ctx, live_codex, list_thread_history_fn=None):
    if list_thread_history_fn is None:
        from codex_native import list_thread_history as list_thread_history_fn
    ctx = ctx or {}
    return list_thread_history_fn(limit=limit, archived=False,
                                  user=ctx.get("user", ""),
                                  uid=ctx.get("uid", ""),
                                  state_dir=ctx.get("state_dir"),
                                  codex_home=ctx.get("codex_home"),
                                  live=bool(live_codex))


def load_history(settings, limit=60, ctx=None, live_codex=False, list_thread_history_fn=None):
    out = load_claude_history(settings, ctx=ctx)
    if settings.codex_enabled:
        try:
            out.extend(_load_codex_history(limit, ctx, live_codex, list_thread_history_fn))
        except Exception as exc:
            print("WARN: failed to load Codex history: %s" % exc)
    out.sort(key=lambda item: item.get("ts") or 0, reverse=True)
    return out[:limit]


def delete_history(sid, settings, backend=None, ctx=None, is_codex_backend_fn=None, delete_thread_fn=None):
    """Delete one Claude transcript or Codex thread by session id. Running sessions are not touched."""
    sid = (sid or "").strip()
    result = {"deleted": False, "session_file": None}
    is_codex = bool(is_codex_backend_fn and is_codex_backend_fn(backend))
    if is_codex:
        if not sid:
            return result
        try:
            if delete_thread_fn is None:
                from codex_native import delete_thread as delete_thread_fn
            ctx = ctx or {}
            result["deleted"] = bool(delete_thread_fn(sid, user=ctx.get("user", ""),
                                                      uid=ctx.get("uid", ""),
                                                      state_dir=ctx.get("state_dir"),
                                                      codex_home=ctx.get("codex_home")))
            result["session_file"] = sid
        except Exception:
            pass
        return result
    projects_dir = claude_projects_dir(settings, ctx)
    if not sid or not os.path.isdir(projects_dir):
        return result
    target = sid + ".jsonl"
    for dirpath, _dirs, files in os.walk(projects_dir):
        if target in files:
            path = os.path.join(dirpath, target)
            try:
                os.unlink(path)
                result["deleted"] = True
                result["session_file"] = path
            except OSError:
                pass
            break
    return result


def recent_dirs(settings, limit=30, ctx=None, load_history_fn=None):
    load_history_fn = load_history_fn or load_history
    by_cwd = {}
    for item in load_history_fn(settings, 500, ctx=ctx):
        cwd = item.get("cwd") or "(unknown directory)"
        entry = by_cwd.get(cwd)
        if entry is None:
            entry = {"cwd": cwd, "count": 0, "last_ts": 0}
            by_cwd[cwd] = entry
        entry["count"] += 1
        if (item.get("ts") or 0) > entry["last_ts"]:
            entry["last_ts"] = item.get("ts") or 0
    return sorted(by_cwd.values(), key=lambda item: item["last_ts"], reverse=True)[:limit]

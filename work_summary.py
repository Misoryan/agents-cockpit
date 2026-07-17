# -*- coding: utf-8 -*-
"""Compact work-view summaries for replayable agent events."""
import copy
import json
import re


_MAX_USER_TEXT = 700
_MAX_ASSISTANT_TEXT = 12000
_MAX_TOOL_PREVIEW = 900
_MAX_TOOL_INPUT = 1600
_MAX_ACTION_LABEL = 180
_MAX_TURNS = 80
_MAX_TOOLS_PER_TURN = 80
_MAX_RUNNING_TOOLS_VISIBLE = 1
_MAX_FILES = 80


def _seq(event):
    try:
        return int((event or {}).get("merged_seq") or (event or {}).get("seq") or 0)
    except Exception:
        return 0


def _start_seq(event):
    try:
        return int((event or {}).get("seq") or (event or {}).get("merged_seq") or 0)
    except Exception:
        return 0


def _short(text, limit):
    text = str(text or "")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 24)].rstrip() + "\n... (truncated)"


def _line_count(text):
    text = str(text or "")
    return len(text.splitlines()) if text else 0


def _blocks(event):
    msg = (event or {}).get("message") or {}
    content = msg.get("content")
    if isinstance(content, list):
        return [block for block in content if isinstance(block, dict)]
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, dict):
        return [content]
    return []


def _json_preview(value, limit=260):
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except Exception:
        text = str(value or "")
    return _short(text, limit)


def _compact_value(value, limit=_MAX_TOOL_INPUT):
    if isinstance(value, str):
        return _short(value, limit)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_compact_value(item, max(120, limit // 3)) for item in value[:8]]
    if isinstance(value, dict):
        out = {}
        for key in list(value.keys())[:16]:
            out[str(key)] = _compact_value(value.get(key), max(120, limit // 3))
        return out
    return _short(str(value), limit)


def _compact_input(name, inp):
    inp = inp or {}
    if not isinstance(inp, dict):
        return {}
    lower = str(name or "").lower()
    keep = []
    if lower in ("bash", "powershell"):
        keep = ["command", "cmd", "cwd"]
    elif lower in ("edit", "str_replace_edit", "write", "write_file"):
        keep = ["file_path", "path", "old_str", "old_string", "new_str", "new_string", "content"]
    elif lower == "multiedit":
        keep = ["file_path", "path", "edits"]
    elif lower in ("websearch", "web_search"):
        keep = ["query"]
    elif lower in ("webfetch", "web_fetch"):
        keep = ["url", "prompt"]
    elif lower in ("read", "glob", "grep"):
        keep = ["file_path", "path", "pattern", "offset", "limit"]
    elif lower in ("todowrite", "todo_write"):
        keep = ["todos"]
    else:
        keep = [
            "description", "file_path", "path", "command", "cmd", "cwd", "query",
            "url", "prompt", "pattern", "reason", "message",
        ]
    out = {}
    for key in keep:
        if key in inp and inp.get(key) not in (None, ""):
            out[key] = _compact_value(inp.get(key))
    return out


def _uniq_append(items, value, limit=None):
    value = str(value or "").strip()
    if not value or value in items:
        return
    if limit is not None and len(items) >= limit:
        return
    items.append(value)


def _diff_stats(text):
    text = str(text or "")
    if "diff --git " not in text and "\n+++ " not in text and not text.startswith("+++ "):
        return {"files": [], "file_stats": [], "added": 0, "deleted": 0}
    files = []
    file_map = {}
    current = ""
    added = 0
    deleted = 0
    def ensure_file(path):
        path = str(path or "").strip()
        path = path[2:] if path.startswith(("a/", "b/")) else path
        if not path or path == "/dev/null":
            return ""
        _uniq_append(files, path, _MAX_FILES)
        if path not in file_map:
            file_map[path] = {"path": path, "added": 0, "deleted": 0}
        return path
    for line in text.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            path = parts[3] if len(parts) > 3 else (parts[2] if len(parts) > 2 else "")
            current = ensure_file(path)
        elif line.startswith("+++ "):
            path = line[4:].strip()
            current = ensure_file(path) or current
        elif line.startswith("+") and not line.startswith("+++ "):
            added += 1
            if current and current in file_map:
                file_map[current]["added"] += 1
        elif line.startswith("-") and not line.startswith("--- "):
            deleted += 1
            if current and current in file_map:
                file_map[current]["deleted"] += 1
    return {
        "files": files,
        "file_stats": [file_map[path] for path in files if path in file_map],
        "added": added,
        "deleted": deleted,
    }


def _parse_exit_duration(text):
    exit_code = None
    duration_ms = None
    for line in reversed(str(text or "").splitlines()[-8:]):
        m = re.match(r"^\s*exit code:\s*(-?\d+)\s*$", line, re.I)
        if m and exit_code is None:
            exit_code = int(m.group(1))
            continue
        m = re.match(r"^\s*duration ms:\s*(\d+)\s*$", line, re.I)
        if m and duration_ms is None:
            duration_ms = int(m.group(1))
    return exit_code, duration_ms


def _tool_label(name, inp):
    inp = inp or {}
    lower = str(name or "").lower()
    if lower in ("bash", "powershell"):
        return inp.get("command") or inp.get("cmd") or name
    if lower in ("edit", "str_replace_edit", "write", "write_file", "multiedit"):
        return inp.get("file_path") or inp.get("path") or name
    if lower in ("websearch", "web_search"):
        return inp.get("query") or name
    if lower in ("webfetch", "web_fetch"):
        return inp.get("url") or name
    if lower in ("read", "glob", "grep"):
        return inp.get("file_path") or inp.get("path") or inp.get("pattern") or name
    if lower in ("todowrite", "todo_write"):
        todos = inp.get("todos") or []
        return "%s items" % len(todos) if todos else name
    return _json_preview(inp, 180) if inp else (name or "tool")


def _tool_files(name, inp):
    inp = inp or {}
    files = []
    for key in ("file_path", "path"):
        _uniq_append(files, inp.get(key), _MAX_FILES)
    for change in inp.get("changes") or []:
        if isinstance(change, dict):
            _uniq_append(files, change.get("path"), _MAX_FILES)
    return files


def _compact_tool(tool):
    if not tool:
        return None
    compact = {
        "id": str(tool.get("id") or ""),
        "name": str(tool.get("name") or "Tool"),
        "label": _short(tool.get("label") or "", _MAX_ACTION_LABEL),
        "status": str(tool.get("status") or "done"),
        "seq": tool.get("seq") or 0,
        "merged_seq": tool.get("merged_seq") or tool.get("seq") or 0,
    }
    for key in ("exit_code", "duration_ms", "output_lines", "output_chars"):
        if tool.get(key) not in (None, ""):
            compact[key] = tool.get(key)
    if tool.get("input"):
        compact["input"] = copy.deepcopy(tool.get("input") or {})
    if tool.get("preview"):
        compact["preview"] = _short(tool.get("preview") or "", _MAX_TOOL_PREVIEW)
    if tool.get("result"):
        compact["result"] = _short(tool.get("result") or "", _MAX_TOOL_PREVIEW)
    if tool.get("files"):
        compact["files"] = list(tool.get("files") or [])[:8]
    if isinstance(tool.get("diff"), dict):
        compact["diff"] = {
            "files": int((tool.get("diff") or {}).get("files") or 0),
            "added": int((tool.get("diff") or {}).get("added") or 0),
            "deleted": int((tool.get("diff") or {}).get("deleted") or 0),
        }
    if tool.get("changed_files"):
        compact["changed_files"] = list(tool.get("changed_files") or [])[:8]
    return compact


def _tool_summary(counts, limit=6):
    out = []
    for name, count in (counts or {}).items():
        try:
            n = int(count or 0)
        except Exception:
            n = 0
        if n > 0:
            out.append({"name": str(name or "Tool"), "count": n})
        if len(out) >= limit:
            break
    return out


def _new_turn(event=None, user_text="", user_images=0):
    seq = _start_seq(event) if event else 0
    return {
        "type": "work_turn",
        "seq": seq,
        "merged_seq": _seq(event) if event else seq,
        "key": "turn-%s" % (seq or "pending"),
        "status": "running",
        "user_text": _short(user_text, _MAX_USER_TEXT),
        "user_images": int(user_images or 0),
        "assistant_text": "",
        "assistant_text_truncated": False,
        "assistant_text_chars": 0,
        "assistant_text_hidden": False,
        "_stream_text": "",
        "thinking_chars": 0,
        "text_stream_chars": 0,
        "tools": [],
        "tool_total": 0,
        "tool_counts": {},
        "tool_summary": [],
        "latest_tool": None,
        "files": [],
        "file_total": 0,
        "changed_files": [],
        "diff_added": 0,
        "diff_deleted": 0,
        "diff_total": 0,
        "commands": [],
        "todos": [],
        "elapsed_ms": None,
        "started_at_ms": None,
        "started_ts": (event or {}).get("ts"),
        "finished_ts": None,
        "duration_ms": None,
        "usage": {},
        "error": "",
    }


def _human_user_content(event):
    blocks = _blocks(event)
    if not blocks:
        return "", 0, False
    texts = []
    images = 0
    only_tool_results = True
    for block in blocks:
        typ = block.get("type")
        if typ == "tool_result":
            continue
        only_tool_results = False
        if typ == "text":
            texts.append(str(block.get("text") or ""))
        elif typ in ("image", "localImage"):
            images += 1
    return "\n".join(texts).strip(), images, not only_tool_results


def _find_tool(turn, tool_id):
    if not tool_id:
        return None
    for tool in reversed(turn.get("tools") or []):
        if tool.get("id") == tool_id:
            return tool
    return None


def _merge_changed_file(turn, path, added=0, deleted=0):
    path = str(path or "").strip()
    if not path:
        return
    try:
        added = int(added or 0)
    except Exception:
        added = 0
    try:
        deleted = int(deleted or 0)
    except Exception:
        deleted = 0
    rows = turn.setdefault("changed_files", [])
    target = None
    for row in rows:
        if row.get("path") == path:
            target = row
            break
    if target is None:
        if len(rows) >= _MAX_FILES:
            return
        target = {"path": path, "added": 0, "deleted": 0, "total": 0}
        rows.append(target)
    target["added"] = int(target.get("added") or 0) + max(0, added)
    target["deleted"] = int(target.get("deleted") or 0) + max(0, deleted)
    target["total"] = int(target.get("added") or 0) + int(target.get("deleted") or 0)
    turn["diff_added"] = int(turn.get("diff_added") or 0) + max(0, added)
    turn["diff_deleted"] = int(turn.get("diff_deleted") or 0) + max(0, deleted)
    turn["diff_total"] = int(turn.get("diff_added") or 0) + int(turn.get("diff_deleted") or 0)


def _add_tool(turn, block, event):
    inp = block.get("input") or {}
    name = block.get("name") or "Tool"
    tool_id = str(block.get("id") or "")
    lower = name.lower()
    tool = {
        "id": tool_id,
        "name": name,
        "label": _short(_tool_label(name, inp), 360),
        "status": "running",
        "seq": _start_seq(event),
        "merged_seq": _seq(event),
        "output_lines": 0,
        "output_chars": 0,
        "exit_code": None,
        "duration_ms": None,
        "preview": "",
        "result": "",
        "files": _tool_files(name, inp),
        "input": _compact_input(name, inp),
    }
    turn["tools"].append(tool)
    turn["tool_total"] = int(turn.get("tool_total") or 0) + 1
    turn["latest_tool"] = tool
    if len(turn["tools"]) > _MAX_TOOLS_PER_TURN:
        turn["tools"] = turn["tools"][-_MAX_TOOLS_PER_TURN:]
    turn["tool_counts"][name] = int(turn["tool_counts"].get(name) or 0) + 1
    for path in tool["files"]:
        _uniq_append(turn["files"], path, _MAX_FILES)
    if lower in ("bash", "powershell"):
        _uniq_append(turn["commands"], tool["label"], 40)
    if lower in ("todowrite", "todo_write"):
        todos = inp.get("todos") or []
        if isinstance(todos, list):
            turn["todos"] = [
                {"content": str(item.get("content") or item.get("activeForm") or ""),
                 "status": str(item.get("status") or "pending")}
                for item in todos if isinstance(item, dict)
            ]
    return tool


def _apply_tool_result(turn, block, event):
    tool_id = str(block.get("tool_use_id") or "")
    tool = _find_tool(turn, tool_id)
    if tool is None:
        tool = {
            "id": tool_id,
            "name": "ToolResult",
            "label": tool_id or "tool result",
            "status": "done",
            "seq": _start_seq(event),
            "merged_seq": _seq(event),
            "output_lines": 0,
            "output_chars": 0,
            "exit_code": None,
            "duration_ms": None,
            "preview": "",
            "result": "",
            "files": [],
            "input": {},
        }
        turn["tools"].append(tool)
        turn["tool_total"] = int(turn.get("tool_total") or 0) + 1
        turn["tool_counts"]["ToolResult"] = int(turn["tool_counts"].get("ToolResult") or 0) + 1
    content = block.get("content")
    text = content if isinstance(content, str) else _json_preview(content, _MAX_TOOL_PREVIEW)
    tool["output_lines"] = _line_count(text)
    tool["output_chars"] = len(str(text or ""))
    exit_code = block.get("exit_code")
    if exit_code is None:
        exit_code = block.get("exitCode")
    duration_ms = block.get("duration_ms")
    if duration_ms is None:
        duration_ms = block.get("durationMs")
    parsed_exit, parsed_dur = _parse_exit_duration(text)
    if exit_code is None:
        exit_code = parsed_exit
    if duration_ms is None:
        duration_ms = parsed_dur
    tool["exit_code"] = exit_code
    tool["duration_ms"] = duration_ms
    failed = exit_code not in (None, "", 0, "0")
    tool["status"] = "failed" if failed else "done"
    result_text = _short(str(text or "").strip(), _MAX_TOOL_PREVIEW)
    tool["result"] = result_text
    if failed or tool["output_lines"] <= 80:
        tool["preview"] = result_text
    stats = _diff_stats(text)
    if stats["files"]:
        tool["diff"] = {"files": len(stats["files"]), "added": stats["added"], "deleted": stats["deleted"]}
        tool["changed_files"] = stats.get("file_stats") or []
        for path in stats["files"]:
            _uniq_append(tool["files"], path, _MAX_FILES)
            _uniq_append(turn["files"], path, _MAX_FILES)
        for row in stats.get("file_stats") or []:
            _merge_changed_file(turn, row.get("path"), row.get("added"), row.get("deleted"))
    turn["latest_tool"] = tool


def _append_assistant_text(turn, text):
    text = str(text or "")
    if not text.strip():
        return
    combined = (turn.get("assistant_text") or "")
    if combined:
        combined += "\n\n"
    combined += text
    turn["assistant_text_chars"] = len(combined)
    turn["assistant_text_truncated"] = len(combined) > _MAX_ASSISTANT_TEXT
    turn["assistant_text"] = _short(combined, _MAX_ASSISTANT_TEXT)


def _stream_delta_text(event, field):
    chunks = (event or {}).get("_stream_chunks") or []
    if chunks:
        return "".join(str((chunk or {}).get("text") or "") for chunk in chunks if isinstance(chunk, dict))
    delta = (((event or {}).get("event") or {}).get("delta") or {})
    return str(delta.get(field) or "")


def _finalize_turn_for_work(turn):
    turn["tool_total"] = max(
        int(turn.get("tool_total") or 0),
        sum(int(v or 0) for v in (turn.get("tool_counts") or {}).values()),
        len(turn.get("tools") or []),
    )
    turn["file_total"] = len(turn.get("files") or [])
    turn["tool_summary"] = _tool_summary(turn.get("tool_counts") or {})
    changed = sorted(
        (turn.get("changed_files") or []),
        key=lambda row: int(row.get("total") or 0),
        reverse=True,
    )[:_MAX_FILES]
    turn["changed_files"] = changed
    turn["diff_added"] = sum(int(row.get("added") or 0) for row in changed)
    turn["diff_deleted"] = sum(int(row.get("deleted") or 0) for row in changed)
    turn["diff_total"] = int(turn.get("diff_added") or 0) + int(turn.get("diff_deleted") or 0)

    latest = turn.get("latest_tool") or ((turn.get("tools") or [])[-1] if turn.get("tools") else None)
    latest = _compact_tool(latest)
    is_running = turn.get("status") == "running"
    turn["latest_tool"] = latest if is_running else None
    if is_running:
        compact_tools = [_compact_tool(tool) for tool in (turn.get("tools") or [])[-_MAX_RUNNING_TOOLS_VISIBLE:]]
        turn["tools"] = [tool for tool in compact_tools if tool]
    else:
        turn["tools"] = []

    if not turn.get("assistant_text") and turn.get("_stream_text"):
        stream_text = str(turn.get("_stream_text") or "")
        turn["assistant_text_chars"] = len(stream_text)
        turn["assistant_text_truncated"] = len(stream_text) > _MAX_ASSISTANT_TEXT
        turn["assistant_text"] = _short(stream_text, _MAX_ASSISTANT_TEXT)
    text = turn.get("assistant_text") or ""
    if text:
        turn["assistant_text_chars"] = max(int(turn.get("assistant_text_chars") or 0), len(text))
        turn["assistant_text_hidden"] = True

    # Work View intentionally keeps counts, not long paths/commands/previews.
    turn["files"] = []
    turn["commands"] = []
    turn.pop("_stream_text", None)
    return turn


def summarize_events(events, snapshot=None, pending=None, max_turns=_MAX_TURNS):
    turns = []
    current = None
    latest_todos = []
    last_seq = 0
    for event in events or []:
        if not isinstance(event, dict):
            continue
        typ = event.get("type")
        last_seq = max(last_seq, _seq(event))
        if typ == "user":
            text, images, is_human = _human_user_content(event)
            if is_human:
                current = _new_turn(event, text, images)
                turns.append(current)
                continue
            if current is None:
                current = _new_turn(event)
                turns.append(current)
            for block in _blocks(event):
                if block.get("type") == "tool_result":
                    _apply_tool_result(current, block, event)
            current["merged_seq"] = max(current.get("merged_seq") or 0, _seq(event))
            continue
        if typ == "turn_started":
            if current is None:
                current = _new_turn(event)
                turns.append(current)
            current["status"] = "running"
            current["merged_seq"] = max(current.get("merged_seq") or 0, _seq(event))
            continue
        if current is None and typ in ("assistant", "stream_event", "result", "interrupted"):
            current = _new_turn(event)
            turns.append(current)
        if current is None:
            continue
        if typ == "stream_event":
            delta = ((event.get("event") or {}).get("delta") or {})
            if delta.get("type") == "thinking_delta":
                text = _stream_delta_text(event, "thinking")
                current["thinking_chars"] += len(str(text or ""))
            elif delta.get("type") == "text_delta":
                text = _stream_delta_text(event, "text")
                current["text_stream_chars"] += len(str(text or ""))
                current["_stream_text"] = (current.get("_stream_text") or "") + str(text or "")
            current["merged_seq"] = max(current.get("merged_seq") or 0, _seq(event))
        elif typ == "assistant":
            for block in _blocks(event):
                btype = block.get("type")
                if btype == "text":
                    _append_assistant_text(current, block.get("text") or "")
                elif btype == "thinking":
                    current["thinking_chars"] += len(str(block.get("thinking") or ""))
                elif btype == "tool_use":
                    _add_tool(current, block, event)
            current["merged_seq"] = max(current.get("merged_seq") or 0, _seq(event))
            if current.get("todos"):
                latest_todos = list(current["todos"])
        elif typ == "result":
            current["status"] = "error" if event.get("error") or event.get("is_error") else "done"
            current["duration_ms"] = event.get("duration_ms")
            current["finished_ts"] = event.get("ts") or current.get("finished_ts")
            current["usage"] = event.get("usage") or {}
            current["error"] = _short(event.get("error") or "", _MAX_TOOL_PREVIEW)
            current["merged_seq"] = max(current.get("merged_seq") or 0, _seq(event))
            current = None
        elif typ == "interrupted":
            current["status"] = "interrupted"
            current["finished_ts"] = event.get("ts") or current.get("finished_ts")
            current["merged_seq"] = max(current.get("merged_seq") or 0, _seq(event))
            current = None
    snapshot = snapshot or {}
    if turns and snapshot.get("running"):
        turns[-1]["status"] = "running"
    elif turns and turns[-1].get("status") == "running":
        turns[-1]["status"] = "done"
    if turns and turns[-1].get("status") == "running":
        elapsed_ms = snapshot.get("turn_elapsed_ms")
        started_at_ms = snapshot.get("turn_started_at_ms")
        if elapsed_ms is None and started_at_ms and snapshot.get("server_now_ms"):
            try:
                elapsed_ms = max(0, int(snapshot.get("server_now_ms")) - int(started_at_ms))
            except Exception:
                elapsed_ms = None
        turns[-1]["elapsed_ms"] = elapsed_ms
        turns[-1]["started_at_ms"] = started_at_ms
    for turn in turns:
        if turn.get("todos"):
            latest_todos = list(turn["todos"])
    pending = pending or []
    status = snapshot.get("state") or ("running" if snapshot.get("running") else "idle")
    if pending:
        status = "confirm"
    visible_turns = turns[-max_turns:]
    file_total = len({path for turn in visible_turns for path in (turn.get("files") or [])})
    tool_total = sum(int(turn.get("tool_total") or len(turn.get("tools") or [])) for turn in visible_turns)
    visible_turns = [_finalize_turn_for_work(turn) for turn in visible_turns]
    return {
        "type": "work_replay",
        "status": status,
        "running": bool(snapshot.get("running")),
        "turns": visible_turns,
        "turn_count": len(turns),
        "tool_total": tool_total,
        "file_total": file_total,
        "latest_todos": latest_todos,
        "pending_count": len(pending),
        "last_seq": snapshot.get("last_seq") or last_seq,
        "turn_elapsed_ms": snapshot.get("turn_elapsed_ms"),
        "turn_started_at_ms": snapshot.get("turn_started_at_ms"),
        "server_now_ms": snapshot.get("server_now_ms"),
    }


def _public_event(event):
    out = copy.deepcopy(event)
    if isinstance(out, dict):
        out.pop("_stream_chunks", None)
    return out


def _turn_event_groups(events):
    groups = []
    current = None

    def begin(event):
        seq = _start_seq(event)
        group = {
            "key": "turn-%s" % (seq or (len(groups) + 1)),
            "seq": seq,
            "merged_seq": _seq(event),
            "events": [],
        }
        groups.append(group)
        return group

    for event in events or []:
        if not isinstance(event, dict):
            continue
        typ = event.get("type")
        if typ == "user":
            _text, _images, is_human = _human_user_content(event)
            if is_human:
                current = begin(event)
            elif current is None:
                current = begin(event)
            current["events"].append(_public_event(event))
            current["merged_seq"] = max(int(current.get("merged_seq") or 0), _seq(event))
            continue
        if typ in ("turn_started", "assistant", "stream_event"):
            if current is None:
                current = begin(event)
            current["events"].append(_public_event(event))
            current["merged_seq"] = max(int(current.get("merged_seq") or 0), _seq(event))
            continue
        if typ in ("result", "interrupted"):
            if current is None:
                current = begin(event)
            current["events"].append(_public_event(event))
            current["merged_seq"] = max(int(current.get("merged_seq") or 0), _seq(event))
            current = None
            continue
    return groups


def turn_events_payload(events, snapshot=None, pending=None, turn=None):
    groups = _turn_event_groups(events)
    wanted = str(turn or "").strip()
    selected = None
    for idx, group in enumerate(groups):
        keys = {str(group.get("key") or ""), str(group.get("seq") or ""), str(idx), str(idx + 1)}
        if wanted in keys:
            selected = group
            break
    if selected is None and groups and not wanted:
        selected = groups[-1]
    if selected is None:
        return {
            "ok": False,
            "error": "turn not found",
            "events": [],
            "snapshot": snapshot or {},
            "pending": [],
            "turn": wanted,
        }
    return {
        "ok": True,
        "events": selected.get("events") or [],
        "snapshot": snapshot or {},
        "pending": [],
        "turn": selected.get("key"),
        "last_seq": selected.get("merged_seq") or 0,
    }


def replay_payload(events, snapshot, pending):
    work = summarize_events(events, snapshot=snapshot, pending=pending)
    return {
        "ok": True,
        "events": [],
        "work": work,
        "snapshot": snapshot,
        "pending": pending,
        "last_seq": snapshot.get("last_seq") or work.get("last_seq") or 0,
    }

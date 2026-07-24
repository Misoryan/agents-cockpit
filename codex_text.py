# -*- coding: utf-8 -*-
"""Text, question, and plan-format helpers for Codex sessions."""
import json


def _truthy(value):
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def text_from_user_input(items):
    parts = []
    for item in items or []:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(item.get("text") or "")
    return "\n".join(part for part in parts if part).strip()


def clean_questions(questions):
    out = []
    for question in questions or []:
        if not isinstance(question, dict):
            continue
        options = []
        for option in question.get("options") or []:
            if isinstance(option, dict):
                clean_option = {
                    "label": str(option.get("label") or ""),
                    "description": str(option.get("description") or ""),
                }
                if option.get("value") is not None:
                    clean_option["value"] = str(option.get("value"))
                options.append(clean_option)
            elif option is not None:
                options.append({"label": str(option), "description": ""})
        out.append({
            "id": str(question.get("id") or ""),
            "header": str(question.get("header") or ""),
            "question": str(question.get("question") or ""),
            "multiSelect": _truthy(
                question.get("multiSelect")
                or question.get("multi_select")
                or question.get("multiple")
                or question.get("allowMultiple")
            ),
            "isOther": bool(question.get("isOther")),
            "isSecret": bool(question.get("isSecret")),
            "options": options,
        })
    return out


def question_text(questions, fallback=""):
    parts = []
    for question in questions or []:
        text = question.get("question") or question.get("header") or ""
        if text:
            parts.append(text)
    return "\n\n".join(parts) or fallback


def answer_list(value):
    if isinstance(value, dict) and "answers" in value:
        value = value.get("answers")
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if item is not None and str(item) != ""]
    if value is None:
        return []
    text = str(value)
    return [text] if text else []


def answers_for_questions(questions, answer):
    out = {}
    answer_map = answer if isinstance(answer, dict) else None
    for idx, question in enumerate(questions or []):
        qid = question.get("id") or str(idx)
        if answer_map is not None:
            raw = answer_map.get(qid)
            if raw is None:
                raw = answer_map.get(str(idx))
        else:
            raw = answer
        out[qid] = {"answers": answer_list(raw)}
    return out


def json_text(obj):
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        return str(obj)


def compact_json(obj, limit=900):
    text = json_text(obj)
    if len(text) > limit:
        return text[:limit] + "\n... (truncated)"
    return text


def changes_to_diff(changes):
    out = []
    for change in changes or []:
        if not isinstance(change, dict):
            continue
        path = change.get("path") or ""
        kind = change.get("kind") or ""
        diff = change.get("diff") or ""
        if path or kind:
            out.append("--- %s %s" % (kind, path))
        if diff:
            out.append(diff)
    return "\n".join(out).strip()


def status_text(status):
    if isinstance(status, dict):
        return status.get("type") or compact_json(status, 180)
    return str(status or "")


def extract_text(obj):
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, list):
        return "\n".join(item for item in (extract_text(value) for value in obj) if item)
    if isinstance(obj, dict):
        for key in ("text", "summary", "content", "message", "delta", "part"):
            text = extract_text(obj.get(key))
            if text:
                return text
    return ""


def extract_proposed_plan(text):
    text = str(text or "")
    start_tag = "<proposed_plan>"
    end_tag = "</proposed_plan>"
    start = text.find(start_tag)
    if start < 0:
        return ""
    end = text.find(end_tag, start + len(start_tag))
    if end < 0:
        return ""
    return text[start + len(start_tag):end].strip()


def as_proposed_plan(text):
    text = str(text or "").strip()
    if not text:
        return ""
    if extract_proposed_plan(text):
        return text
    return "<proposed_plan>\n%s\n</proposed_plan>" % text


def plan_text_event(text):
    text = as_proposed_plan(text)
    if not text:
        return None
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}

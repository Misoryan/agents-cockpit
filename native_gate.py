# -*- coding: utf-8 -*-
"""Approval and ask-user formatting helpers for NativeSession."""


def clean_ask_questions(questions):
    out = []
    for question in questions or []:
        if not isinstance(question, dict):
            continue
        options = []
        for option in question.get("options") or []:
            if isinstance(option, dict):
                options.append({"label": str(option.get("label") or ""),
                                "description": str(option.get("description") or "")})
            elif option is not None:
                options.append({"label": str(option), "description": ""})
        out.append({"id": str(question.get("id") or ""),
                    "header": str(question.get("header") or ""),
                    "question": str(question.get("question") or ""),
                    "multiSelect": bool(question.get("multiSelect")),
                    "options": options})
    return out


def format_ask_answer(answer, questions):
    if answer is None:
        return ""
    if isinstance(answer, str):
        return answer
    if isinstance(answer, dict):
        question_map = {}
        for idx, question in enumerate(questions or []):
            qid = question.get("id") or str(idx)
            question_map[qid] = question.get("question") or question.get("header") or ""
        lines = []
        for qid, values in answer.items():
            if isinstance(values, (list, tuple)):
                value_text = ", ".join(str(value) for value in values if value not in (None, ""))
            else:
                value_text = str(values) if values not in (None, "") else ""
            if not value_text:
                continue
            label = question_map.get(qid) or ""
            lines.append(("%s: %s" % (label, value_text)) if label else value_text)
        return chr(10).join(lines)
    return str(answer)


def preview_for(tool_name, input_obj):
    if not isinstance(input_obj, dict):
        return ""
    command = input_obj.get("command") or input_obj.get("cmd")
    if command:
        return command
    if tool_name in ("Edit", "Write", "NotebookEdit"):
        return input_obj.get("file_path") or input_obj.get("path") or ""
    return ""


def is_dangerous(tool_name, input_obj):
    if not isinstance(input_obj, dict):
        return False
    command = (input_obj.get("command") or input_obj.get("cmd") or "").lower()
    return any(word in command for word in ("rm -rf", "rmdir", "del /f", "format ",
                                           "shutdown", "reg delete", ":(){", "mkfs"))

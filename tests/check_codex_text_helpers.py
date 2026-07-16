"""Check extracted Codex text/question helpers."""
import sys
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import codex_native  # noqa: E402
import codex_text  # noqa: E402


def main():
    assert codex_text.text_from_user_input([
        {"type": "text", "text": "hello"},
        {"type": "image", "text": "skip"},
        {"type": "text", "text": "world"},
    ]) == "hello\nworld"

    questions = codex_text.clean_questions([
        {"id": "q1", "header": "Pick", "question": "Choose", "isOther": True,
         "isSecret": True, "options": [{"label": "A", "description": "first"}, "B"]},
        "ignored",
    ])
    assert questions == [{
        "id": "q1",
        "header": "Pick",
        "question": "Choose",
        "isOther": True,
        "isSecret": True,
        "options": [{"label": "A", "description": "first"}, {"label": "B", "description": ""}],
    }]
    assert codex_native._clean_questions(questions) == questions
    assert codex_text.question_text(questions, fallback="fallback") == "Choose"
    assert codex_text.question_text([], fallback="fallback") == "fallback"

    assert codex_text.answer_list({"answers": ["a", "", None, "b"]}) == ["a", "b"]
    assert codex_text.answer_list("x") == ["x"]
    assert codex_text.answer_list(None) == []
    assert codex_text.answers_for_questions(questions, {"q1": ["A"]}) == {"q1": {"answers": ["A"]}}
    assert codex_text.answers_for_questions([{"id": ""}], "free") == {"0": {"answers": ["free"]}}

    compact = codex_text.compact_json({"x": "y" * 20}, limit=10)
    assert compact.endswith("\n... (truncated)")
    assert codex_text.changes_to_diff([
        {"kind": "modify", "path": "a.py", "diff": "@@ diff"},
        {"diff": "only diff"},
    ]) == "--- modify a.py\n@@ diff\nonly diff"
    assert codex_text.status_text({"type": "complete"}) == "complete"

    nested = {"message": [{"content": {"text": "inner"}}]}
    assert codex_text.extract_text(nested) == "inner"
    wrapped = codex_text.as_proposed_plan("step 1")
    assert wrapped == "<proposed_plan>\nstep 1\n</proposed_plan>"
    assert codex_text.extract_proposed_plan(wrapped) == "step 1"
    assert codex_native._plan_text_event("step 1")["message"]["content"][0]["text"] == wrapped
    assert codex_text.plan_text_event("") is None

    print("codex text helper checks passed")


if __name__ == "__main__":
    main()

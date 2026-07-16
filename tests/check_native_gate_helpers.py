"""Check extracted native gate formatting helpers."""
import sys
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import native  # noqa: E402
import native_gate  # noqa: E402


def main():
    questions = native_gate.clean_ask_questions([
        {"id": "choice", "header": "Pick", "question": "Pick one?",
         "multiSelect": True, "options": [{"label": "A", "description": "first"}, "B"]},
        "ignored",
    ])
    assert questions == [{
        "id": "choice",
        "header": "Pick",
        "question": "Pick one?",
        "multiSelect": True,
        "options": [{"label": "A", "description": "first"}, {"label": "B", "description": ""}],
    }]
    assert native._clean_ask_questions(questions) == questions

    answer = native_gate.format_ask_answer({"choice": ["A", "B"], "free": "text"}, questions)
    assert answer == "Pick one?: A, B\ntext"
    assert native._format_ask_answer("plain", questions) == "plain"
    assert native_gate.format_ask_answer(None, questions) == ""

    assert native_gate.preview_for("Bash", {"command": "echo hi"}) == "echo hi"
    assert native_gate.preview_for("Edit", {"file_path": "a.py"}) == "a.py"
    assert native_gate.preview_for("Read", {"file_path": "a.py"}) == ""
    assert native.NativeSession._preview_for("Write", {"path": "b.py"}) == "b.py"

    assert native_gate.is_dangerous("Bash", {"command": "rm -rf /tmp/x"})
    assert native_gate.is_dangerous("PowerShell", {"cmd": "shutdown /s"})
    assert not native_gate.is_dangerous("Bash", {"command": "echo safe"})
    assert native.NativeSession._is_dangerous("Bash", {"command": "format c:"})

    print("native gate helper checks passed")


if __name__ == "__main__":
    main()

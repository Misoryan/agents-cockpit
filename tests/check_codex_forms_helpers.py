"""Check extracted Codex form/schema helpers."""
import sys
from pathlib import Path

if "--help" not in sys.argv:
    sys.argv.append("--help")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import codex_forms  # noqa: E402
import codex_native  # noqa: E402


def main():
    options = codex_forms.option_list({
        "options": [{"value": "a", "label": "A", "description": "first"}, "b"],
        "enum": ["a", "c"],
        "enumNames": ["A duplicate", "C"],
        "oneOf": [{"const": "d", "title": "D"}],
        "anyOf": [{"enum": ["e"], "description": "fifth"}],
    })
    assert options == [
        {"value": "a", "label": "A", "description": "first"},
        {"value": "b", "label": "b", "description": ""},
        {"value": "c", "label": "C", "description": ""},
        {"value": "d", "label": "D", "description": ""},
        {"value": "e", "label": "e", "description": "fifth"},
    ]
    assert codex_native._option_list({"items": {"enum": ["x"]}}) == [
        {"value": "x", "label": "x", "description": ""}
    ]

    assert codex_forms.schema_type({"type": ["null", "integer"]}) == "integer"
    assert codex_forms.form_input_type({"type": "boolean"}, []) == "checkbox"
    assert codex_forms.form_input_type({"type": "array"}, options) == "multiselect"
    assert codex_forms.form_input_type({"type": "array"}, []) == "textarea"
    assert codex_forms.form_input_type({"type": "integer"}, []) == "number"
    assert codex_forms.form_input_type({"format": "multiline"}, []) == "textarea"
    assert codex_forms.form_input_type({}, options) == "select"

    field = codex_forms.field_from_spec("name", {
        "title": "Name",
        "description": "Your name",
        "default": "Alice",
        "enum": ["Alice", "Bob"],
    }, required=True)
    assert field["id"] == "name"
    assert field["label"] == "Name"
    assert field["type"] == "select"
    assert field["required"] is True
    assert field["default"] == "Alice"

    fields = codex_forms.form_fields_from_schema({
        "properties": {
            "name": {"type": "string", "title": "Name"},
            "age": {"type": "integer"},
        },
        "required": ["name"],
    })
    assert [item["id"] for item in fields] == ["name", "age"]
    assert fields[0]["required"] is True
    assert fields[1]["type"] == "number"

    list_fields = codex_native._form_fields_from_schema({
        "fields": [{"name": "choice", "choices": ["x"]}, {"bad": "ok"}]
    })
    assert list_fields[0]["id"] == "choice"
    assert list_fields[0]["type"] == "select"
    assert list_fields[1]["id"] == "field_2"

    print("codex form helper checks passed")


if __name__ == "__main__":
    main()

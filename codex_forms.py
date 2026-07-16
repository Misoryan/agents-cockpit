# -*- coding: utf-8 -*-
"""JSON-schema/form helpers for Codex app-server requests."""


def option_list(spec):
    if not isinstance(spec, dict):
        return []
    raw = spec.get("options")
    if raw is None:
        raw = spec.get("choices")
    opts = []
    if isinstance(raw, list):
        for opt in raw:
            if isinstance(opt, dict):
                value = opt.get("value")
                if value is None:
                    value = opt.get("id") or opt.get("name") or opt.get("const") or opt.get("label") or opt.get("title")
                label = opt.get("label") or opt.get("title") or opt.get("name") or value
                desc = opt.get("description") or opt.get("help") or ""
                if value is not None:
                    opts.append({"value": str(value), "label": str(label), "description": str(desc)})
            elif opt is not None:
                opts.append({"value": str(opt), "label": str(opt), "description": ""})
    enum = spec.get("enum")
    if isinstance(enum, list):
        enum_names = spec.get("enumNames") or []
        for idx, value in enumerate(enum):
            if value is None:
                continue
            label = enum_names[idx] if idx < len(enum_names) and enum_names[idx] else value
            opts.append({"value": str(value), "label": str(label), "description": ""})
    for key in ("oneOf", "anyOf"):
        raw_variants = spec.get(key)
        if isinstance(raw_variants, list):
            for variant in raw_variants:
                if not isinstance(variant, dict):
                    continue
                value = variant.get("const")
                if value is None:
                    variant_enum = variant.get("enum")
                    if isinstance(variant_enum, list) and len(variant_enum) == 1:
                        value = variant_enum[0]
                if value is None:
                    continue
                label = variant.get("title") or variant.get("label") or value
                opts.append({
                    "value": str(value),
                    "label": str(label),
                    "description": str(variant.get("description") or ""),
                })
    if not opts and isinstance(spec.get("items"), dict):
        opts = option_list(spec.get("items"))
    deduped = []
    seen = set()
    for opt in opts:
        value = opt.get("value")
        if value in seen:
            continue
        seen.add(value)
        deduped.append(opt)
    return deduped


def schema_type(spec):
    if not isinstance(spec, dict):
        return "string"
    typ = spec.get("type") or spec.get("inputType") or spec.get("input_type") or ""
    if isinstance(typ, list):
        typ = next((item for item in typ if item != "null"), typ[0] if typ else "")
    return str(typ or "string").lower()


def form_input_type(spec, options):
    typ = schema_type(spec)
    fmt = str(spec.get("format") or "").lower() if isinstance(spec, dict) else ""
    widget = str(spec.get("widget") or spec.get("component") or "").lower() if isinstance(spec, dict) else ""
    if typ in ("boolean", "checkbox") or widget == "checkbox":
        return "checkbox"
    if typ in ("array", "multi_select", "multiselect") or widget in ("multi_select", "multiselect"):
        return "multiselect" if options else "textarea"
    if options:
        return "select"
    if typ in ("number", "integer"):
        return "number"
    if typ in ("textarea", "long_text") or fmt in ("textarea", "multiline") or widget == "textarea":
        return "textarea"
    return "text"


def field_from_spec(key, spec, required=False):
    if not isinstance(spec, dict):
        spec = {}
    options = option_list(spec)
    return {
        "id": str(key),
        "label": str(spec.get("label") or spec.get("title") or spec.get("name") or key),
        "description": str(spec.get("description") or spec.get("help") or ""),
        "type": form_input_type(spec, options),
        "required": bool(required or spec.get("required")),
        "default": spec.get("default"),
        "options": options,
    }


def form_fields_from_schema(schema):
    if not isinstance(schema, dict):
        return []
    fields = []
    raw_fields = schema.get("fields") or schema.get("inputs") or schema.get("elements")
    if isinstance(raw_fields, list):
        for idx, spec in enumerate(raw_fields):
            if not isinstance(spec, dict):
                continue
            key = spec.get("id") or spec.get("name") or spec.get("key") or spec.get("path") or ("field_%d" % (idx + 1))
            fields.append(field_from_spec(key, spec, bool(spec.get("required"))))
        return fields
    props = schema.get("properties")
    if isinstance(props, dict):
        required = set(item for item in (schema.get("required") or []) if isinstance(item, str))
        for key, spec in props.items():
            fields.append(field_from_spec(key, spec, key in required))
    return fields

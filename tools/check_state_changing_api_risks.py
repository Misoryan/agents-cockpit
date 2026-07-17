# -*- coding: utf-8 -*-
"""Validate state-changing API risk metadata covers all mutating routes."""
import argparse
import ast
import inspect
import json
from pathlib import Path
import sys
import textwrap

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import manager_internal_api  # noqa: E402
import manager_user_api  # noqa: E402
import web  # noqa: E402

DOC = ROOT / "docs" / "state-changing-api-risk-matrix.md"
REQUIRED_FIELDS = {"risk", "area", "guards"}


def _literal_path_set_from_function(fn):
    source = textwrap.dedent(inspect.getsource(fn))
    tree = ast.parse(source)
    paths = set()

    def add_value(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value.startswith("/api/"):
            paths.add(node.value)
        elif isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            for item in node.elts:
                add_value(item)

    class Visitor(ast.NodeVisitor):
        def visit_Compare(self, node):
            if isinstance(node.left, ast.Name) and node.left.id == "path":
                for comparator in node.comparators:
                    add_value(comparator)
            self.generic_visit(node)

    Visitor().visit(tree)
    return paths


def _check_entries(name, actual_paths, metadata):
    meta_paths = set(metadata)
    missing = sorted(actual_paths - meta_paths)
    stale = sorted(meta_paths - actual_paths)
    malformed = []
    for path, value in sorted(metadata.items()):
        fields = set(value or {})
        guards = value.get("guards") if isinstance(value, dict) else None
        if not REQUIRED_FIELDS.issubset(fields) or not isinstance(guards, (tuple, list)) or not guards:
            malformed.append(path)
    return {
        "name": name,
        "actual": sorted(actual_paths),
        "metadata": sorted(meta_paths),
        "missing": missing,
        "stale": stale,
        "malformed": malformed,
        "ok": not missing and not stale and not malformed,
    }


def evaluate():
    user_paths = _literal_path_set_from_function(manager_user_api.handle_post)
    web_paths = _literal_path_set_from_function(web.WebHandler._web_post)
    internal_paths = set(manager_internal_api.INTERNAL_GATE_POSTS) | set(manager_internal_api.INTERNAL_CONTROL_POSTS)
    checks = [
        _check_entries("manager_user_api", user_paths, manager_user_api.USER_POST_ROUTE_RISKS),
        _check_entries("manager_internal_api", internal_paths, manager_internal_api.INTERNAL_POST_ROUTE_RISKS),
        _check_entries("web", web_paths, web.WEB_CONTROL_ROUTE_RISKS),
    ]
    doc_text = DOC.read_text(encoding="utf-8") if DOC.exists() else ""
    doc_missing = []
    for check in checks:
        for path in check["actual"]:
            if path not in doc_text:
                doc_missing.append(path)
    return {
        "ok": all(check["ok"] for check in checks) and not doc_missing,
        "checks": checks,
        "doc": str(DOC.relative_to(ROOT)),
        "doc_missing": sorted(doc_missing),
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="Print a machine-readable result.")
    args = parser.parse_args(argv)
    result = evaluate()
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        for check in result["checks"]:
            print("%s: %d routes" % (check["name"], len(check["actual"])))
        if result["doc_missing"]:
            print("doc_missing: %s" % ", ".join(result["doc_missing"]))
        print("ok: %s" % ("true" if result["ok"] else "false"))
    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

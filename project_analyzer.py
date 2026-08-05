"""
project_analyzer.py
--------------------
Analyzes a *project* of bash files (not just one script in isolation).

Fixes the core gap of v1 (extractor.py): when file A does
`source B.sh` and then calls a function defined in B.sh inside an
if-condition or a command, the tool now recognizes that call and
links it to that function's own decision tree — instead of treating
it as an opaque, unrelated command string.

Install dependencies first:
    pip install tree-sitter tree-sitter-bash

Usage:
    python project_analyzer.py path/to/project_dir
    python project_analyzer.py path/to/project_dir -o output.json
    python project_analyzer.py file1.sh file2.sh file3.sh
"""

import argparse
import json
import sys
from pathlib import Path

from tree_sitter import Language, Parser
import tree_sitter_bash as tsbash


def get_parser() -> Parser:
    bash_language = Language(tsbash.language())
    return Parser(bash_language)


def node_text(node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace").strip()


# ---------------------------------------------------------------------------
# Discovery: function definitions and `source`/`.` dependencies
# ---------------------------------------------------------------------------

def discover_functions(root, source: bytes) -> dict:
    """Map function_name -> function_definition node, for every function
    defined anywhere in this file (not descending into nested if/for/etc,
    only stopping recursion at function_definition boundaries themselves)."""
    funcs = {}

    def walk(node):
        for child in node.named_children:
            if child.type == "function_definition":
                name_node = child.child_by_field_name("name")
                if name_node:
                    funcs[node_text(name_node, source)] = child
                # a function defined inside another function is unusual but
                # keep walking in case it happens
                walk(child)
            else:
                walk(child)

    walk(root)
    return funcs


def discover_sources(root, source: bytes) -> list:
    """Find `source file.sh` / `. file.sh` statements anywhere in the file."""
    sourced = []

    def walk(node):
        for child in node.named_children:
            if child.type == "command":
                name_node = child.child_by_field_name("name")
                name_text = node_text(name_node, source) if name_node else None
                if name_text in ("source", "."):
                    arg_nodes = child.children_by_field_name("argument")
                    if arg_nodes:
                        sourced.append(node_text(arg_nodes[0], source))
            else:
                walk(child)

    walk(root)
    return sourced


# ---------------------------------------------------------------------------
# Classification helpers (this is where cross-file linking happens)
# ---------------------------------------------------------------------------

def classify_command(node, source: bytes, known_functions: set) -> dict:
    """Turn a `command` node into a leaf action, recognizing calls to
    known functions (defined anywhere in the project, since bash
    `source` makes them globally visible)."""
    name_node = node.child_by_field_name("name")
    name_text = node_text(name_node, source) if name_node else None
    full_text = node_text(node, source)

    if name_text in ("source", "."):
        return {"type": "source", "text": full_text}
    if name_text in known_functions:
        return {"type": "call", "function": name_text, "text": full_text}
    return {"type": "command", "text": full_text}


def classify_condition(condition_node, source: bytes, known_functions: set) -> dict:
    """Classify an if/elif condition (the node under the `condition` field).
    If it's a single bare command whose name matches a known function,
    mark it as a call (this is the `if check_network; then` case).
    Compound conditions (lists, pipelines, redirected commands, test
    expressions, etc.) are kept as raw text -- they aren't a plain call."""
    if condition_node.type == "command":
        name_node = condition_node.child_by_field_name("name")
        name_text = node_text(name_node, source) if name_node else None
        text = node_text(condition_node, source)
        if name_text in known_functions:
            return {"text": text, "type": "call", "function": name_text}
        return {"text": text, "type": "raw"}

    return {"text": node_text(condition_node, source), "type": "raw"}


# ---------------------------------------------------------------------------
# Building decision-tree nodes
# ---------------------------------------------------------------------------

COMPOUND_TYPES = (
    "for_statement", "while_statement", "c_style_for_statement",
    "subshell", "compound_statement", "do_group",
)


def build_case_node(case_node, source: bytes, known_functions: set) -> dict:
    """A case_statement becomes its own decision-node shape (distinct from
    an if_statement's condition/yes/no): {"case_value":..., "branches":[...]}
    with one branch per case_item, each holding that pattern's own body
    (which itself can contain further nested ifs/cases)."""
    value_node = case_node.child_by_field_name("value")
    value = classify_condition(value_node, source, known_functions) if value_node else None

    branches = []
    for item in case_node.named_children:
        if item.type != "case_item":
            continue
        pattern_node = item.child_by_field_name("value")
        pattern_text = node_text(pattern_node, source) if pattern_node else "*"
        body_nodes = [c for c in item.named_children if c != pattern_node and c.type != "comment"]
        branches.append({"pattern": pattern_text, "then": build_body(body_nodes, source, known_functions)})

    return {
        "case_value": value,
        "line": case_node.start_point[0] + 1,
        "branches": branches,
    }


def build_body(statement_nodes, source: bytes, known_functions: set) -> dict:
    """Build the {"actions": [...], "nested_ifs": [...]} shape for a
    then/elif/else body or a function body. "nested_ifs" holds both
    if_statement and case_statement decision nodes found directly here."""
    actions = []
    nested_ifs = []

    for node in statement_nodes:
        if node.type == "if_statement":
            nested_ifs.append(build_if_node(node, source, known_functions))
        elif node.type == "case_statement":
            nested_ifs.append(build_case_node(node, source, known_functions))
        elif node.type == "command":
            action = classify_command(node, source, known_functions)
            if action["type"] != "source":  # source lines are dependency info, not actions
                actions.append(action)
        elif node.type == "function_definition":
            continue  # handled at the project level, not inline
        elif node.type in COMPOUND_TYPES:
            nested_ifs.extend(find_nested_ifs(node, source, known_functions))
            actions.append({"type": "block", "text": node_text(node, source)})
        else:
            text = node_text(node, source)
            if text:
                actions.append({"type": "other", "text": text})

    return {"actions": actions, "nested_ifs": nested_ifs}


def find_nested_ifs(node, source: bytes, known_functions: set) -> list:
    """Recursively find if_statement/case_statement decision nodes inside
    for/while/subshell bodies, without crossing into a nested
    function_definition."""
    found = []
    for child in node.named_children:
        if child.type == "if_statement":
            found.append(build_if_node(child, source, known_functions))
        elif child.type == "case_statement":
            found.append(build_case_node(child, source, known_functions))
        elif child.type == "function_definition":
            continue
        else:
            found.extend(find_nested_ifs(child, source, known_functions))
    return found


def find_top_level_ifs(root, source: bytes, known_functions: set) -> list:
    """Find if_statement/case_statement decision nodes at the top level of
    a file (outside any function)."""
    found = []
    for child in root.named_children:
        if child.type == "if_statement":
            found.append(build_if_node(child, source, known_functions))
        elif child.type == "case_statement":
            found.append(build_case_node(child, source, known_functions))
        elif child.type == "function_definition":
            continue
        else:
            found.extend(find_nested_ifs(child, source, known_functions))
    return found


def _condition_by_position(node):
    """Fallback for when child_by_field_name('condition') returns None --
    find the anonymous 'then' token and take the named child immediately
    before it. Used because elif_clause doesn't expose 'condition' as a
    field the way if_statement does."""
    children = node.children
    then_idx = next((i for i, c in enumerate(children) if c.type == "then"), None)
    if then_idx is None:
        return None
    named_before = [c for c in children[:then_idx] if c.is_named]
    return named_before[-1] if named_before else None


def build_if_node(if_node, source: bytes, known_functions: set) -> dict:
    """Uses tree-sitter-bash's `condition` field directly (robust across
    simple commands, redirected commands, lists/pipelines, test
    expressions, etc.) rather than scanning for 'if'/'then' tokens."""
    condition_node = if_node.child_by_field_name("condition")
    if condition_node is None:
        condition_node = _condition_by_position(if_node)
    condition = classify_condition(condition_node, source, known_functions) if condition_node else None

    then_nodes = []
    elif_branches = []
    else_branch = None

    for child in if_node.named_children:
        if child == condition_node or child.type == "comment":
            continue
        if child.type == "elif_clause":
            elif_branches.append(build_elif_node(child, source, known_functions))
        elif child.type == "else_clause":
            else_nodes = [c for c in child.named_children if c.type != "comment"]
            else_branch = build_body(else_nodes, source, known_functions)
        else:
            then_nodes.append(child)

    return {
        "condition": condition,
        "line": if_node.start_point[0] + 1,
        "then": build_body(then_nodes, source, known_functions),
        "elif_branches": elif_branches,
        "else": else_branch,
    }


def build_elif_node(elif_node, source: bytes, known_functions: set) -> dict:
    condition_node = elif_node.child_by_field_name("condition")
    if condition_node is None:
        condition_node = _condition_by_position(elif_node)
    condition = classify_condition(condition_node, source, known_functions) if condition_node else None
    body_nodes = [
        c for c in elif_node.named_children
        if c != condition_node and c.type != "comment"
    ]
    return {"condition": condition, "then": build_body(body_nodes, source, known_functions)}


# ---------------------------------------------------------------------------
# Project-level orchestration
# ---------------------------------------------------------------------------

def analyze_project(file_paths) -> dict:
    parser = get_parser()
    parsed = {}       # filename -> (root, source_bytes)
    all_functions = {}  # name -> {"file":..., "node":..., "source":...}

    for path in file_paths:
        source_code = path.read_text(encoding="utf-8")
        source_bytes = source_code.encode("utf-8")
        tree = parser.parse(source_bytes)
        root = tree.root_node
        parsed[path.name] = (root, source_bytes)

        for name, node in discover_functions(root, source_bytes).items():
            all_functions[name] = {"file": path.name, "node": node, "source": source_bytes}

    known_function_names = set(all_functions.keys())

    functions_out = {}
    for name, info in all_functions.items():
        body_node = info["node"].child_by_field_name("body")
        body_children = list(body_node.named_children) if body_node else []
        result = build_body(body_children, info["source"], known_function_names)
        functions_out[name] = {"defined_in": info["file"], **result}

    files_out = {}
    for filename, (root, source_bytes) in parsed.items():
        files_out[filename] = {
            "sources": discover_sources(root, source_bytes),
            "decision_trees": find_top_level_ifs(root, source_bytes, known_function_names),
        }

    return {"files": files_out, "functions": functions_out}


def main():
    ap = argparse.ArgumentParser(
        description="Analyze a bash project: extract if/else decision trees and "
                     "link function calls across files (via `source`)."
    )
    ap.add_argument("paths", nargs="+", type=Path,
                     help="A directory of .sh files, or a list of .sh files")
    ap.add_argument("-o", "--output", type=Path, default=None)
    ap.add_argument("--clean", action="store_true",
                     help="Output the simplified yes/no decision tree (function-call "
                          "actions inlined) instead of the detailed linked JSON.")
    args = ap.parse_args()

    file_paths = []
    for p in args.paths:
        if p.is_dir():
            file_paths.extend(sorted(p.glob("*.sh")))
        else:
            file_paths.append(p)

    if not file_paths:
        print("No .sh files found.", file=sys.stderr)
        sys.exit(1)

    result = analyze_project(file_paths)

    if args.clean:
        from simplify import simplify_project
        result = simplify_project(result)

    output_json = json.dumps(result, indent=2, ensure_ascii=False)

    if args.output:
        args.output.write_text(output_json, encoding="utf-8")
        print(f"Wrote {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
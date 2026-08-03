"""
extractor.py
------------
Parses bash scripts with tree-sitter-bash and extracts if/elif/else
structures into a JSON-serializable "decision tree".

Install dependencies first:
    pip install tree-sitter tree-sitter-bash

Usage:
    python extractor.py script.sh
    python extractor.py script.sh -o output.json
"""

import argparse
import json
import sys
from pathlib import Path

from tree_sitter import Language, Parser
import tree_sitter_bash as tsbash


def get_parser() -> Parser:
    """Build a tree-sitter Parser configured with the bash grammar."""
    bash_language = Language(tsbash.language())
    return Parser(bash_language)


def node_text(node, source: bytes) -> str:
    """Return the raw source text covered by a node, decoded and trimmed."""
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace").strip()


def extract_statements(nodes, source: bytes):
    """
    Given a list of sibling statement nodes (the body of a then/elif/else
    branch), split them into:
      - "commands": flat text of non-branching statements (leaves)
      - "nested_ifs": any if_statement nodes found directly in this body,
        recursively converted into decision-tree nodes.
    Other compound statements (for/while/case/function) are also walked so
    that if-statements nested inside them are not missed.
    """
    commands = []
    nested_ifs = []

    for node in nodes:
        if node.type == "if_statement":
            nested_ifs.append(build_if_node(node, source))
        elif node.type in (
            "for_statement", "while_statement", "c_style_for_statement",
            "case_statement", "function_definition", "subshell",
            "compound_statement", "do_group",
        ):
            # Descend into these to catch if-statements nested inside them,
            # without treating the wrapper itself as a leaf command.
            inner_ifs = find_if_statements(node, source)
            nested_ifs.extend(inner_ifs)
            commands.append(node_text(node, source))
        else:
            text = node_text(node, source)
            if text:
                commands.append(text)

    return commands, nested_ifs


def find_if_statements(node, source: bytes):
    """Recursively find if_statement nodes anywhere under `node`
    (used to look inside for/while/case/function bodies)."""
    found = []
    for child in node.named_children:
        if child.type == "if_statement":
            found.append(build_if_node(child, source))
        else:
            found.extend(find_if_statements(child, source))
    return found


def build_if_node(if_node, source: bytes) -> dict:
    """
    Convert a single tree-sitter if_statement node into a decision-tree
    dict of the shape:

    {
      "condition": "...",
      "then": {"commands": [...], "nested_ifs": [...]},
      "elif_branches": [
         {"condition": "...", "then": {"commands": [...], "nested_ifs": [...]}}
      ],
      "else": {"commands": [...], "nested_ifs": [...]} | null,
      "line": 12
    }
    """
    condition_text = None
    then_body_nodes = []
    elif_branches = []
    else_branch = None

    children = if_node.children
    i = 0
    n = len(children)

    # First named child after 'if' keyword up to 'then' keyword is the condition.
    # We walk tokens in order: 'if' <condition...> 'then' <body...> [elif_clause]* [else_clause]? 'fi'
    idx = 0
    # skip the 'if' keyword
    while idx < n and children[idx].type != "if":
        idx += 1
    idx += 1  # move past 'if'

    condition_nodes = []
    while idx < n and children[idx].type != "then":
        if children[idx].is_named:
            condition_nodes.append(children[idx])
        idx += 1
    if condition_nodes:
        # condition may span one node (e.g. a test_command) - join text of all
        start = condition_nodes[0].start_byte
        end = condition_nodes[-1].end_byte
        condition_text = source[start:end].decode("utf-8", errors="replace").strip()
    idx += 1  # move past 'then'

    while idx < n and children[idx].type not in ("elif_clause", "else_clause", "fi"):
        if children[idx].is_named:
            then_body_nodes.append(children[idx])
        idx += 1

    while idx < n and children[idx].type in ("elif_clause", "else_clause"):
        clause = children[idx]
        if clause.type == "elif_clause":
            elif_branches.append(build_elif_node(clause, source))
        elif clause.type == "else_clause":
            else_body_nodes = [c for c in clause.named_children if c.type != "comment"]
            commands, nested_ifs = extract_statements(else_body_nodes, source)
            else_branch = {"commands": commands, "nested_ifs": nested_ifs}
        idx += 1

    then_commands, then_nested = extract_statements(then_body_nodes, source)

    return {
        "condition": condition_text,
        "line": if_node.start_point[0] + 1,
        "then": {"commands": then_commands, "nested_ifs": then_nested},
        "elif_branches": elif_branches,
        "else": else_branch,
    }


def build_elif_node(elif_node, source: bytes) -> dict:
    """elif_clause children: 'elif' <condition> 'then' <body...>"""
    children = elif_node.children
    n = len(children)
    idx = 0
    while idx < n and children[idx].type != "elif":
        idx += 1
    idx += 1

    condition_nodes = []
    while idx < n and children[idx].type != "then":
        if children[idx].is_named:
            condition_nodes.append(children[idx])
        idx += 1
    condition_text = None
    if condition_nodes:
        start = condition_nodes[0].start_byte
        end = condition_nodes[-1].end_byte
        condition_text = source[start:end].decode("utf-8", errors="replace").strip()
    idx += 1  # past 'then'

    body_nodes = []
    while idx < n:
        if children[idx].is_named:
            body_nodes.append(children[idx])
        idx += 1

    commands, nested_ifs = extract_statements(body_nodes, source)
    return {
        "condition": condition_text,
        "then": {"commands": commands, "nested_ifs": nested_ifs},
    }


def extract_decision_trees(source_code: str) -> list:
    """Parse bash source and return a list of top-level decision trees
    (one per top-level if_statement; nested ones are embedded inside)."""
    parser = get_parser()
    source_bytes = source_code.encode("utf-8")
    tree = parser.parse(source_bytes)
    root = tree.root_node

    top_level_ifs = find_if_statements(root, source_bytes)
    return top_level_ifs


def main():
    ap = argparse.ArgumentParser(description="Extract if/else decision trees from a bash script.")
    ap.add_argument("script", type=Path, help="Path to the .sh file to analyze")
    ap.add_argument("-o", "--output", type=Path, default=None, help="Write JSON to this file instead of stdout")
    args = ap.parse_args()

    source_code = args.script.read_text(encoding="utf-8")
    trees = extract_decision_trees(source_code)

    result = {
        "source_file": str(args.script),
        "if_statement_count": len(trees),
        "decision_trees": trees,
    }

    output_json = json.dumps(result, indent=2, ensure_ascii=False)

    if args.output:
        args.output.write_text(output_json, encoding="utf-8")
        print(f"Wrote decision tree JSON to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
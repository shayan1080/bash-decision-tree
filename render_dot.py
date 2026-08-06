"""
render_dot.py
--------------
Converts the clean decision-tree JSON (from `project_analyzer.py --clean`)
into Graphviz DOT format. The resulting .dot files can be visualized with:

    dot -Tpng decision_tree.dot -o decision_tree.png
    dot -Tsvg decision_tree.dot -o decision_tree.svg
    circo -Tpng decision_tree.dot -o decision_tree.png  # for circular layout
    neato -Tpng decision_tree.dot -o decision_tree.png  # for spring layout

Usage:
    python project_analyzer.py my_scripts --clean -o clean.json
    python render_dot.py clean.json -o tree_dots/

Or in one step (using run_all.py):
    python run_all.py
"""

import argparse
import json
import sys
from pathlib import Path


class DotBuilder:
    def __init__(self, detailed=False):
        self.lines = [
            'digraph decision_tree {',
            'rankdir=TB;',
            'node [shape=box, style=rounded, fontname="Segoe UI"];',
            'edge [fontname="Segoe UI"];',
        ]
        self.node_id = 0
        self.detailed = detailed

    def fresh_id(self):
        nid = self.node_id
        self.node_id += 1
        return nid

    def esc(self, s):
        """Escape text for DOT format."""
        if s is None:
            return ""
        return (s or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

    def add_node(self, nid, label, shape="box", color=None):
        """Add a node to the graph."""
        label_safe = self.esc(label)
        color_attr = f', color="{color}"' if color else ""
        self.lines.append(f'n{nid} [label="{label_safe}"{color_attr}];')

    def add_edge(self, from_id, to_id, label=""):
        """Add an edge to the graph."""
        label_safe = self.esc(label)
        if label:
            self.lines.append(f'n{from_id} -> n{to_id} [label="{label_safe}"];')
        else:
            self.lines.append(f'n{from_id} -> n{to_id};')

    def visit(self, node):
        """Recursively visit and build DOT for a node. Returns its node ID."""
        if node is None:
            nid = self.fresh_id()
            self.add_node(nid, "(none)", color="#cccccc")
            return nid

        if isinstance(node, str):
            nid = self.fresh_id()
            self.add_node(nid, node, shape="box", color="#e8f4f8")
            return nid

        if isinstance(node, list):
            nid = self.fresh_id()
            label = " / ".join(str(v) for v in node)
            self.add_node(nid, label, color="#e8f4f8")
            return nid

        # A case_statement node
        if "branches" in node:
            return self._visit_case(node)

        # An if_statement node
        if "condition" in node:
            return self._visit_if(node)

        # A function call or other dict
        if "function" in node:
            nid = self.fresh_id()
            label = f'{node["function"]}()\n{node.get("defined_in", "")}'
            self.add_node(nid, label, color="#c8e6c9")
            if "before" in node:
                for action in node["before"]:
                    action_id = self.visit(action)
                    self.add_edge(nid, action_id, "before")
            if "actions" in node:
                for action in node["actions"]:
                    action_id = self.visit(action)
                    self.add_edge(nid, action_id)
            return nid

        # Fallback
        nid = self.fresh_id()
        self.add_node(nid, str(node))
        return nid

    def _visit_if(self, node):
        """Visit an if_statement node."""
        nid = self.fresh_id()
        condition = node.get("condition") or "?"
        label = f"if {condition}"
        self.add_node(nid, label, color="#e3f2fd")

        # Condition detail (if present and detailed mode)
        if self.detailed and "condition_detail" in node:
            detail = node["condition_detail"]
            detail_id = self.visit(detail)
            self.add_edge(nid, detail_id, "detail")

        # Yes branch
        yes_node = node.get("yes")
        yes_id = self.visit(yes_node)
        self.add_edge(nid, yes_id, "yes")

        # No branch
        no_node = node.get("no")
        no_id = self.visit(no_node)
        self.add_edge(nid, no_id, "no")

        return nid

    def _visit_case(self, node):
        """Visit a case_statement node."""
        nid = self.fresh_id()
        case_value = node.get("case_value") or "?"
        label = f"case {case_value}"
        self.add_node(nid, label, color="#fff3e0")

        # Value detail (if present and detailed mode)
        if self.detailed and "value_detail" in node:
            detail = node["value_detail"]
            detail_id = self.visit(detail)
            self.add_edge(nid, detail_id, "detail")

        # Case branches
        for branch in node.get("branches", []):
            pattern = branch.get("pattern", "?")
            then_node = branch.get("then")
            then_id = self.visit(then_node)
            self.add_edge(nid, then_id, pattern)

        return nid

    def build(self):
        """Finalize the DOT graph and return as string."""
        self.lines.append("}")
        return "\n".join(self.lines)


def render_dot(tree_json, detailed=False):
    """Convert a single decision-tree JSON to DOT format."""
    builder = DotBuilder(detailed=detailed)
    builder.visit(tree_json)
    return builder.build()


def main():
    ap = argparse.ArgumentParser(
        description="Render clean decision-tree JSON as Graphviz DOT diagrams."
    )
    ap.add_argument("input", type=Path, help="Path to clean JSON (project_analyzer.py --clean output)")
    ap.add_argument("-o", "--outdir", type=Path, default=Path("tree_dots"))
    ap.add_argument("--detailed", action="store_true", help="Include condition_detail/value_detail edges")
    args = ap.parse_args()

    data = json.loads(args.input.read_text(encoding="utf-8"))
    args.outdir.mkdir(parents=True, exist_ok=True)

    count = 0
    for filename, trees in data.items():
        for i, tree in enumerate(trees):
            dot = render_dot(tree, detailed=args.detailed)
            out_path = args.outdir / f"{Path(filename).stem}_{i + 1}.dot"
            out_path.write_text(dot, encoding="utf-8")
            print(f"Wrote {out_path}", file=sys.stderr)
            count += 1

    if count == 0:
        print("No decision trees found in input JSON.", file=sys.stderr)


if __name__ == "__main__":
    main()
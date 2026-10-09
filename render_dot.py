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
    def __init__(self, detailed=True, show_before=False, max_depth=None):
        self.lines = [
            'digraph decision_tree {',
            'rankdir=TB;',
            'node [shape=box, style=rounded, fontname="Segoe UI"];',
            'edge [fontname="Segoe UI"];',
        ]
        self.node_id = 0
        self.detailed = detailed
        self.show_before = show_before
        self.max_depth = max_depth
        self._seen = {}  # canonical JSON string of a subtree -> node id already built for it
        self._body_cache = {}  # (function, defined_in, actions tuple) -> node id of the
                                # shared function-body node, reused across every call site
                                # so a widely-used helper (e.g. a logging function) isn't
                                # redrawn from scratch each time it's called.

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

    def visit(self, node, depth=0):
        """Recursively visit and build DOT for a node. Returns its node ID.
        depth=0 is the root -- always shown in full, regardless of max_depth.

        Dedup: if an IDENTICAL subtree (same JSON content) was already
        rendered at the same depth, its existing node id is reused
        instead of rebuilding a full duplicate copy -- this is what
        keeps the DOT file a sane size even though simplify.py's JSON
        deliberately embeds the same "continuation" into every case
        branch / guard-clause path rather than linking it once."""
        if self.max_depth is not None and depth > self.max_depth:
            nid = self.fresh_id()
            self.add_node(nid, "...", color="#dddddd")
            return nid

        try:
            key = (depth, json.dumps(node, sort_keys=True))
        except TypeError:
            key = None
        if key is not None and key in self._seen:
            return self._seen[key]

        nid = self._visit_uncached(node, depth)
        if key is not None:
            self._seen[key] = nid
        return nid

    def _visit_uncached(self, node, depth=0):
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
            return self._visit_case(node, depth)

        # An if_statement node
        if "condition" in node:
            return self._visit_if(node, depth)

        # A function call or other dict
        if "function" in node:
            # The function's own body (its actions) is identical at every
            # call site, so it CAN be shared -- but only when nothing
            # site-specific hangs off it. If this call has a "then"
            # (a continuation that belongs only to THIS call site),
            # reusing a shared body node would attach every call site's
            # "then" to the same node, making the diagram falsely show
            # the function branching to all of them at once. So the
            # cache is only consulted/populated for calls with no
            # "then" -- the common case for a helper like a logger that
            # is simply the last thing on its path -- and any call that
            # does have a "then" is rendered fresh, kept separate from
            # every other call site.
            body_key = (
                node["function"],
                node.get("defined_in"),
                tuple(node.get("actions", [])) if isinstance(node.get("actions"), list) else None,
                tuple(node.get("before", [])) if isinstance(node.get("before"), list) else None,
                node.get("call_text"),
            )
            has_then = node.get("then") is not None

            if not has_then and body_key in self._body_cache:
                return self._body_cache[body_key]

            nid = self.fresh_id()
            label_lines = [f'{node["function"]}()', node.get("defined_in", "")]
            # "call_text" is what was actually invoked at THIS call site
            # (e.g. `log_error "cannot deploy"`) - the callee's own body
            # below is generic/shared, so without this the real argument
            # passed at this call site would be invisible.
            if node.get("call_text"):
                label_lines.append("called as: " + node["call_text"])
            # "before" on a function node is real sequential code that
            # ran right before this call in the same body (e.g. another
            # call chained via "then" one level up) - unlike the
            # optional lead-in on a bare if/case condition, this is
            # essential control flow, so it's always shown regardless
            # of show_before.
            if node.get("before"):
                label_lines.append("before: " + "; ".join(str(b) for b in node["before"]))
            self.add_node(nid, "\n".join(label_lines), color="#c8e6c9")
            if "actions" in node:
                for action in node["actions"]:
                    action_id = self.visit(action, depth + 1)
                    self.add_edge(nid, action_id)

            if not has_then:
                self._body_cache[body_key] = nid
            else:
                then_id = self.visit(node["then"], depth + 1)
                self.add_edge(nid, then_id)

            return nid

        # Fallback
        nid = self.fresh_id()
        self.add_node(nid, str(node))
        return nid

    def _visit_if(self, node, depth=0):
        """Visit an if_statement node (which may also be a resolved function
        call carrying function/defined_in/before, e.g. run_deploy())."""
        nid = self.fresh_id()
        condition = node.get("condition") or "?"
        label_lines = [f"if {condition}"]
        if "function" in node:
            label_lines.append(f'{node["function"]}() - {node.get("defined_in", "")}')
        if self.show_before and node.get("before"):
            label_lines.append("before: " + "; ".join(str(b) for b in node["before"]))
        self.add_node(nid, "\n".join(label_lines), color="#e3f2fd")

        # Condition detail (if present and detailed mode)
        if self.detailed and "condition_detail" in node:
            detail = node["condition_detail"]
            detail_id = self.visit(detail, depth + 1)
            self.add_edge(nid, detail_id, "detail")

        # Yes branch
        yes_node = node.get("yes")
        yes_id = self.visit(yes_node, depth + 1)
        self.add_edge(nid, yes_id, "yes")

        # No branch
        no_node = node.get("no")
        no_id = self.visit(no_node, depth + 1)
        self.add_edge(nid, no_id, "no")

        return nid

    def _visit_case(self, node, depth=0):
        """Visit a case_statement node."""
        nid = self.fresh_id()
        case_value = node.get("case_value") or "?"
        label_lines = [f"case {case_value}"]
        if self.show_before and node.get("before"):
            label_lines.append("before: " + "; ".join(str(b) for b in node["before"]))
        self.add_node(nid, "\n".join(label_lines), color="#fff3e0")

        # Value detail (if present and detailed mode)
        if self.detailed and "value_detail" in node:
            detail = node["value_detail"]
            detail_id = self.visit(detail, depth + 1)
            self.add_edge(nid, detail_id, "detail")

        # Case branches
        for branch in node.get("branches", []):
            pattern = branch.get("pattern", "?")
            then_node = branch.get("then")
            then_id = self.visit(then_node, depth + 1)
            self.add_edge(nid, then_id, pattern)

        return nid

    def build(self):
        """Finalize the DOT graph and return as string."""
        self.lines.append("}")
        return "\n".join(self.lines)


def render_dot(tree_json, detailed=True, show_before=False, max_depth=None):
    """Convert a single decision-tree JSON to DOT format."""
    builder = DotBuilder(detailed=detailed, show_before=show_before, max_depth=max_depth)
    builder.visit(tree_json)
    return builder.build()


def main():
    ap = argparse.ArgumentParser(
        description="Render clean decision-tree JSON as Graphviz DOT diagrams."
    )
    ap.add_argument("input", type=Path, help="Path to clean JSON (project_analyzer.py --clean output)")
    ap.add_argument("-o", "--outdir", type=Path, default=Path("tree_dots"))
    ap.add_argument("--simple", action="store_true",
                     help="Omit condition_detail/value_detail edges (shown by default)")
    ap.add_argument("--show-before", action="store_true",
                     help="Show 'before' actions inside the owning node's label (hidden by default)")
    ap.add_argument("--depth", type=int, default=None,
                     help="Only show nodes up to this many levels below the root (root itself is "
                          "always shown in full); deeper branches are collapsed into a '...' node. "
                          "Unlimited by default.")
    args = ap.parse_args()

    data = json.loads(args.input.read_text(encoding="utf-8"))
    args.outdir.mkdir(parents=True, exist_ok=True)

    count = 0
    for filename, trees in data.items():
        for i, tree in enumerate(trees):
            dot = render_dot(tree, detailed=not args.simple, show_before=args.show_before,
                              max_depth=args.depth)
            out_path = args.outdir / f"{Path(filename).stem}_{i + 1}.dot"
            out_path.write_text(dot, encoding="utf-8")
            print(f"Wrote {out_path}", file=sys.stderr)
            count += 1

    if count == 0:
        print("No decision trees found in input JSON.", file=sys.stderr)


if __name__ == "__main__":
    main()
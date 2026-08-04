"""
render_tree.py
---------------
Renders the clean decision-tree JSON (from `project_analyzer.py --clean`,
or `simplify_tree.py`) as SVG diagrams -- one file per top-level
if-statement per bash file. Pure Python, no extra dependencies (unlike
tree-sitter, this step doesn't need internet access to install anything).

Usage:
    python project_analyzer.py my_scripts --clean -o clean.json
    python render_tree.py clean.json -o tree_svgs/

Each .svg file can be opened directly in a browser, or dragged into most
image viewers / editors / docs.
"""

import argparse
import json
import sys
from pathlib import Path

# ---- layout constants (all in SVG user units / px) ----
BOX_W_MIN = 160
BOX_H1 = 44   # single-line box (no subtitle)
BOX_H2 = 60   # two-line box (title + subtitle)
ROW_GAP = 90  # vertical distance between row tops
H_GAP = 40    # horizontal gap between sibling boxes
CHAR_W_TITLE = 7.2   # px/char at 13px sans-serif
CHAR_W_SUB = 6.0     # px/char at 11px sans-serif
DETAIL_MAX_CHARS = 45  # keep condition_detail summaries short so boxes stay compact

COLORS = {
    # kind: (fill, stroke, text)
    "decision": ("#E6F1FB", "#185FA5", "#0C447C"),  # blue  - a plain if condition
    "call":     ("#E1F5EE", "#0F6E56", "#085041"),  # teal  - condition/action that's a resolved function call
    "leaf":     ("#F1EFE8", "#5F5E5A", "#2C2C2A"),  # gray  - terminal outcome
}


def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def text_width(s, char_w):
    return len(s or "") * char_w


class Box:
    def __init__(self, title, subtitle=None, kind="leaf"):
        self.title = title
        self.subtitle = subtitle
        self.kind = kind
        self.w = max(
            BOX_W_MIN,
            text_width(title, CHAR_W_TITLE) + 28,
            text_width(subtitle or "", CHAR_W_SUB) + 28,
        )
        self.h = BOX_H2 if subtitle else BOX_H1


class TreeNode:
    def __init__(self, box):
        self.box = box
        self.children = []  # list of (edge_label, TreeNode)
        self.x = 0.0
        self.y = 0


def leaf_text(value):
    if value is None:
        return "(none)"
    if isinstance(value, list):
        return " / ".join(str(v) for v in value)
    return str(value)


def summarize_detail(detail):
    """Flatten a condition_detail sub-tree (or leaf, or no-branch function
    call) into one short line, so it can ride along in a node's subtitle
    instead of needing its own layout slot."""
    if detail is None:
        return None
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        return " / ".join(str(v) for v in detail)
    if "condition" in detail:
        yes, no = detail.get("yes"), detail.get("no")
        yes_s = yes if isinstance(yes, str) else ("..." if yes else "-")
        no_s = no if isinstance(no, str) else ("..." if no else "-")
        return f'{detail.get("condition")} -> {yes_s} / {no_s}'
    if "actions" in detail:
        return "; ".join(leaf_text(a) for a in detail["actions"]) or f'{detail.get("function", "")}()'
    return str(detail)


def build_tree(node):
    if not isinstance(node, dict):
        return TreeNode(Box(leaf_text(node), kind="leaf"))

    # A function with no internal branching: {"function":..., "actions":[...]}
    if "actions" in node and "condition" not in node:
        fn = node.get("function")
        title = f"{fn}()" if fn else "..."
        subtitle = "; ".join(leaf_text(a) for a in node["actions"]) or node.get("defined_in")
        return TreeNode(Box(title, subtitle, kind="call"))

    # A decision node: {"condition":..., "yes":..., "no":..., [function, defined_in, condition_detail]}
    is_call = "function" in node
    title = node.get("condition") or "?"
    subtitle = None
    if is_call:
        subtitle = f'{node["function"]}() - {node.get("defined_in", "")}'
    detail_summary = summarize_detail(node.get("condition_detail"))
    if detail_summary:
        if len(detail_summary) > DETAIL_MAX_CHARS:
            detail_summary = detail_summary[: DETAIL_MAX_CHARS - 3] + "..."
        piece = f"detail: {detail_summary}"
        subtitle = f"{subtitle}  |  {piece}" if subtitle else piece

    box = Box(title, subtitle, kind="call" if is_call else "decision")
    tn = TreeNode(box)
    tn.children.append(("no", build_tree(node.get("no"))))
    tn.children.append(("yes", build_tree(node.get("yes"))))
    return tn


def assign_positions(node, depth, next_x):
    node.y = depth
    if not node.children:
        node.x = next_x[0] + node.box.w / 2
        next_x[0] += node.box.w + H_GAP
        return node.x

    xs = [assign_positions(child, depth + 1, next_x) for _, child in node.children]
    node.x = sum(xs) / len(xs)
    return node.x


def _max_depth(node):
    if not node.children:
        return node.y
    return max(_max_depth(c) for _, c in node.children)


def _center_y(node):
    return 40 + node.y * ROW_GAP + node.box.h / 2


def _draw(node, elems):
    box = node.box
    cx, cy = node.x, _center_y(node)
    x, y = cx - box.w / 2, cy - box.h / 2
    fill, stroke, text_color = COLORS.get(box.kind, COLORS["leaf"])

    elems.append(
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{box.w:.1f}" height="{box.h:.1f}" '
        f'rx="8" fill="{fill}" stroke="{stroke}" stroke-width="1"/>'
    )
    if box.subtitle:
        elems.append(
            f'<text x="{cx:.1f}" y="{y + box.h / 2 - 9:.1f}" text-anchor="middle" '
            f'dominant-baseline="central" font-size="13" font-weight="600" '
            f'fill="{text_color}">{esc(box.title)}</text>'
        )
        elems.append(
            f'<text x="{cx:.1f}" y="{y + box.h / 2 + 11:.1f}" text-anchor="middle" '
            f'dominant-baseline="central" font-size="11" '
            f'fill="{text_color}">{esc(box.subtitle)}</text>'
        )
    else:
        elems.append(
            f'<text x="{cx:.1f}" y="{cy:.1f}" text-anchor="middle" '
            f'dominant-baseline="central" font-size="13" font-weight="600" '
            f'fill="{text_color}">{esc(box.title)}</text>'
        )

    for label, child in node.children:
        ccx, ccy = child.x, _center_y(child)
        c_top = ccy - child.box.h / 2
        by = y + box.h
        mid_y = (by + c_top) / 2
        path = f"M{cx:.1f},{by:.1f} L{cx:.1f},{mid_y:.1f} L{ccx:.1f},{mid_y:.1f} L{ccx:.1f},{c_top:.1f}"
        elems.append(
            f'<path d="{path}" fill="none" stroke="#888780" stroke-width="1.2" '
            f'marker-end="url(#arrow)"/>'
        )
        lx, ly = (cx + ccx) / 2, mid_y - 6
        elems.append(
            f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle" '
            f'font-size="11" fill="#5F5E5A">{esc(label)}</text>'
        )
        _draw(child, elems)


def render_svg(tree_json):
    root = build_tree(tree_json)
    next_x = [40]
    assign_positions(root, 0, next_x)
    total_w = next_x[0] + 40
    total_h = _max_depth(root) * ROW_GAP + BOX_H2 + 80

    elems = [
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" '
        'markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
        '<path d="M2 1L8 5L2 9" fill="none" stroke="#5F5E5A" stroke-width="1.5" '
        'stroke-linecap="round" stroke-linejoin="round"/></marker></defs>'
    ]
    _draw(root, elems)

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total_w:.0f} {total_h:.0f}" '
        f'width="{total_w:.0f}" height="{total_h:.0f}" font-family="Segoe UI, Tahoma, sans-serif">'
        f'<rect x="0" y="0" width="{total_w:.0f}" height="{total_h:.0f}" fill="#ffffff"/>'
        + "".join(elems) +
        "</svg>"
    )


def main():
    ap = argparse.ArgumentParser(description="Render clean decision-tree JSON as SVG diagrams.")
    ap.add_argument("input", type=Path, help="Path to clean JSON (project_analyzer.py --clean output)")
    ap.add_argument("-o", "--outdir", type=Path, default=Path("tree_svgs"))
    args = ap.parse_args()

    data = json.loads(args.input.read_text(encoding="utf-8"))
    args.outdir.mkdir(parents=True, exist_ok=True)

    count = 0
    for filename, trees in data.items():
        for i, tree in enumerate(trees):
            svg = render_svg(tree)
            out_path = args.outdir / f"{Path(filename).stem}_{i + 1}.svg"
            out_path.write_text(svg, encoding="utf-8")
            print(f"Wrote {out_path}", file=sys.stderr)
            count += 1

    if count == 0:
        print("No decision trees found in input JSON.", file=sys.stderr)


if __name__ == "__main__":
    main()
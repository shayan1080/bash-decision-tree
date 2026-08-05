"""
render_tree.py
---------------
Renders the clean decision-tree JSON (from `project_analyzer.py --clean`,
or `simplify_tree.py`) as SVG diagrams -- one file per top-level
if-statement per bash file. Pure Python, no extra dependencies.

Usage:
    python project_analyzer.py my_scripts --clean -o clean.json
    python render_tree.py clean.json -o tree_svgs/

A `condition_detail` (the internal branching of a function used as a
condition, e.g. check_network()'s own ping test) is drawn as its own
dashed sub-tree, anchored directly above the node it belongs to and
connected by a short dashed leader line. This is done recursively, so a
detail whose OWN condition is again a function call (detail-within-detail)
is also drawn in full -- nothing gets flattened into text.
"""

import argparse
import json
import sys
from pathlib import Path

# ---- layout constants (all in SVG user units / px) ----
BOX_W_MIN = 160
BOX_H1 = 44    # single-line box (no subtitle)
BOX_H2 = 60    # two-line box (title + subtitle)
ROW_GAP = 90   # vertical distance between row tops
H_GAP = 40     # horizontal gap between sibling boxes
LANE_GAP = 50  # vertical gap between a detail sub-tree and the node it explains
CHAR_W_TITLE = 7.2   # px/char at 13px sans-serif
CHAR_W_SUB = 6.0     # px/char at 11px sans-serif
MARGIN = 40

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
    def __init__(self, title, subtitle=None, kind="leaf", dashed=False):
        self.title = title
        self.subtitle = subtitle
        self.kind = kind
        self.dashed = dashed
        self.w = max(
            BOX_W_MIN,
            text_width(title, CHAR_W_TITLE) + 28,
            text_width(subtitle or "", CHAR_W_SUB) + 28,
        )
        self.h = BOX_H2 if subtitle else BOX_H1


class TreeNode:
    def __init__(self, box):
        self.box = box
        self.children = []   # list of (edge_label, TreeNode) -- normal yes/no flow
        self.detail = None   # TreeNode | None -- condition_detail sub-tree, drawn separately
        self.x = 0.0          # local x from assign_positions
        self.y = 0             # local depth from assign_positions
        self.subtree_w = 0.0   # reserved width for this node's whole subtree
        self.cx = 0.0          # final absolute canvas x
        self.cy = 0.0          # final absolute canvas y


def leaf_text(value):
    if value is None:
        return "(none)"
    if isinstance(value, list):
        return " / ".join(str(v) for v in value)
    return str(value)


DETAIL_MAX_CHARS = 45  # keep folded (2nd-level+) detail summaries short


def _summarize(detail):
    """Flatten a condition_detail (or leaf, or no-branch function call)
    into one short line. Used only for a detail-of-a-detail, which is
    folded into subtitle text instead of being drawn as its own
    sub-tree (see build_tree) -- stacking two upward-growing subtrees
    would otherwise collide."""
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


def build_tree(node, dashed=False, in_detail=False):
    if not isinstance(node, dict):
        return TreeNode(Box(leaf_text(node), kind="leaf", dashed=dashed))

    # A function with no internal branching: {"function":..., "actions":[...]}
    if "actions" in node and "condition" not in node:
        fn = node.get("function")
        title = f"{fn}()" if fn else "..."
        subtitle = "; ".join(leaf_text(a) for a in node["actions"]) or node.get("defined_in")
        return TreeNode(Box(title, subtitle, kind="call", dashed=dashed))

    # A decision node: {"condition":..., "yes":..., "no":..., [function, defined_in, condition_detail, before]}
    is_call = "function" in node
    title = node.get("condition") or "?"
    subtitle_parts = []
    if is_call:
        subtitle_parts.append(f'{node["function"]}() - {node.get("defined_in", "")}')
    before = node.get("before")
    if before:
        subtitle_parts.append("before: " + "; ".join(leaf_text(b) for b in before))
    subtitle = "  |  ".join(subtitle_parts) if subtitle_parts else None

    detail = node.get("condition_detail")
    nested_detail_tree = None
    if detail is not None:
        if not in_detail:
            # First level of detail: draw it as a real sub-tree.
            nested_detail_tree = build_tree(detail, dashed=True, in_detail=True)
        else:
            # A detail-of-a-detail: fold into subtitle text instead of
            # drawing a second stacked upward-growing sub-tree.
            summary = _summarize(detail)
            if summary:
                if len(summary) > DETAIL_MAX_CHARS:
                    summary = summary[: DETAIL_MAX_CHARS - 3] + "..."
                piece = f"detail: {summary}"
                subtitle = f"{subtitle}  |  {piece}" if subtitle else piece

    box = Box(title, subtitle, kind="call" if is_call else "decision", dashed=dashed)
    tn = TreeNode(box)
    tn.children.append(("no", build_tree(node.get("no"), dashed, in_detail)))
    tn.children.append(("yes", build_tree(node.get("yes"), dashed, in_detail)))
    tn.detail = nested_detail_tree
    return tn


def assign_depth(node, depth):
    node.y = depth
    for _, child in node.children:
        assign_depth(child, depth + 1)


def compute_subtree_width(node):
    """Bottom-up: each node reserves max(its own box width, the combined
    width of its children). This is what a simple leaf-slot layout
    misses -- a wide internal node (e.g. one with a long 'before:'
    subtitle) can otherwise overlap a neighboring sibling's slot."""
    if not node.children:
        node.subtree_w = node.box.w
    else:
        child_widths = [compute_subtree_width(c) for _, c in node.children]
        children_total = sum(child_widths) + H_GAP * (len(child_widths) - 1)
        node.subtree_w = max(node.box.w, children_total)
    return node.subtree_w


def place_x(node, left_edge):
    """Top-down: positions node.x from the widths computed above,
    centering a node's children block within whichever is wider -- the
    node's own box, or the children's combined width."""
    if not node.children:
        node.x = left_edge + node.subtree_w / 2
        return

    children_total = sum(c.subtree_w for _, c in node.children) + H_GAP * (len(node.children) - 1)
    start = left_edge + (node.subtree_w - children_total) / 2
    cursor = start
    for _, child in node.children:
        place_x(child, cursor)
        cursor += child.subtree_w + H_GAP
    node.x = left_edge + node.subtree_w / 2


def assign_positions(node, left_edge=0.0):
    """Full local layout for one tree (main tree, or a detail sub-tree
    laid out independently): depth + subtree-width-aware x positions."""
    assign_depth(node, 0)
    compute_subtree_width(node)
    place_x(node, left_edge)


def _max_depth(node):
    if not node.children:
        return node.y
    return max(_max_depth(c) for _, c in node.children)


def finalize_coords(node, y_of_local, x_shift):
    """Sets node.cx / node.cy (absolute canvas coords) for every node in
    the main tree, given a function mapping (local_y, box_height) -> canvas_y."""
    node.cx = node.x + x_shift
    node.cy = y_of_local(node.y, node.box.h)
    for _, child in node.children:
        finalize_coords(child, y_of_local, x_shift)


def _finalize_flipped(node, anchor_y, x_shift):
    """Positions a detail sub-tree growing UPWARD from anchor_y (the top
    edge of the node it explains, minus a gap): the detail's root sits
    just above anchor_y, and deeper detail nodes go further up."""
    node.cx = node.x + x_shift
    node.cy = anchor_y - node.y * ROW_GAP - node.box.h / 2
    for _, child in node.children:
        _finalize_flipped(child, anchor_y, x_shift)


def place_details(node):
    """Once node.cx/node.cy are set, position its condition_detail (if any)
    anchored just above it, then recurse -- both into the normal yes/no
    children AND into the detail sub-tree itself, so a detail whose own
    condition is again a function call gets its detail placed too."""
    if node.detail is not None:
        d = node.detail
        assign_positions(d, 0.0)
        anchor_y = node.cy - node.box.h / 2 - LANE_GAP
        _finalize_flipped(d, anchor_y, x_shift=node.cx - d.x)
        place_details(d)
    for _, child in node.children:
        place_details(child)


def _walk_all(node, fn):
    fn(node)
    for _, child in node.children:
        _walk_all(child, fn)
    if node.detail is not None:
        _walk_all(node.detail, fn)


def _bbox(root):
    box = {"lo_x": root.cx, "hi_x": root.cx, "lo_y": root.cy, "hi_y": root.cy}

    def collect(n):
        box["lo_x"] = min(box["lo_x"], n.cx - n.box.w / 2)
        box["hi_x"] = max(box["hi_x"], n.cx + n.box.w / 2)
        box["lo_y"] = min(box["lo_y"], n.cy - n.box.h / 2)
        box["hi_y"] = max(box["hi_y"], n.cy + n.box.h / 2)

    _walk_all(root, collect)
    return box["lo_x"], box["hi_x"], box["lo_y"], box["hi_y"]


def _shift_all(root, dx, dy):
    def s(n):
        n.cx += dx
        n.cy += dy

    _walk_all(root, s)


def _connect(elems, parent, child, label, dashed=False):
    """Elbow connector between two positioned nodes. Works whether the
    child is below the parent (normal flow) or above it (a detail
    sub-tree, laid out growing upward)."""
    if child.cy >= parent.cy:
        py = parent.cy + parent.box.h / 2
        cy_edge = child.cy - child.box.h / 2
    else:
        py = parent.cy - parent.box.h / 2
        cy_edge = child.cy + child.box.h / 2
    mid_y = (py + cy_edge) / 2
    dash = ' stroke-dasharray="4 3"' if dashed else ""
    path = f"M{parent.cx:.1f},{py:.1f} L{parent.cx:.1f},{mid_y:.1f} L{child.cx:.1f},{mid_y:.1f} L{child.cx:.1f},{cy_edge:.1f}"
    elems.append(f'<path d="{path}" fill="none" stroke="#888780" stroke-width="1.2"{dash} marker-end="url(#arrow)"/>')
    if label:
        lx, ly = (parent.cx + child.cx) / 2, mid_y - 6
        elems.append(f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle" font-size="11" fill="#5F5E5A">{esc(label)}</text>')


def _draw_box(node, elems):
    box = node.box
    cx, cy = node.cx, node.cy
    x, y = cx - box.w / 2, cy - box.h / 2
    fill, stroke, text_color = COLORS.get(box.kind, COLORS["leaf"])
    dash = ' stroke-dasharray="5 4"' if box.dashed else ""

    elems.append(
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{box.w:.1f}" height="{box.h:.1f}" '
        f'rx="8" fill="{fill}" stroke="{stroke}" stroke-width="1"{dash}/>'
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


def _draw(node, elems):
    _draw_box(node, elems)
    for label, child in node.children:
        _connect(elems, node, child, label, dashed=False)
        _draw(child, elems)
    if node.detail is not None:
        _connect(elems, node, node.detail, "detail", dashed=True)
        _draw(node.detail, elems)


def render_svg(tree_json):
    root = build_tree(tree_json)

    assign_positions(root, MARGIN)
    main_max_depth = _max_depth(root)

    finalize_coords(root, lambda ly, bh: MARGIN + ly * ROW_GAP + bh / 2, x_shift=0.0)
    place_details(root)  # positions every condition_detail sub-tree, recursively; may go above y=0

    lo_x, hi_x, lo_y, hi_y = _bbox(root)
    dx = MARGIN - lo_x if lo_x < MARGIN else 0.0
    dy = MARGIN - lo_y if lo_y < MARGIN else 0.0
    if dx or dy:
        _shift_all(root, dx, dy)
        lo_x, hi_x, lo_y, hi_y = lo_x + dx, hi_x + dx, lo_y + dy, hi_y + dy

    total_w = hi_x + MARGIN
    total_h = max(hi_y + MARGIN, MARGIN + (main_max_depth + 1) * ROW_GAP)

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
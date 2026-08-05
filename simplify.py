"""
simplify.py
-----------
Pure post-processing: takes the detailed, linked analysis produced by
project_analyzer.py (a dict with "files" and "functions") and collapses
it into a clean yes/no decision tree per entry point, without losing any
of the underlying detail.

Key rule (this is the whole point of this module):
  - If a function call appears as a CONDITION (`if check_network; then`),
    its outer yes/no still drives the flow (that's what the caller
    actually branches on) - but the function's own internal logic is
    NOT thrown away. It's attached alongside as "condition_detail", so
    you can see exactly *why* check_network() returns true/false without
    it being merged into (and confused with) the outer then/else.
  - If a function call appears as an ACTION inside a branch (`install_packages`
    called as a statement, not tested), and that function itself branches,
    it IS expanded inline as the continuation of that branch - that's a
    real next step in the flow, not a side detail.

No tree-sitter dependency here - this only works on already-parsed JSON,
so it can be re-run on a saved output.json without touching bash at all.
"""

import re

_ECHO_RE = re.compile(r'^echo\s+["\'](.*)["\']\s*$')


def _clean_label(text: str) -> str:
    """Strip `echo "..."` down to just the message, for a readable leaf label.
    Anything else is left as-is (still the real command text)."""
    if text is None:
        return text
    m = _ECHO_RE.match(text.strip())
    return m.group(1) if m else text


def _expand_call(fname: str, functions: dict, visited: frozenset):
    if fname in visited:
        return f"{fname}()  [recursive - see functions.{fname} in the raw JSON]"

    func = functions.get(fname)
    if not func:
        return f"{fname}()  [not defined in the analyzed files]"

    if func.get("nested_ifs"):
        node = _simplify_sequence(func["nested_ifs"], functions, visited | {fname})
        node["function"] = fname
        node["defined_in"] = func.get("defined_in")
        return node

    labels = [_clean_label(a["text"]) for a in func.get("actions", [])]
    if not labels:
        return f"{fname}()"
    return {
        "function": fname,
        "defined_in": func.get("defined_in"),
        "actions": labels,
    }


def _simplify_sequence(nested_ifs: list, functions: dict, visited: frozenset) -> dict:
    """A body can contain more than one sibling if-statement in sequence
    (e.g. a guard clause followed by another check). If the first one has
    no else (so execution falls through when its condition is false),
    chain the next if onto its "no" branch instead of dropping it.
    This does not do full control-flow analysis (e.g. it won't notice a
    `return` inside the yes-branch) - it only handles the common
    guard-clause shape."""
    first, *rest = nested_ifs
    node = _simplify_if(first, functions, visited)
    if node.get("no") is None and rest:
        node["no"] = _simplify_sequence(rest, functions, visited)
    return node


def _simplify_branch(body, functions: dict, visited: frozenset):
    if body is None:
        return None

    actions = body.get("actions", [])
    nested_ifs = body.get("nested_ifs", [])
    leading = [_clean_label(a["text"]) for a in actions]  # any actions in this same body

    # Direct nested if/else statement(s) inside this branch -> that's the
    # continuation (chain them if there's more than one in sequence).
    # Any plain actions that came before it in the same body are kept as
    # "before" context on the resulting node.
    if nested_ifs:
        node = _simplify_sequence(nested_ifs, functions, visited)
        if leading and isinstance(node, dict):
            node["before"] = leading
        return node

    # The LAST action is a call to a function that itself branches ->
    # inline-expand it (e.g. `echo "..."; run_deploy`). Earlier actions in
    # the same branch are kept as "before" context on the expanded node.
    if actions and actions[-1]["type"] == "call":
        expanded = _expand_call(actions[-1]["function"], functions, visited)
        leading_before_call = leading[:-1]
        if leading_before_call:
            if isinstance(expanded, dict):
                expanded["before"] = leading_before_call
            elif isinstance(expanded, str):
                expanded = leading_before_call + [expanded]
            elif isinstance(expanded, list):
                expanded = leading_before_call + expanded
        return expanded

    # Otherwise: plain terminal leaf/leaves.
    if not leading:
        return None
    return leading[0] if len(leading) == 1 else leading


def _elif_chain_to_if(elif_branches, else_branch):
    """Fold [elif1, elif2, ...] + else into a synthetic nested if_node so
    an elif chain simplifies the same way as a plain if/else."""
    first, *rest = elif_branches
    return {
        "condition": first["condition"],
        "then": first["then"],
        "elif_branches": rest,
        "else": else_branch,
    }


def _simplify_if(if_node: dict, functions: dict, visited: frozenset) -> dict:
    condition = if_node.get("condition")
    node = {"condition": condition["text"] if condition else None}

    # If the condition itself is a call to a known function, don't throw
    # away its internal branching - attach it as a side-detail so nothing
    # is lost, while the outer yes/no keeps driving the actual flow.
    if condition and condition["type"] == "call":
        node["condition"] = f'{condition["text"]}()'
        node["condition_detail"] = _expand_call(condition["function"], functions, visited)

    node["yes"] = _simplify_branch(if_node.get("then"), functions, visited)

    elif_branches = if_node.get("elif_branches") or []
    else_branch = if_node.get("else")

    if elif_branches:
        synthetic = _elif_chain_to_if(elif_branches, else_branch)
        node["no"] = _simplify_if(synthetic, functions, visited)
    else:
        node["no"] = _simplify_branch(else_branch, functions, visited)

    return node


def simplify_project(analysis: dict) -> dict:
    """Top-level entry point. Returns {filename: [clean_tree, ...]} for
    every file that has at least one top-level if-statement."""
    functions = analysis.get("functions", {})
    out = {}
    for filename, info in analysis.get("files", {}).items():
        trees = info.get("decision_trees") or []
        if not trees:
            continue
        out[filename] = [_simplify_if(t, functions, frozenset()) for t in trees]
    return out
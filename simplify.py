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

import copy
import re

_ECHO_RE = re.compile(r'^echo\s+["\'](.*)["\']\s*$')
_TERMINATOR_RE = re.compile(r'^(return|exit)\b')


def _clean_label(text: str) -> str:
    """Strip `echo "..."` down to just the message, for a readable leaf label.
    Anything else is left as-is (still the real command text)."""
    if text is None:
        return text
    m = _ECHO_RE.match(text.strip())
    return m.group(1) if m else text


def _terminates(value) -> bool:
    """True if a branch's visible content ends with a return/exit
    statement, meaning execution doesn't fall through to whatever comes
    next - so no further continuation should be chained onto it.
    For a nested decision (if/case) or an expanded-call dict, whether
    EVERY path through it terminates isn't tracked, so we conservatively
    say no (better to over-attach a continuation than lose one)."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(_TERMINATOR_RE.match(value.strip()))
    if isinstance(value, list):
        return bool(value) and _terminates(value[-1])
    return False


def _expand_call(fname: str, functions: dict, visited: frozenset):
    if fname in visited:
        return f"{fname}()  [recursive - see functions.{fname} in the raw JSON]"

    func = functions.get(fname)
    if not func:
        return f"{fname}()  [not defined in the analyzed files]"

    if func.get("nested_ifs"):
        node = _simplify_sequence(func["nested_ifs"], functions, visited | {fname})
        leading = [_clean_label(a["text"]) for a in func.get("actions", [])]
        trailing = [_clean_label(a["text"]) for a in func.get("after_actions", [])]
        if leading:
            node["before"] = leading
        if trailing:
            node = _attach_trailing(node, trailing)
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


def _simplify_node(node: dict, functions: dict, visited: frozenset) -> dict:
    """Dispatches to the right simplifier based on node shape: a
    case_statement node has "branches", an if_statement node has
    "condition"."""
    if "branches" in node:
        return _simplify_case(node, functions, visited)
    return _simplify_if(node, functions, visited)


def _simplify_sequence(nested_decisions: list, functions: dict, visited: frozenset) -> dict:
    """A body can contain more than one sibling if/case decision in
    sequence (e.g. a guard clause followed by another check, or a
    validation `case` followed by the real logic). Chains the rest onto
    every branch that doesn't end in return/exit (see _terminates) -
    if with no else -> its "no"; case_statement -> every branch; an
    explicit else/branch that doesn't terminate also gets it, since
    execution really does continue past it. This still isn't full
    control-flow analysis (e.g. an early return buried inside a nested
    if two levels down within a branch won't be noticed) - just the
    common shapes."""
    first, *rest = nested_decisions
    node = _simplify_node(first, functions, visited)
    if not rest:
        return node

    continuation = _simplify_sequence(rest, functions, visited)
    if "branches" in node:
        for b in node["branches"]:
            if not _terminates(b["then"]):
                b["then"] = _append_continuation(b["then"], copy.deepcopy(continuation))
    else:
        if not _terminates(node.get("yes")):
            node["yes"] = _append_continuation(node.get("yes"), copy.deepcopy(continuation))
        if not _terminates(node.get("no")):
            node["no"] = _append_continuation(node.get("no"), continuation)
    return node


def _append_continuation(existing, continuation):
    """Appends "whatever runs next" onto the end of an already-simplified
    branch value. Handles the common shapes (empty branch, plain leaf
    text) cleanly; if the branch is itself a further decision (nested
    if/case), the continuation can't be cleanly spliced into all of ITS
    leaves without deeper recursion, so it's left as-is in that case
    (documented limitation). `continuation` is always a value this call
    owns exclusively (deep-copied by the caller when reused across
    branches), so mutating/embedding it directly here is safe."""
    if existing is None:
        return continuation
    if isinstance(existing, (str, list)):
        existing_list = existing if isinstance(existing, list) else [existing]
        if isinstance(continuation, dict):
            continuation["before"] = existing_list + continuation.get("before", [])
            return continuation
        if isinstance(continuation, list):
            return existing_list + continuation
        return existing_list + [continuation]
    return existing


def _attach_trailing(node, trailing: list):
    """Best-effort: append trailing actions (that came after all the
    nested ifs/cases in a body) onto every leaf that doesn't already
    terminate with return/exit - every case branch, or the yes/no of an
    if/elif chain. Still not full control-flow analysis (a return buried
    two levels deep inside a branch won't be noticed), but a branch whose
    OWN last visible action is return/exit is now correctly left alone."""
    if not trailing or _terminates(node):
        return node
    if isinstance(node, dict) and "branches" in node:
        for b in node["branches"]:
            b["then"] = _attach_trailing(b["then"], trailing)
        return node
    if isinstance(node, dict) and "condition" in node:
        node["yes"] = _attach_trailing(node.get("yes"), trailing)
        node["no"] = _attach_trailing(node.get("no"), trailing)
        return node
    return _append_continuation(node, trailing)


def _simplify_branch(body, functions: dict, visited: frozenset):
    if body is None:
        return None

    actions = body.get("actions", [])
    nested_ifs = body.get("nested_ifs", [])
    after_actions = body.get("after_actions", [])
    leading = [_clean_label(a["text"]) for a in actions]
    trailing = [_clean_label(a["text"]) for a in after_actions]

    # Direct nested if/else statement(s) inside this branch -> that's the
    # continuation (chain them if there's more than one in sequence).
    # Any plain actions that came before it in the same body are kept as
    # "before" context; anything that came after is chained on as the
    # natural fallthrough (e.g. a guard-clause chain ending in `return 0`).
    if nested_ifs:
        node = _simplify_sequence(nested_ifs, functions, visited)
        if leading and isinstance(node, dict):
            node["before"] = leading
        if trailing:
            node = _attach_trailing(node, trailing)
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


def _simplify_case(node: dict, functions: dict, visited: frozenset) -> dict:
    value = node.get("case_value")
    is_call = bool(value) and value["type"] == "call"
    negated_prefix = ""
    if is_call and value["text"].lstrip().startswith("!"):
        negated_prefix = "! "
    result = {
        "case_value": (f'{negated_prefix}{value["function"]}()' if is_call else (value["text"] if value else None)),
        "branches": [
            {"pattern": b["pattern"], "then": _simplify_branch(b.get("then"), functions, visited)}
            for b in node.get("branches", [])
        ],
    }
    if "line" in node:
        result["line"] = node["line"]
    if value and value["type"] == "call":
        result["value_detail"] = _expand_call(value["function"], functions, visited)
    return result


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
    if "line" in if_node:
        node["line"] = if_node["line"]

    # If the condition itself is a call to a known function, don't throw
    # away its internal branching - attach it as a side-detail so nothing
    # is lost, while the outer yes/no keeps driving the actual flow.
    if condition and condition["type"] == "call":
        negated = condition["text"].lstrip().startswith("!")
        prefix = "! " if negated else ""
        node["condition"] = f'{prefix}{condition["function"]}()'
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
        out[filename] = [_simplify_node(t, functions, frozenset()) for t in trees]
    return out
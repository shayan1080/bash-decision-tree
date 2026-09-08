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


_RETURN_RE = re.compile(r"^\s*return\b")
_EXIT_RE = re.compile(r"^\s*exit\b")


def _terminates(value, respect_return=True):
    if value is None:
        return False

    if isinstance(value, str):
        text = value.strip()

        if _EXIT_RE.match(text):
            return True

        if respect_return and _RETURN_RE.match(text):
            return True

        return False

    if isinstance(value, list):
        return bool(value) and _terminates(
            value[-1],
            respect_return=respect_return
        )

    return False


_expand_cache = {}


def _expand_call(fname: str, functions: dict, visited: frozenset):
    key = (fname, visited)

    if key in _expand_cache:
        return copy.deepcopy(_expand_cache[key])

    if fname in visited:
        result = (
            f"{fname}()  "
            f"[recursive - see functions.{fname} in the raw JSON]"
        )

        _expand_cache[key] = copy.deepcopy(result)
        return copy.deepcopy(result)

    func = functions.get(fname)

    if not func:
        result = (
            f"{fname}()  "
            f"[not defined in the analyzed files]"
        )

        _expand_cache[key] = copy.deepcopy(result)
        return copy.deepcopy(result)

    if func.get("nested_ifs"):
        node = _simplify_sequence(
            func["nested_ifs"],
            functions,
            visited | {fname}
        )

        leading = [
            _clean_label(a["text"])
            for a in func.get("actions", [])
        ]

        trailing = [
            _clean_label(a["text"])
            for a in func.get("after_actions", [])
        ]

        if leading:
            node["before"] = leading

        if trailing:
            node = _attach_trailing(
                node,
                trailing
            )

        node["function"] = fname
        node["defined_in"] = func.get("defined_in")

        _expand_cache[key] = copy.deepcopy(node)
        return copy.deepcopy(node)

    labels = [
        _clean_label(a["text"])
        for a in func.get("actions", [])
    ]

    if not labels:
        result = f"{fname}()"

        _expand_cache[key] = copy.deepcopy(result)
        return copy.deepcopy(result)

    result = {
        "function": fname,
        "defined_in": func.get("defined_in"),
        "actions": labels,
    }

    _expand_cache[key] = copy.deepcopy(result)
    return copy.deepcopy(result)


def _simplify_node(node: dict, functions: dict, visited: frozenset) -> dict:
    """Dispatches to the right simplifier based on node shape: a
    case_statement node has "branches", an if_statement node has
    "condition"."""
    if "branches" in node:
        return _simplify_case(node, functions, visited)
    return _simplify_if(node, functions, visited)


def _simplify_sequence(
    nested_decisions: list,
    functions: dict,
    visited: frozenset
) -> dict:
    """
    Simplify a sequence of sibling decisions while preserving
    normal fall-through control flow.

    Any continuation after a decision is attached to every path
    that does not terminate with return/exit.
    """
    first, *rest = nested_decisions

    node = _simplify_node(
        first,
        functions,
        visited
    )

    if not rest:
        return node

    continuation = _simplify_sequence(
        rest,
        functions,
        visited
    )

    return _append_to_fallthrough(
        node,
        continuation
    )


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

def _append_to_fallthrough(node, continuation, respect_return=True):
    """
    Append continuation to every path that can naturally fall through.

    If respect_return=True, `return` is treated as a terminator.
    This is correct for normal control flow inside the current scope.

    If respect_return=False, `return` inside an expanded function call
    is treated as returning control to the caller, so the continuation
    must still be attached after it.
    """
    if node is None:
        return continuation

    if isinstance(node, (str, list)):
        if respect_return and _terminates(node):
            return node

        return _append_continuation(
            node,
            continuation
        )

    if isinstance(node, dict):

        # case statement
        if "branches" in node:
            for branch in node["branches"]:
                branch["then"] = _append_to_fallthrough(
                    branch.get("then"),
                    copy.deepcopy(continuation),
                    respect_return=respect_return
                )

            return node

        # if statement
        if "condition" in node:
            node["yes"] = _append_to_fallthrough(
                node.get("yes"),
                copy.deepcopy(continuation),
                respect_return=respect_return
            )

            node["no"] = _append_to_fallthrough(
                node.get("no"),
                copy.deepcopy(continuation),
                respect_return=respect_return
            )

            return node

    return node


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

    leading = [
        _clean_label(a["text"])
        for a in actions
    ]

    trailing = [
        _clean_label(a["text"])
        for a in after_actions
    ]

    # ---------------------------------------------------------
    # First handle nested decisions.
    # ---------------------------------------------------------
    if nested_ifs:
        node = _simplify_sequence(
            nested_ifs,
            functions,
            visited
        )

        if leading and isinstance(node, dict):
            node["before"] = leading

        if trailing:
            node = _attach_trailing(
                node,
                trailing
            )

        return node

    # ---------------------------------------------------------
    # No nested decisions.
    #
    # Process actions from left to right.
    # ---------------------------------------------------------
    if not actions:
        return None

    result = None

    for action in actions:
        if action["type"] == "call":
            expanded = _expand_call(
                action["function"],
                functions,
                visited
            )

            if result is None:
                result = expanded
            else:
                result = _append_to_fallthrough(
                    result,
                    expanded
                )

        else:
            label = _clean_label(
                action["text"]
            )

            if result is None:
                result = label
            else:
               result = _append_to_fallthrough(result,[label],respect_return=False)
    # ---------------------------------------------------------
    # Actions after nested/normal actions.
    # ---------------------------------------------------------
    if trailing:
        result = _append_to_fallthrough(
            result,
            trailing
        )

    return result


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

    before_actions = node.get("before_actions") or []

    if before_actions:
        result["before"] = [_clean_label(a["text"]) for a in before_actions]
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

    node = {
        "condition": condition["text"] if condition else None
    }

    if "line" in if_node:
        node["line"] = if_node["line"]

    if condition and condition["type"] == "call":
        negated = condition["text"].lstrip().startswith("!")
        prefix = "! " if negated else ""

        node["condition"] = f'{prefix}{condition["function"]}()'

        node["condition_detail"] = _expand_call(
            condition["function"],
            functions,
            visited
        )

    node["yes"] = _simplify_branch(
        if_node.get("then"),
        functions,
        visited
    )

    elif_branches = if_node.get("elif_branches") or []
    else_branch = if_node.get("else")

    if elif_branches:
        synthetic = _elif_chain_to_if(
            elif_branches,
            else_branch
        )

        node["no"] = _simplify_if(
            synthetic,
            functions,
            visited
        )
    else:
        node["no"] = _simplify_branch(
            else_branch,
            functions,
            visited
        )

    # Actions that occur after this decision must execute on every
    # non-terminating path.
    after_actions = if_node.get("after_actions") or []

    if after_actions:
        trailing = [
            _clean_label(a["text"])
            for a in after_actions
        ]

        node["yes"] = _append_to_fallthrough(
            node["yes"],
            trailing
        )

        node["no"] = _append_to_fallthrough(
            node["no"],
            trailing
        )

    # Actions that happened before this decision belong to the decision
    # itself, rather than being treated as a third execution branch.
    before_actions = if_node.get("before_actions") or []

    if before_actions:
        node["before"] = [
            _clean_label(a["text"])
            for a in before_actions
        ]

    return node


_RETURN_RE = re.compile(r"^\s*return\s+(\d+)\s*$")


def _leaf_truth(value):
    """For a terminal leaf (str, list of str, or None), determine if it
    resolves to True (return 0), False (return N != 0), or None
    (ambiguous -- no explicit numeric return here)."""
    if isinstance(value, list):
        value = value[-1] if value else None
    if not isinstance(value, str):
        return None
    m = _RETURN_RE.match(value.strip())
    if m:
        return int(m.group(1)) == 0
    return None


_MAX_FLATTEN_DEPTH = 6


def _try_flatten(detail, outer_yes, outer_no, negated=False, _depth=0):
    """Recursively walks a condition_detail sub-tree, replacing every
    leaf that resolves to true/false with the outer yes/no content.
    Returns (flattened_tree, all_resolved) -- all_resolved is False if
    any leaf was ambiguous, in which case the caller keeps the original
    node (with its condition_detail side-branch) unchanged rather than
    asserting something we're not sure of. Cascades through nested
    condition_detail-of-a-detail levels too, as far as they stay
    unambiguous -- capped at _MAX_FLATTEN_DEPTH as a safety net so a
    pathological chain of details can't blow up recursion/copy cost."""
    if _depth > _MAX_FLATTEN_DEPTH:
        return detail, False

    ambiguous = [False]

    def walk(d):
        if isinstance(d, dict):
            if "branches" in d:
                return {**d, "branches": [{**b, "then": walk(b.get("then"))} for b in d["branches"]]}
            if "condition" in d:
                new_d = dict(d)
                new_d["yes"] = walk(d.get("yes"))
                new_d["no"] = walk(d.get("no"))
                inner_detail = new_d.get("condition_detail")
                if inner_detail is not None:
                    inner_negated = new_d.get("condition", "").lstrip().startswith("!")
                    inner_flat, inner_ok = _try_flatten(inner_detail,new_d["yes"],new_d["no"],negated=inner_negated,
                    _depth=_depth + 1)
                    if inner_ok:
                        new_d = inner_flat
                return new_d
            ambiguous[0] = True
            return d
        truth = _leaf_truth(d)

        if truth is True:
            return copy.deepcopy(outer_no if negated else outer_yes)

        if truth is False:
            return copy.deepcopy(outer_yes if negated else outer_no)

        ambiguous[0] = True
        return d

    flattened = walk(detail)
    return flattened, not ambiguous[0]


def _flatten_node(node):
    """Recursively applies the flattening across a whole simplified tree:
    wherever a node has a condition_detail (or a case has a value_detail)
    that resolves unambiguously via explicit return codes, the detail
    side-branch is folded directly into the tree (replacing the node),
    so the final tree only ever has yes/no or case branches -- no
    separate "detail" branch left over. Ambiguous cases keep their
    original condition_detail, unchanged, as a safe fallback."""
    if not isinstance(node, dict):
        return node

    if "branches" in node:
        node["branches"] = [
            {**b, "then": _flatten_node(b.get("then"))}
            for b in node["branches"]
        ]
        return node

    if "condition" in node:
        node["yes"] = _flatten_node(node.get("yes"))
        node["no"] = _flatten_node(node.get("no"))

        detail = node.get("condition_detail")
        if detail is not None:
            negated = node.get("condition", "").lstrip().startswith("!")
            flattened, all_resolved = _try_flatten(detail,node["yes"],node["no"],negated=negated)
            if all_resolved:
                if "before" in node and isinstance(flattened, dict):
                    flattened["before"] = node["before"] + flattened.get("before", [])
                return flattened
        return node

    return node


def simplify_project(analysis: dict) -> dict:
    """Top-level entry point. Returns {filename: [clean_tree, ...]} for
    every file that has at least one top-level if-statement. Trees are
    flattened as a final pass: wherever a condition_detail resolves
    unambiguously (explicit return 0 / return N), it's folded directly
    into the tree instead of kept as a side "detail" branch, so the
    result is a pure yes/no (or case-branch) tree wherever possible."""
    _expand_cache.clear()
    functions = analysis.get("functions", {})
    out = {}
    for filename, info in analysis.get("files", {}).items():
        trees = info.get("decision_trees") or []
        if not trees:
            continue
        out[filename] = [_flatten_node(_simplify_node(t, functions, frozenset())) for t in trees]
    return out
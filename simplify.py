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

        trailing = _simplify_action_sequence(
            func.get("after_actions", []),
            functions,
            visited | {fname}
        )

        if leading:
            node["before"] = leading

        if trailing:
            node = _append_to_fallthrough(
                node,
                trailing
            )

        node["function"] = fname
        node["defined_in"] = func.get("defined_in")

        _expand_cache[key] = copy.deepcopy(node)
        return copy.deepcopy(node)

    labels = _simplify_action_sequence(
        func.get("actions", []),
        functions,
        visited | {fname}
    )

    if labels is None:
        result = f"{fname}()"

        _expand_cache[key] = copy.deepcopy(result)
        return copy.deepcopy(result)

    if isinstance(labels, dict):
        # The body's own content is already a nested call (or a
        # decision) with its OWN function/defined_in identity - don't
        # stomp on it by tagging it as fname. Instead wrap fname as its
        # own (empty-bodied) leaf that leads straight into it, the same
        # way a decision node points at whatever follows it.
        result = {
            "function": fname,
            "defined_in": func.get("defined_in"),
            "actions": [],
            "then": labels,
        }
    else:
        result = {
            "function": fname,
            "defined_in": func.get("defined_in"),
            "actions": labels if isinstance(labels, list) else [labels],
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
    must still be attached after it. `exit` is always a terminator
    regardless of respect_return, since it ends the whole shell process,
    not just the current function's scope.
    """
    # Work on a private copy: `continuation` may be the SAME object the
    # caller is about to attach to more than one path (e.g. both the
    # "yes" and "no" of a decision, or multiple case branches). Every
    # path below either returns `continuation` directly or mutates a
    # dict in place (see _append_continuation's "before" merge) - without
    # this, two branches that both received the same object would end
    # up silently sharing (and corrupting) each other's content.
    continuation = copy.deepcopy(continuation)

    if node is None:
        return continuation

    if isinstance(node, (str, list)):
        if _terminates(node, respect_return=respect_return):
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

        # A plain action-list leaf (an expanded function call with no
        # nested_ifs, e.g. {"function":..., "actions":[...]}). This
        # shape has no branches/condition to recurse into, so the
        # continuation belongs right after it - but it must NOT be
        # merged into "actions": that field is the function's own body
        # and is shared (cached) across every call site of this
        # function, while the continuation is specific to THIS call
        # site. Mixing them would both misrepresent the function's own
        # logic (the caller's next steps would look like part of the
        # callee) and defeat node de-duplication when rendering (the
        # same shared helper, e.g. a logging function, gets expanded
        # fresh at every call site instead of being reused), so it's
        # kept in a separate "then" field instead.
        if "actions" in node:
            if _terminates(node["actions"], respect_return=respect_return):
                return node
            node = dict(node)
            node["then"] = _append_to_fallthrough(
                node.get("then"),
                continuation,
                respect_return=respect_return
            )
            return node

    return node


def _simplify_action_sequence(actions: list, functions: dict, visited: frozenset):
    """Process a flat list of actions (no nested_ifs) left to right,
    expanding every "call" action via _expand_call (never just its raw
    text) and chaining everything together with _append_to_fallthrough.
    Shared by _simplify_branch (a decision branch's body) and
    _expand_call (a function's own body when it has no nested_ifs of
    its own) - a function call must always be expanded the same way
    regardless of which of the two contexts it's found in."""
    result = None

    for action in actions:
        if action["type"] == "call":
            expanded = _expand_call(
                action["function"],
                functions,
                visited
            )

            # _expand_call only knows the CALLEE's own generic body (it's
            # cached by function name, shared across every call site), so
            # it has no way to show what was actually passed at THIS call
            # site (e.g. `log_error "cannot deploy"` vs `log_error
            # "disk full"`). Record the real call text here, once per
            # call site, so that information isn't silently dropped.
            call_text = _clean_label(action.get("text", action["function"]))
            if isinstance(expanded, dict) and call_text != f'{action["function"]}':
                expanded = dict(expanded)
                expanded["call_text"] = call_text

            if result is None:
                result = expanded
            else:
                result = _append_to_fallthrough(
                    result,
                    expanded,
                    respect_return=False
                )

        else:
            label = _clean_label(
                action["text"]
            )

            if result is None:
                result = label
            else:
                result = _append_to_fallthrough(result, [label], respect_return=False)

    return result


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

    trailing = _simplify_action_sequence(after_actions, functions, visited)

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
            node = _append_to_fallthrough(
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

    result = _simplify_action_sequence(actions, functions, visited)
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
        trailing = _simplify_action_sequence(after_actions, functions, visited)

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


_RETURN_VALUE_RE = re.compile(r"^\s*return\s+(\d+)\s*$")


def _leaf_truth(value):
    """For a terminal leaf, determine if it resolves to True (return 0),
    False (return N != 0), or None (ambiguous -- no explicit numeric
    return here). Handles three shapes:

    - str / list of str: the plain case, checked directly.
    - dict (a call chain, e.g. {"function":"log_error", "actions":[...],
      "then": [...]}): a helper call before the branch's own return
      (e.g. `log_error; echo "DB DOWN"; return 1`) is extremely common,
      so this recurses into "then" to find the truth value, rather than
      giving up and marking the whole thing ambiguous just because the
      immediate value isn't a plain str/list.

    Returns (truth, lead): `lead` is whatever ran before the `return`,
    so callers can keep it instead of throwing it away. For the
    str/list case `lead` is a list of the preceding actions; for the
    dict case `lead` is the dict itself (with its own "then" reduced to
    whatever preceded the return), since a call node can't be flattened
    into a plain list without losing its own identity."""
    if isinstance(value, dict):
        if "then" not in value:
            return None, None
        truth, inner_lead = _leaf_truth(value["then"])
        if truth is None:
            return None, None
        new_value = dict(value)
        if inner_lead:
            new_value["then"] = inner_lead
        else:
            new_value.pop("then", None)
        return truth, new_value

    if isinstance(value, list):
        if not value:
            return None, None
        last = value[-1]
        lead = value[:-1]
    else:
        last = value
        lead = []
    if not isinstance(last, str):
        return None, None
    m = _RETURN_VALUE_RE.match(last.strip())
    if m:
        return int(m.group(1)) == 0, lead
    return None, None


def _dead_ends_in_exit(value):
    """True if this leaf's last visible statement is `exit N` (through
    any depth of dict "then" chaining). A path that ends in `exit` never
    returns control to its caller at all, so - unlike a genuinely
    unresolvable leaf (e.g. relying on the implicit exit status of a
    plain command) - it shouldn't count as "we don't know this
    function's truth value". It simply isn't a data point: if every
    OTHER path a function can take agrees on a truth value, that's the
    function's truth value, regardless of how many of its paths exit
    instead of returning."""
    if isinstance(value, dict):
        if "then" not in value:
            return False
        return _dead_ends_in_exit(value["then"])
    if isinstance(value, list):
        value = value[-1] if value else None
    if not isinstance(value, str):
        return False
    return bool(_EXIT_RE.match(value.strip()))


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
            # Any other dict shape falls through to _leaf_truth below,
            # which knows how to pull a truth value out of a call-leaf
            # dict (e.g. {"function":"log_error", "then":[...]}) by
            # looking inside its "then" chain instead of giving up.
        truth, lead = _leaf_truth(d)

        if truth is None:
            # A path that dead-ends in `exit` never returns at all, so
            # it isn't evidence of ambiguity - it's simply excluded from
            # the vote. Leave it exactly as-is (nothing to attach a
            # continuation to) without blocking the OTHER paths from
            # resolving.
            if _dead_ends_in_exit(d):
                return d
            ambiguous[0] = True
            return d

        target = copy.deepcopy(outer_no if negated else outer_yes) if truth \
            else copy.deepcopy(outer_yes if negated else outer_no)

        # Actions that ran before the `return` inside the inner function
        # are real, visible behavior (e.g. "DB OK") - keep them, spliced
        # in right before the outer continuation they lead into. Only the
        # `return N` itself was consumed to resolve the truth value.
        if isinstance(lead, dict):
            # A call chain (e.g. log_error(); "DB DOWN"; return 1) - use
            # _append_to_fallthrough so `target` is spliced onto the
            # actual tail of the chain (inside "then"), not tacked onto
            # the call node itself.
            return _append_to_fallthrough(lead, target, respect_return=False)
        if lead:
            return _append_continuation(list(lead), target)
        return target

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
            # Flatten the detail sub-tree on its own first, independent
            # of whether THIS level resolves. Otherwise, if the outer
            # function (e.g. one with no explicit `return`, relying on
            # the implicit exit status of its last command) can't be
            # resolved, everything nested inside it - even fully
            # independent, resolvable calls several levels down - would
            # be thrown away along with it and left as raw, un-flattened
            # "detail" branches.
            detail = _flatten_node(detail)
            node["condition_detail"] = detail

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
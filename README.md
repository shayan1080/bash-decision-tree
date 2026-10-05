# Bash Decision Tree Extractor

Static analysis tool that parses a multi-file Bash project with
[tree-sitter-bash](https://github.com/tree-sitter/tree-sitter-bash),
resolves `if`/`elif`/`case` control flow across function-call
boundaries, and renders the result as a Graphviz decision tree.

Unlike a plain AST dump, the tool follows function calls used as
conditions (e.g. `if check_database; then ...`) and — wherever the
called function's own return value can be determined statically —
inlines that function's internal logic directly into the branch that
called it, instead of leaving a separate, opaque "see elsewhere" edge.

```bash
check_database() {
    if [ "$status" = "up" ]; then
        echo "DB OK"; return 0
    else
        echo "DB DOWN"; return 1
    fi
}

if check_database; then
    echo "Deploy"
else
    echo "Rollback"
fi
```

is rendered as a single, flat decision — `$status = up` directly
drives `Deploy` / `Rollback` — rather than two disconnected nodes
joined by a generic "detail" edge.

## Table of contents

- [Pipeline overview](#pipeline-overview)
- [Requirements](#requirements)
- [Project files](#project-files)
- [Usage](#usage)
- [Output format](#output-format)
- [How the flattening works](#how-the-flattening-works)
- [Known limitations](#known-limitations)

## Pipeline overview

The tool is three independent stages, connected only through JSON on
disk. Each stage can be run — and tested — on its own.

```
 .sh source files
        │
        ▼
┌───────────────────┐
│ project_analyzer.py│   tree-sitter parse → raw per-function / per-file JSON
└───────────────────┘
        │  raw JSON  {"files": {...}, "functions": {...}}
        ▼
┌───────────────────┐
│    simplify.py      │   expands function calls, resolves return/exit
│  (library, no CLI)  │   semantics, inlines nested conditions
└───────────────────┘
        │  clean JSON  {filename: [decision_tree, ...]}
        ▼
┌───────────────────┐
│   render_dot.py     │   clean JSON → Graphviz DOT
└───────────────────┘
        │
        ▼
   dot -Tpng / -Tsvg → final diagram
```

`simplify.py` has no command-line entry point of its own; it is
imported directly by `project_analyzer.py` when the `--clean` flag is
passed. It never touches Bash or tree-sitter — it only transforms
already-parsed JSON — so it can be re-run or unit-tested on a saved
`output.json` without re-parsing anything.

## Requirements

- Python 3.9+
- [`tree-sitter`](https://pypi.org/project/tree-sitter/)
- [`tree-sitter-bash`](https://pypi.org/project/tree-sitter-bash/)
- [Graphviz](https://graphviz.org/download/) (`dot` executable) to
  render the `.dot` output to an image — not required to generate the
  `.dot` file itself

```bash
pip install tree-sitter tree-sitter-bash
```

## Project files

Only the files that take part in actually running the pipeline are
listed; everything else used during development (ad-hoc test scripts,
one-off JSON samples) is not part of the tool itself.

| File | Role |
|---|---|
| `project_analyzer.py` | Stage 1. Parses the project with tree-sitter and produces the raw JSON (`functions` + per-file `decision_trees`). Has the command-line entry point for the whole pipeline. |
| `simplify.py` | Stage 2. Expands function calls, resolves `return`/`exit` semantics, and inlines nested conditions. Imported by `project_analyzer.py --clean`; not run directly. |
| `render_dot.py` | Stage 3. Converts the clean JSON into Graphviz `.dot` files. Has its own command-line entry point. |

## Usage

### 1. Generate the clean decision tree JSON

```bash
python project_analyzer.py <path-to-project-or-.sh-files> --clean -o clean.json
```

- `<path-to-project-or-.sh-files>` — one or more arguments: a
  directory (searched recursively for `*.sh`) and/or individual `.sh`
  file paths.
- `--clean` — run the output through `simplify.py` (function-call
  expansion and flattening) instead of emitting the raw, unexpanded
  AST-level JSON.
- `-o / --output` — write to a file instead of stdout.

Omitting `--clean` produces the raw per-function / per-file JSON that
`simplify.py` itself consumes — useful for inspecting what
tree-sitter actually extracted before any flattening logic runs.

### 2. Render the decision tree(s) to Graphviz

```bash
python render_dot.py clean.json -o tree_dots/
```

One `.dot` file is written per top-level decision tree, named
`<source-file-stem>_<index>.dot`.

| Flag | Effect |
|---|---|
| `-o / --outdir` | Output directory (default: `tree_dots/`) |
| `--simple` | Omit `condition_detail` / `value_detail` edges (shown by default) |
| `--show-before` | Also show `before` context on `if`/`case` condition nodes (hidden by default; function-call nodes always show it, since there it's essential control flow rather than decorative lead-in) |
| `--depth N` | Collapse anything deeper than `N` levels below the root into a single `...` node |

### 3. Render the image

```bash
dot -Tpng tree_dots/myscript_1.dot -o myscript_1.png
dot -Tsvg tree_dots/myscript_1.dot -o myscript_1.svg
```

`circo` or `neato` can be used instead of `dot` for a circular or
spring layout.

## Output format

**Raw JSON** (`project_analyzer.py` without `--clean`):

```json
{
  "files": {
    "main.sh": {
      "sources": ["lib/checks.sh", "..."],
      "decision_trees": [ /* top-level if/case nodes, AST-faithful */ ]
    }
  },
  "functions": {
    "check_database": {
      "defined_in": "lib/checks.sh",
      "actions": [...],
      "nested_ifs": [...],
      "after_actions": [...]
    }
  }
}
```

**Clean JSON** (`--clean`): `{filename: [decision_tree, ...]}`, where
each decision tree is built from a small set of node shapes:

| Shape | Meaning |
|---|---|
| `{"condition", "yes", "no", "condition_detail"?}` | An `if` (or a folded function condition). `condition_detail` is only present when the condition's own internal logic could **not** be resolved statically. |
| `{"case_value", "branches", "value_detail"?}` | A `case` statement; `branches` is a list of `{"pattern", "then"}`. |
| `{"function", "defined_in", "actions", "before"?, "then"?, "call_text"?}` | An expanded function call. `actions` is the callee's own body; `then` is what runs next **at this specific call site** (never merged into `actions`, since the body is shared across call sites); `call_text` is the literal call as written (e.g. `log_error "disk full"`), since the generic body alone can't show which argument was passed. |
| string / list of strings | A plain leaf — one or more sequential statements with no further branching. |

## How the flattening works

1. **Expansion** (`_expand_call` in `simplify.py`): every function call
   is replaced by that function's own simplified body, recursively,
   with a cache so a given function is only analyzed once and a
   `visited` set to guard against (mutual) recursion.
2. **Truth resolution** (`_leaf_truth`): a branch's outcome is known
   when it ends in an explicit `return N` — `return 0` → true, any
   other value → false. This also looks inside a trailing function
   call (e.g. `log_error; return 1`) rather than giving up as soon as
   the last statement isn't a bare `return`.
3. **Exit is not ambiguity** (`_dead_ends_in_exit`): a path ending in
   `exit` never returns control to its caller at all, so it is
   excluded from the vote on the function's truth value rather than
   blocking resolution the way a genuinely unknown outcome would.
4. **Inlining** (`_flatten_node` / `_try_flatten`): if every path
   through a condition's `condition_detail` resolves (exits aside),
   the detail subtree replaces the condition outright, with the
   caller's own `yes`/`no` spliced onto each resolved leaf. If even
   one path is genuinely unresolvable, the condition is left
   untouched with its `condition_detail` attached, rather than
   guessing. This inlining is unbounded — it keeps following resolvable
   nested function conditions as deep as the project actually has them,
   with no artificial depth or size cap.

## Known limitations

- **No argument substitution.** A callee's body is shown generically
  (e.g. `echo "ERROR: $1"`); the actual argument text at a given call
  site is preserved separately as `call_text`, but it is not
  substituted into the body itself.
- **Only explicit numeric `return N` is resolved.** A bare `return`,
  `return $?`, or `return $SOME_VAR` remains unresolved, so the
  surrounding condition keeps its `condition_detail` rather than being
  inlined.
- **Output size grows with nested, resolvable conditions, with no cap.**
  Each inline duplicates its surroundings across the branches of what's
  being inlined, so the cost compounds with the depth of nested,
  resolvable function conditions — a project with several such levels
  stacked on one path, or many independently-resolvable decisions
  overall, can produce a very large clean JSON / `.dot` file. There is
  currently no depth or size limit guarding against this; if it
  becomes a problem in practice, `render_dot.py`'s `--depth` flag can
  still be used to limit how much of an already-generated tree gets
  drawn.
- **No general data-flow analysis.** Variable values are not tracked
  across statements or function boundaries beyond what's needed for
  `return`/`exit` resolution.

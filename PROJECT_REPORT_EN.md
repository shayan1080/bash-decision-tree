# Full Project Report: Extracting a Decision Tree from Bash Scripts with Tree-sitter

## 1. Project Overview

This project is a Python tool that uses **tree-sitter** (with the `tree-sitter-bash` grammar) to parse the Bash files in a project, extract the `if`/`elif`/`else` and `case` structures from them, and build a **decision tree** that:

- Detects function calls across different files (when file A `source`s file B and uses a function defined in it)
- Analyzes the whole project together instead of treating each file in isolation
- Produces a full, detailed JSON output (for programmatic analysis) and a simplified/clean output (for human reading)
- Can turn the decision tree into an image (SVG) or a Graphviz-compatible format (DOT)

The main goal: given a multi-file Bash project with nested functions, build an understandable, high-level view of the program's decision logic — something that's hard to get just by reading the code, but is easy to get from a structured diagram/JSON.

---

## 2. Overall Pipeline

The project is a 3-stage pipeline:

```
.sh files                    Full/raw JSON                  Clean, readable JSON        Image / graph
(bash scripts)   ──────►     (raw/detailed)     ──────►      (clean)          ──────►    (SVG or DOT)
              project_analyzer.py              simplify.py              render_tree.py /
                                                                          render_dot.py
```

### Stage 1 — `project_analyzer.py` (raw analysis)
Parses every `.sh` file in the project with tree-sitter. For each file:
- Finds every function it defines (regardless of which file ends up calling it — since in bash, `source` makes functions global)
- Tracks `source`/`.` statements (the file dependency graph)
- Converts every `if`/`case` (whether top-level, inside a function, or inside a loop) into a dictionary structure
- When a condition or an action is a call to a known function (even one defined in a different file), it's tagged with `"type": "call"` instead of being left as raw text

The output of this stage is complete and precise (nothing is lost), but it's verbose for a human to read directly.

### Stage 2 — `simplify.py` (simplification)
Takes the output of stage 1 and builds a clean **yes/no decision tree**:
- Every function call used as an **action** (not a condition) is expanded inline into the tree, since it's a genuine continuation of the flow
- Every function call used as a **condition** has its internals attached as `condition_detail`, right next to the main node (without merging into the main flow)
- An `elif` chain is turned into a nested `if` structure
- A `case` becomes a multi-branch node
- Actions before/after a decision (`before`) are preserved
- Detects when a branch ends in `return`/`exit` so nothing gets incorrectly chained onto it afterward

### Stage 3 — Visualization
Two independent paths:
- **`render_tree.py`**: builds an SVG file from the clean JSON (pure Python, no extra installs needed)
- **`render_dot.py`**: builds a `.dot` file (Graphviz format) from the clean JSON, which can be turned into an image with the `dot` command or an online Graphviz viewer

---

## 3. Installation and Usage

### Prerequisite
```bash
pip install tree-sitter tree-sitter-bash
```
(Only needed for stage 1. `simplify.py`, `render_tree.py`, and `render_dot.py` don't need tree-sitter at all, since they only work on JSON.)

### Main commands

**1. Full analysis (raw/detailed JSON):**
```bash
python project_analyzer.py my_project -o raw.json
```
`my_project` can be a directory (every `.sh` inside it, including subfolders, is found recursively) or a list of specific files:
```bash
python project_analyzer.py file1.sh file2.sh file3.sh -o raw.json
```

**2. Analyze + simplify in one step:**
```bash
python project_analyzer.py my_project --clean -o clean.json
```
(Equivalent to running `project_analyzer.py` without `--clean` and then feeding the result to `simplify_tree.py`.)

**3. Simplify separately (if you already have `raw.json`):**
```bash
python simplify_tree.py raw.json -o clean.json
```

**4. Generate an SVG image:**
```bash
python render_tree.py clean.json -o tree_svgs/
```
Each SVG file can be opened directly in a browser or any image viewer.

**5. Generate a DOT file (for Graphviz):**
```bash
python render_dot.py clean.json -o tree_dots/
dot -Tpng tree_dots/main_1.dot -o main_1.png   # if Graphviz is installed
```
If Graphviz isn't installed, you can paste the `.dot` file's content into [dreampuf.github.io/GraphvizOnline](https://dreampuf.github.io/GraphvizOnline).

**6. Run every sample test case in one command:**
```bash
python run_all.py
```
This runs every example under `examples/` end to end and writes `raw.json`, `clean.json`, and SVGs for each one under `results/<test_name>/`.

---

## 4. Project Files and Function-by-Function Explanation

### 📄 `project_analyzer.py` — the core analyzer

| Function | What it does |
|---|---|
| `get_parser()` | Builds and returns a `Parser` configured with the `tree-sitter-bash` grammar. |
| `node_text(node, source)` | Extracts a tree-sitter node's raw text from its `start_byte`/`end_byte`. |
| `discover_functions(root, source)` | Walks the whole tree (without crossing into another function's boundary) and builds a table of `function name → its definition node`. |
| `discover_sources(root, source)` | Finds `source file.sh` / `. file.sh` statements and returns the sourced filenames (the dependency graph). |
| `classify_command(node, source, known_functions)` | Takes a `command` node and determines: is it `source`? Is it a call to a known function (`type: call`)? Or just a plain command (`type: command`)? |
| `classify_condition(condition_node, source, known_functions)` | Classifies the condition of an `if`/`elif`/`case`. If the condition is a bare call to a function (even negated with `!`, like `if ! check_x; then`), it's marked `call`; otherwise it's kept as raw text (`raw`). |
| `build_case_node(case_node, source, known_functions)` | Converts a `case_statement` into `{"case_value":..., "branches":[...]}`. Every `case_item` (even ones with combined patterns like `a|b|c)`) becomes one branch. |
| `build_body(statement_nodes, source, known_functions)` | Processes the body of a `then`/`else`/`elif`/function. Its output is `{"actions": [...], "nested_ifs": [...], "after_actions": [...]}` — actions before the first decision, the nested decisions themselves (`if`/`case`), and actions after the last decision are kept separate. |
| `find_nested_ifs(node, source, known_functions)` | Searches inside a `for`/`while`/`subshell` for any `if`/`case` and returns them (without crossing into a function boundary). |
| `find_top_level_ifs(root, source, known_functions)` | Same as above, but for the top level of a file (outside any function). |
| `_condition_by_position(node)` | A fallback: when the grammar doesn't expose a `condition` field directly (like on `elif_clause`), finds the condition by locating the `then` token and taking the node right before it. |
| `build_if_node(if_node, source, known_functions)` | Converts a full `if_statement` (with its `elif`s and `else`) into a dict: `{"condition":..., "line":..., "then":..., "elif_branches":[...], "else":...}`. |
| `build_elif_node(elif_node, source, known_functions)` | Same as above, but for a single `elif_clause`. |
| `analyze_project(file_paths)` | The main orchestration function: parses every file, builds the project-wide function table, and returns the final `{"files": {...}, "functions": {...}}` output. |
| `main()` | CLI entry point: reads arguments (directory or files, `--clean`, `-o`), calls `analyze_project`, and applies `simplify_project` if requested. |

**A note on `COMPOUND_TYPES`:** this tuple includes `for_statement`, `while_statement`, `c_style_for_statement`, `subshell`, `compound_statement`, `do_group`. These are kept as a raw text block (`"type": "block"`), but any `if`/`case` inside them is still extracted separately. **`case_statement` is deliberately NOT in this list** — it's processed as a full decision type of its own, not as an opaque block.

### 📄 `simplify.py` — simplification

| Function | What it does |
|---|---|
| `_clean_label(text)` | Turns `echo "message"` into just `message` for readability. |
| `_terminates(value)` | Checks whether a branch ends in `return`/`exit` — so we don't incorrectly chain the flow's continuation onto a branch that already ends there. |
| `_expand_call(fname, functions, visited)` | Expands a function by name: if it has its own branching (`if`/`case`), simplifies it recursively; if it's just plain actions, returns those; if it's called recursively (references itself), returns a "recursive" marker instead of infinite-looping. |
| `_simplify_node(node, functions, visited)` | Dispatches to `_simplify_case` or `_simplify_if` based on the node's shape (`branches` vs `condition`). |
| `_simplify_sequence(nested_decisions, functions, visited)` | When several `if`/`case` decisions occur in sequence in the same body, chains the rest onto every branch that doesn't terminate (per `_terminates`). |
| `_append_continuation(existing, continuation)` | Appends "what comes next" onto an already-simplified branch. |
| `_attach_trailing(node, trailing)` | Attaches actions that occur after the last decision (`after_actions`) onto every non-terminating leaf. |
| `_simplify_branch(body, functions, visited)` | Simplifies a `then`/`else` branch: expands nested decisions if present, inline-expands the last action if it's a function call, otherwise returns plain text. |
| `_simplify_case(node, functions, visited)` | Simplifies a `case` node; processes each branch with `_simplify_branch`. |
| `_elif_chain_to_if(elif_branches, else_branch)` | Folds an `elif` chain into a synthetic nested `if` (so it simplifies with the same logic as a plain `if`). |
| `_simplify_if(if_node, functions, visited)` | The core of simplification: converts an `if_statement` into `{"condition":..., "yes":..., "no":..., ["condition_detail"], ["before"]}`. |
| `simplify_project(analysis)` | The main entry point: runs over every file and every one of its top-level trees, returns `{filename: [trees]}`. |

### 📄 `render_tree.py` — SVG rendering

Pure Python, no external dependencies. It:
1. Converts the clean JSON into a `TreeNode` structure (`build_tree`)
2. Uses a subtree-width-based layout algorithm (`compute_subtree_width`/`place_x`) to guarantee no box overlaps its neighbor
3. Places `condition_detail` as a dashed sub-tree directly above the node it belongs to (`place_details`) — supporting one full level (a detail-of-a-detail is folded into a text summary instead of a second sub-tree, to avoid visual collisions)
4. The final output is a standalone `.svg` file

**Known limitation:** for very large projects with many parallel branches that each have deep `condition_detail` chains, some boxes may still collide (since each `condition_detail` is placed independently/locally, unaware of a sibling branch's own detail). For that scale, **`render_dot.py` + Graphviz** is recommended (since `dot` has its own proper, global layout algorithm).

### 📄 `render_dot.py` — DOT/Graphviz rendering

Uses similar logic to `render_tree.py`, but instead of pixel coordinates, it only builds nodes and edges in DOT text format (the `DotBuilder` class). The actual layout is done by Graphviz itself (the `dot` command) when converting to an image, so this file never runs into the box-collision problem. By default it also shows `condition_detail`/`value_detail` as separate edges (labeled `detail`) — this can be turned off with the `--simple` flag.

### 📄 `run_all.py` — batch test runner

Defines a fixed list (`TEST_CASES`) of project samples (installer, various corner cases), fully processes each one (raw → clean → SVG), and saves the results under `results/<test_name>/`. If one fails, the rest still run — the failure is just logged. At the end it also builds one `all_results.json` with every test's clean output in one place.

### 📄 `simplify_tree.py` — standalone CLI for simplification

A lightweight wrapper that reads `raw.json`, calls `simplify_project`, and saves the result — without re-parsing any bash. Useful when you already have `raw.json` and just want to re-simplify it (e.g. after an update to `simplify.py`).

### 📄 `extractor.py` — first version (deprecated)

The tool's original version, which processed each bash file **in isolation, unaware of other files**. Its core bug was that it couldn't detect function calls across files. **No longer used** — kept only for reference. `project_analyzer.py` fully replaces it.

---

## 5. Features

- ✅ Multi-file project analysis with automatic `source` detection
- ✅ Linking function calls across files (not just within one file)
- ✅ Extracting `if`/`elif`/`else` with any condition type (simple, compound with `&&`/`||`, negated with `!`)
- ✅ Extracting `case` with combined patterns (`a|b|c)`)
- ✅ Detecting nested `if`/`case` (even inside `for`/`while`/`subshell`)
- ✅ Inline-expanding function calls when used as actions
- ✅ Preserving a function's internal detail when used as a condition (`condition_detail`) without merging it into the main flow
- ✅ Detecting sequences of multiple decisions in a row and chaining them correctly (respecting `return`/`exit`)
- ✅ Stripping comments out of actions
- ✅ Cleaning up `echo` text for readability
- ✅ Reporting line numbers (`line`) for every decision
- ✅ Pure-Python SVG output (no installs needed)
- ✅ DOT output for Graphviz
- ✅ Recursive subdirectory scanning (`rglob`)
- ✅ Batch test execution with `run_all.py`

---

## 6. Known Limitations

These are known, **deliberate** trade-offs — either outside the project's original scope, or things we've consciously accepted for now:

1. **No full control-flow analysis:** we only detect `return`/`exit` shallowly (as the last action of a branch). A deeper `return` (e.g. two levels of nesting down) may still get a continuation incorrectly attached to it.
2. **The tree repeats after a `case` instead of being linked:** when code follows a `case_statement`, that code gets appended to **every branch** of the case that doesn't terminate (rather than being linked once). This is semantically correct, but increases output size for `case`s with many branches.
3. **Loops (`for`/`while`) as raw text:** a loop's body is kept as one raw text block (not a structured, repeating node). Only the `if`/`case` inside it are extracted separately.
4. **Box collisions in SVG for very large projects:** explained above (the `render_tree.py` section). Workaround: use `render_dot.py`.
5. **Compound conditions (`&&`/`||`) aren't expanded:** if a condition includes multiple function calls joined by `&&`/`||` (like `if is_valid && has_permission; then`), the whole condition stays as raw text rather than each call being analyzed separately.
6. **`line` only for decisions, not actions:** line numbers are only recorded for `if`/`case` nodes, not for each individual action.

---

## 7. History of Bugs Found and Fixed

Through testing against real, complex samples, these bugs were found and fixed:

| # | Bug | Where | Status |
|---|---|---|---|
| 1 | Cross-file function calls weren't linked at all (original `extractor.py`) | Overall architecture | ✅ Fixed by rewriting as `project_analyzer.py` |
| 2 | The condition inside an `elif` wasn't extracted (`elif_clause` has no `condition` field) | `project_analyzer.py` | ✅ Fixed with the `_condition_by_position` fallback |
| 3 | Multiple sequential `if`s in one function: only the first was seen | `simplify.py` | ✅ Fixed with `_simplify_sequence` |
| 4 | `case_statement` was ignored entirely (only an `if` inside it was extracted) | `project_analyzer.py` | ✅ Fixed with `build_case_node` |
| 5 | Combined `case` patterns (`a|b|c)`) — only the first pattern was recognized, the rest were incorrectly swept into the body | `project_analyzer.py` | ✅ Fixed with `children_by_field_name` (plural) |
| 6 | Chaining after a `case_statement` didn't work at all (code after a case was lost) | `simplify.py` | ✅ Fixed |
| 7 | `if ! func; then` (negation) wasn't recognized as a function call | `project_analyzer.py` | ✅ Fixed by unwrapping `negated_command` |
| 8 | Actions after the last `if` in a body (like a trailing `return 0`) were lost | `project_analyzer.py` + `simplify.py` | ✅ Fixed with `after_actions` |
| 9 | Comments were incorrectly counted as actions | `project_analyzer.py` | ✅ Fixed |
| 10 | Compounding duplicated content across `case` branches (from a shallow copy instead of a deep one) | `simplify.py` | ✅ Fixed with `copy.deepcopy` |
| 11 | Extra `()` in function names (included the whole call text + arguments) | `simplify.py` | ✅ Fixed by using the bare function name |
| 12 | Line numbers (`line`) were dropped from the simplified output | `simplify.py` | ✅ Fixed |
| 13 | The flow's continuation was incorrectly chained onto branches that already ended in `return`/`exit` | `simplify.py` | ✅ Fixed with `_terminates` |
| 14 | `glob("*.sh")` only found files directly inside a folder, not subfolders | `project_analyzer.py` | ✅ Fixed with `rglob` |
| 15 | `condition_detail` was only shown as a summarized text line in the SVG, not a real sub-tree | `render_tree.py` | ✅ Fixed (capped at one level to avoid collisions) |
| 16 | Wide boxes (due to `before` text) could overlap their neighbor | `render_tree.py` | ✅ Fixed with a subtree-width-based layout algorithm |

---

## 8. Examples and Test Cases (`examples/`)

| Example | What it tests |
|---|---|
| `installer/` | Base scenario: one file that sources two others and uses their functions |
| `corner_cases/elif_chain.sh` | A 3-way `elif` chain with no function calls |
| `corner_cases/deep_chain/` | A 3-file call chain + sequential guard clauses |
| `corner_cases/recursive/retry.sh` | A function that calls itself (tests the infinite-loop guard) |
| `corner_cases/unresolved/caller.sh` | Calling a function that's never defined (safe fallback) |
| `corner_cases/compound_condition.sh` | A compound `&&` condition that shouldn't be misdetected as a call |
| `corner_cases/case_with_if.sh` | An `if` nested inside a `case` |
| `corner_cases/multi_top_level.sh` | Multiple independent top-level `if`s in one file |

---

## 9. Conclusion

This project started from a simple idea (extract `if`/`else` from bash) and, through repeated testing against real and increasingly complex samples (an 8-file deployment project, deeply nested `elif` scripts), grew into a fairly complete tool that:
- Analyzes the whole project (not just a single file)
- Preserves cross-file relationships
- Shows a function's internal detail without cluttering the main flow
- Produces both a machine-readable output (JSON) and a human-readable one (SVG/DOT)

The remaining limitations (no full control-flow analysis, repetition after a case, loops as raw text) are documented and can be addressed further if needed.

"""
run_all.py
----------
Runs every example / corner-case test through the full pipeline
(project_analyzer -> simplify -> render_tree) and saves everything into
a results folder, so you can eyeball the SVGs and also hand the combined
JSON back for review.

Must be run from the project root (the folder containing project_analyzer.py,
simplify.py, render_tree.py, and the examples/ folder), since it imports
them directly.

Usage:
    python run_all.py
    python run_all.py -o results
"""

import argparse
import json
import sys
import traceback
from pathlib import Path

from project_analyzer import analyze_project
from simplify import simplify_project
from render_tree import render_svg

# name -> list of .sh files (relative to this script's folder) that make up that test
TEST_CASES = {
    "installer": [
        "examples/installer/installer.sh",
        "examples/installer/network.sh",
        "examples/installer/package.sh",
    ],
    "elif_chain": [
        "examples/corner_cases/elif_chain.sh",
    ],
    "deep_chain": [
        "examples/corner_cases/deep_chain/entry.sh",
        "examples/corner_cases/deep_chain/validate.sh",
        "examples/corner_cases/deep_chain/deploy_step.sh",
    ],
    "recursive": [
        "examples/corner_cases/recursive/retry.sh",
    ],
    "unresolved": [
        "examples/corner_cases/unresolved/caller.sh",
    ],
    "compound_condition": [
        "examples/corner_cases/compound_condition.sh",
    ],
    "case_with_if": [
        "examples/corner_cases/case_with_if.sh",
    ],
    "multi_top_level": [
        "examples/corner_cases/multi_top_level.sh",
        "examples/installer/package.sh",
    ],
}


def run_one(name: str, rel_paths: list, base_dir: Path, out_dir: Path) -> dict:
    """Runs one test case end-to-end. Returns a result dict; never raises --
    failures are captured so one broken test doesn't stop the rest."""
    test_out = out_dir / name
    test_out.mkdir(parents=True, exist_ok=True)

    paths = [base_dir / p for p in rel_paths]
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        return {"name": name, "status": "error", "error": f"missing files: {missing}"}

    try:
        raw = analyze_project(paths)
        clean = simplify_project(raw)

        (test_out / "raw.json").write_text(
            json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (test_out / "clean.json").write_text(
            json.dumps(clean, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        svg_dir = test_out / "svgs"
        svg_dir.mkdir(exist_ok=True)
        svg_count = 0
        for filename, trees in clean.items():
            for i, tree in enumerate(trees):
                svg = render_svg(tree)
                (svg_dir / f"{Path(filename).stem}_{i + 1}.svg").write_text(svg, encoding="utf-8")
                svg_count += 1

        return {
            "name": name,
            "status": "ok",
            "svg_count": svg_count,
            "clean": clean,
        }
    except Exception as e:
        return {
            "name": name,
            "status": "error",
            "error": f"{type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
        }


def main():
    ap = argparse.ArgumentParser(description="Run all example/corner-case tests through the full pipeline.")
    ap.add_argument("-o", "--outdir", type=Path, default=Path("results"))
    args = ap.parse_args()

    base_dir = Path(__file__).resolve().parent
    args.outdir.mkdir(parents=True, exist_ok=True)

    summary = {}
    for name, rel_paths in TEST_CASES.items():
        print(f"Running: {name} ...", file=sys.stderr)
        result = run_one(name, rel_paths, base_dir, args.outdir)
        summary[name] = result
        if result["status"] == "ok":
            print(f"  ok - {result['svg_count']} svg(s) -> {args.outdir / name / 'svgs'}", file=sys.stderr)
        else:
            print(f"  ERROR: {result['error']}", file=sys.stderr)

    # One combined file with everything (minus tracebacks, kept in per-test
    # folders only) -- this is the one to send back for review.
    combined = {
        name: (
            {"status": r["status"], "svg_count": r.get("svg_count"), "clean": r.get("clean")}
            if r["status"] == "ok"
            else {"status": r["status"], "error": r["error"]}
        )
        for name, r in summary.items()
    }
    combined_path = args.outdir / "all_results.json"
    combined_path.write_text(json.dumps(combined, indent=2, ensure_ascii=False), encoding="utf-8")

    ok_count = sum(1 for r in summary.values() if r["status"] == "ok")
    print(f"\n{ok_count}/{len(summary)} tests ran without errors.", file=sys.stderr)
    print(f"Combined results written to {combined_path}", file=sys.stderr)
    print(f"Per-test raw/clean/svgs written under {args.outdir}/<test_name>/", file=sys.stderr)


if __name__ == "__main__":
    main()
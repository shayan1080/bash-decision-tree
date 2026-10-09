"""
simplify_tree.py
-----------------
Turns the detailed JSON from project_analyzer.py into a clean yes/no
decision tree, with function-call actions inlined.

Usage:
    python project_analyzer.py examples/installer -o raw.json
    python simplify_tree.py raw.json
    python simplify_tree.py raw.json -o clean.json
"""

import argparse
import json
import sys
from pathlib import Path

from simplify import simplify_project


def main():
    ap = argparse.ArgumentParser(description="Simplify project_analyzer.py output into a clean decision tree.")
    ap.add_argument("input", type=Path, help="Path to the raw JSON produced by project_analyzer.py")
    ap.add_argument("-o", "--output", type=Path, default=None)
    args = ap.parse_args()

    analysis = json.loads(args.input.read_text(encoding="utf-8"))
    clean = simplify_project(analysis)
    output_json = json.dumps(clean, indent=2, ensure_ascii=False)

    if args.output:
        args.output.write_text(output_json, encoding="utf-8")
        print(f"Wrote {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
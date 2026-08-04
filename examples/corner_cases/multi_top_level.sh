#!/bin/bash
# Tests: two SEPARATE top-level if-statements in one file (not nested in
# each other). decision_trees for this file should have 2 entries.

source packages.sh

if [ -z "$1" ]; then
    echo "Usage: $0 <target>"
    exit 1
fi

if install_packages; then
    echo "Setup complete"
else
    echo "Setup failed"
fi
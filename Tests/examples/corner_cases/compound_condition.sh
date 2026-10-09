#!/bin/bash
# Tests: a condition that's a compound expression (list with &&) where
# BOTH sides happen to be known functions. This should NOT be classified
# as a single "call" -- it's a raw compound condition, even though a
# naive text-match on the condition might tempt you to detect a call here.

is_valid() {
    [ -n "$1" ]
}

has_permission() {
    [ "$USER" = "root" ]
}

if is_valid "$1" && has_permission; then
    echo "Proceeding"
else
    echo "Blocked"
fi
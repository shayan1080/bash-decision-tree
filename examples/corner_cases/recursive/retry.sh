#!/bin/bash
# Tests: direct recursion. retry_download calls itself in its own
# "no" branch. Should not infinite-loop -- simplify.py's visited-set
# guard should catch this and print a "[recursive ...]" marker instead.

retry_download() {
    if download_file; then
        echo "Download succeeded"
    else
        echo "Retrying..."
        retry_download
    fi
}

if retry_download; then
    echo "Done"
else
    echo "Gave up"
fi
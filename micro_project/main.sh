#!/bin/bash
source lib.sh

deploy() {
    if ! check_disk "$1"; then
        log_error "cannot deploy"
        exit 1
    fi

    echo "deploying"
    return 0
}

cleanup() {
    echo "cleaning up"
    return 0
}

if deploy "95"; then
    echo "DEPLOY OK"
else
    echo "DEPLOY FAILED"
fi

cleanup
echo "DONE"
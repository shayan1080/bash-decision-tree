#!/bin/bash

log_error() {
    echo "ERROR: $1"
    return 1
}

log_warn() {
    echo "WARN: $1"
}

check_disk() {
    local usage="$1"

    if [ "$usage" -gt 90 ]; then
        log_error "disk full"
        return 1
    fi

    log_warn "disk ok"
    return 0
}
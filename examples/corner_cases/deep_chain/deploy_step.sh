#!/bin/bash

check_disk_space() {
    if [ $(df / | tail -1 | awk '{print $5}' | tr -d '%') -lt 90 ]; then
        return 0
    else
        return 1
    fi
}

run_deploy() {
    echo "Running deployment steps"
    for step in build test publish; do
        if [ "$step" = "publish" ]; then
            echo "Publishing artifact"
        fi
    done
}
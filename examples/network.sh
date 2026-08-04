#!/bin/bash

check_network() {
    if ping -c 1 google.com >/dev/null; then
        return 0
    else
        return 1
    fi
}
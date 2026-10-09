#!/bin/bash

log_error() {
    echo "ERROR: $1"
    return 1
}

check_database() {
    local status="$1"

    if [ "$status" = "up" ]; then
        echo "Database is up"
        return 0
    else
        log_error "Database is down"
        echo "Database check failed"
        return 1
    fi
}

check_service() {
    local db_status="$1"
    local service_status="$2"

    if check_database "$db_status"; then
        echo "Database check passed"

        if [ "$service_status" = "up" ]; then
            echo "Service is up"
            return 0
        else
            log_error "Service is down"
            return 1
        fi
    else
        echo "Cannot check service"
        return 1
    fi
}

validate_environment() {
    local env="$1"

    if [ "$env" = "production" ]; then
        echo "Production environment"
        return 0
    elif [ "$env" = "staging" ]; then
        echo "Staging environment"
        return 0
    else
        log_error "Unknown environment"
        return 1
    fi
}
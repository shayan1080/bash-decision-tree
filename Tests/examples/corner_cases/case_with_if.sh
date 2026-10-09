#!/bin/bash
# Tests: if-statements nested inside a case statement (not for/while).

ACTION=$1

case "$ACTION" in
    start)
        if [ -f "./app.pid" ]; then
            echo "Already running"
        else
            echo "Starting app"
        fi
        ;;
    stop)
        echo "Stopping app"
        ;;
    *)
        echo "Unknown action"
        ;;
esac
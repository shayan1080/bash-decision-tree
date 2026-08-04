#!/bin/bash
# Tests: calls send_notification(), which is never defined in this file
# (imagine it's normally sourced from a file you forgot to pass to the
# tool). Should fall back gracefully instead of crashing.

if send_notification "deploy started"; then
    echo "Notified"
else
    echo "Notification failed"
fi
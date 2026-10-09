#!/bin/bash

source config/config.sh
source lib/checks.sh
source lib/deployment.sh

main() {
    echo "Starting deployment"

    if deploy "up" "up"; then
        echo "Deployment successful"
    else
        echo "Deployment failed"

        if rollback; then
            echo "Rollback successful"
        else
            log_error "Rollback failed"
        fi
    fi

    echo "Deployment process finished"
}

main
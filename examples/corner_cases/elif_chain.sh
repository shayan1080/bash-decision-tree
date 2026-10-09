#!/bin/bash
# Tests: elif chain (3+ branches), no function calls involved at all.

ENV=$1

if [ "$ENV" = "production" ]; then
    echo "Deploying to production"
elif [ "$ENV" = "staging" ]; then
    echo "Deploying to staging"
elif [ "$ENV" = "development" ]; then
    echo "Deploying to development"
else
    echo "Unknown environment"
fi
#!/bin/bash

# if اول
if [[ "$1" == "test" ]]; then
    echo "Test mode"
fi

# if دوم
if [[ "$1" == "deploy" ]]; then
    echo "Deploy mode"
fi
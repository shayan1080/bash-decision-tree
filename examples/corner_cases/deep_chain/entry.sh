#!/bin/bash
# Tests: a call chain 3 files deep (entry -> validate -> disk), each level
# adding its own branching. Also tests a condition-call whose branch (yes)
# contains MULTIPLE actions, one of which is a call (not the single-action
# case the current code special-cases).

source validate.sh
source deploy_step.sh

if validate_environment; then
    echo "Environment OK, starting deploy"
    run_deploy
else
    echo "Environment check failed, aborting"
    exit 1
fi
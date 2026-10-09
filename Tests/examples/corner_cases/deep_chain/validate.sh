 #!/bin/bash
# validate_environment() calls check_disk_space(), which is defined in a
# THIRD file (deploy_step.sh) that THIS file sources -- not entry.sh
# directly. Tests whether call resolution still works when the function
# is only transitively reachable, not sourced by the file that calls it.

source deploy_step.sh

validate_environment() {
    if [ -z "$HOME" ]; then
        echo "HOME not set"
        return 1
    fi

    if check_disk_space; then
        return 0
    else
        return 1
    fi
}
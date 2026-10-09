#!/bin/bash
# app.sh - سیستم مدیریت کاربران (درخت مستقل)

# ============================================
# توابع مدیریت کاربران
# ============================================

create_user() {
    local username="$1"
    local role="$2"
    
    if [[ -z "$username" ]]; then
        echo "ERROR: Username is required"
        return 1
    fi
    
    if [[ -z "$role" ]]; then
        echo "WARNING: No role specified, defaulting to 'user'"
        role="user"
    fi
    
    if [[ "$role" == "admin" ]]; then
        echo "Creating admin user: $username"
        # Admin specific logic
        if [[ "$username" == "root" ]]; then
            echo "WARNING: Root user created with admin privileges"
            return 0
        else
            echo "Admin user $username created successfully"
            return 0
        fi
    elif [[ "$role" == "editor" ]]; then
        echo "Creating editor user: $username"
        echo "Editor $username created successfully"
        return 0
    elif [[ "$role" == "viewer" ]]; then
        echo "Creating viewer user: $username"
        echo "Viewer $username created successfully"
        return 0
    else
        echo "Creating regular user: $username"
        echo "User $username created successfully"
        return 0
    fi
}

delete_user() {
    local username="$1"
    local force="$2"
    
    if [[ -z "$username" ]]; then
        echo "ERROR: Username is required for deletion"
        return 1
    fi
    
    if [[ "$force" == "true" ]]; then
        echo "Force deleting user: $username"
        return 0
    else
        echo "Would you like to delete user: $username? (y/n)"
        return 0
    fi
}

list_users() {
    local format="$1"
    
    if [[ "$format" == "json" ]]; then
        echo '{"users": ["alice", "bob", "charlie"]}'
        return 0
    elif [[ "$format" == "csv" ]]; then
        echo "alice,bob,charlie"
        return 0
    else
        echo "alice"
        echo "bob"
        echo "charlie"
        return 0
    fi
}

# ============================================
# نقطه ورود - مدیریت کاربران
# ============================================

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "=== USER MANAGEMENT SYSTEM ==="
    
    # Test create_user
    if create_user "alice" "admin"; then
        echo "User creation test passed"
    else
        echo "User creation test failed"
    fi
    
    # Test delete_user
    if delete_user "bob" "true"; then
        echo "User deletion test passed"
    else
        echo "User deletion test failed"
    fi
    
    # Test list_users with different formats
    if list_users "json" | grep -q "alice"; then
        echo "JSON format test passed"
    else
        echo "JSON format test failed"
    fi
fi
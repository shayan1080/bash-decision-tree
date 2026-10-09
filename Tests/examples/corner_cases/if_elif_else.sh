#!/bin/bash
# complex_conditions.sh - A test file with many nested if/elif/else

# ============================================================================
# 1. BASIC IF-ELIF-ELSE CHAIN (5 branches)
# ============================================================================

check_environment() {
    local env="$1"
    
    if [[ "$env" == "production" ]]; then
        echo "Running in PRODUCTION mode"
        DEPLOY_STRATEGY="canary"
        BACKUP_REQUIRED=true
        MAINTENANCE_MODE=false
        
    elif [[ "$env" == "staging" ]]; then
        echo "Running in STAGING mode"
        DEPLOY_STRATEGY="rolling"
        BACKUP_REQUIRED=true
        MAINTENANCE_MODE=false
        
    elif [[ "$env" == "development" ]]; then
        echo "Running in DEVELOPMENT mode"
        DEPLOY_STRATEGY="direct"
        BACKUP_REQUIRED=false
        MAINTENANCE_MODE=false
        
    elif [[ "$env" == "testing" ]]; then
        echo "Running in TESTING mode"
        DEPLOY_STRATEGY="none"
        BACKUP_REQUIRED=false
        MAINTENANCE_MODE=true
        
    else
        echo "ERROR: Unknown environment: $env"
        return 1
    fi
    
    return 0
}

# ============================================================================
# 2. NESTED IF (3 levels deep)
# ============================================================================

validate_deployment() {
    local version="$1"
    local force="$2"
    
    # Level 1
    if [[ -z "$version" ]]; then
        echo "ERROR: Version is required"
        return 1
    else
        # Level 2
        if [[ "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
            echo "Version format is valid: $version"
            
            # Level 3
            if [[ "$force" == "true" ]]; then
                echo "FORCE mode enabled - skipping compatibility check"
                return 0
            else
                echo "Checking compatibility..."
                
                # Level 4
                if [[ "$version" == "v1.0.0" ]]; then
                    echo "Legacy version - some features disabled"
                    return 0
                elif [[ "$version" == "v1.1.0" ]]; then
                    echo "Compatible version - all features available"
                    return 0
                else
                    echo "Compatibility check passed for $version"
                    return 0
                fi
            fi
        else
            echo "ERROR: Invalid version format: $version"
            return 1
        fi
    fi
}

# ============================================================================
# 3. IF WITH MULTIPLE CONDITIONS (&& and ||)
# ============================================================================

check_system_ready() {
    local cpu_usage="$1"
    local memory_usage="$2"
    local disk_usage="$3"
    local network_ok="$4"
    
    if [[ "$network_ok" == "true" ]] && [[ "$cpu_usage" -lt 80 ]] && [[ "$memory_usage" -lt 90 ]]; then
        echo "System is ready for deployment"
        return 0
        
    elif [[ "$network_ok" == "false" ]] && [[ "$cpu_usage" -lt 50 ]] && [[ "$memory_usage" -lt 70 ]]; then
        echo "Network is down but system is idle - waiting for network"
        return 1
        
    elif [[ "$cpu_usage" -gt 90 ]] || [[ "$memory_usage" -gt 95 ]]; then
        echo "ERROR: System overloaded - CPU: ${cpu_usage}%, Memory: ${memory_usage}%"
        return 2
        
    elif [[ "$disk_usage" -gt 90 ]] && [[ "$cpu_usage" -lt 60 ]]; then
        echo "WARNING: Disk space critical but CPU is fine"
        return 3
        
    else
        echo "Unknown system state - manual check required"
        return 4
    fi
}

# ============================================================================
# 4. IF WITH COMMAND EXECUTION
# ============================================================================

check_database() {
    local db_host="$1"
    local db_user="$2"
    local db_name="$3"
    
    if mysqladmin ping -h "$db_host" -u "$db_user" 2>/dev/null; then
        echo "Database server is reachable"
        
        if mysql -h "$db_host" -u "$db_user" -e "USE $db_name" 2>/dev/null; then
            echo "Database '$db_name' exists"
            
            if mysql -h "$db_host" -u "$db_user" -e "SHOW TABLES FROM $db_name" | grep -q "users"; then
                echo "Table 'users' exists"
                return 0
            else
                echo "ERROR: Table 'users' not found in $db_name"
                return 1
            fi
        else
            echo "ERROR: Database '$db_name' does not exist"
            return 2
        fi
    else
        echo "ERROR: Cannot connect to database server"
        return 3
    fi
}

# ============================================================================
# 5. COMPLEX IF WITH ARITHMETIC
# ============================================================================

check_version_compatibility() {
    local current_version="$1"
    local new_version="$2"
    
    local cur_major=$(echo "$current_version" | cut -d. -f1)
    local cur_minor=$(echo "$current_version" | cut -d. -f2)
    local new_major=$(echo "$new_version" | cut -d. -f1)
    local new_minor=$(echo "$new_version" | cut -d. -f2)
    
    if [[ $new_major -gt $cur_major ]]; then
        echo "Major version upgrade detected"
        
        if [[ $new_major -eq $((cur_major + 1)) ]]; then
            echo "Minor major upgrade - safe"
            
            if [[ $new_minor -eq 0 ]]; then
                echo "New major version with 0 minor - stable"
                return 0
            else
                echo "New major version with minor > 0 - stable"
                return 0
            fi
        else
            echo "WARNING: Skipping multiple major versions"
            
            if [[ $((new_major - cur_major)) -gt 2 ]]; then
                echo "ERROR: Too many major versions skipped"
                return 1
            else
                echo "Safe to proceed with 2 major version jump"
                return 0
            fi
        fi
        
    elif [[ $new_major -eq $cur_major ]]; then
        echo "Same major version - minor upgrade"
        
        if [[ $new_minor -gt $cur_minor ]]; then
            echo "Minor version upgrade - safe"
            return 0
        elif [[ $new_minor -eq $cur_minor ]]; then
            echo "Same version - no change needed"
            return 0
        else
            echo "ERROR: Cannot downgrade minor version"
            return 1
        fi
        
    else
        echo "ERROR: Major version downgrade not allowed"
        return 1
    fi
}

# ============================================================================
# 6. FUNCTION WITH EARLY RETURNS
# ============================================================================

validate_arguments() {
    local env="$1"
    local version="$2"
    local force="$3"
    
    if [[ -z "$env" ]]; then
        echo "ERROR: Environment is required"
        return 1
    fi
    
    if [[ -z "$version" ]]; then
        echo "ERROR: Version is required"
        return 1
    fi
    
    if [[ "$env" != "production" ]] && [[ "$env" != "staging" ]] && [[ "$env" != "development" ]]; then
        echo "ERROR: Invalid environment: $env"
        return 1
    fi
    
    if [[ "$force" != "true" ]] && [[ "$force" != "false" ]]; then
        echo "WARNING: Invalid force value '$force' - defaulting to false"
        force="false"
    fi
    
    if [[ "$version" != "latest" ]] && [[ ! "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        echo "ERROR: Invalid version format: $version"
        return 1
    fi
    
    echo "All arguments valid!"
    return 0
}

# ============================================================================
# ✅ TOP-LEVEL IF (این را اضافه کردم تا decision_tree داشته باشیم)
# ============================================================================

# اگر فایل مستقیماً اجرا شود، main را اجرا کن
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    
    echo "=== TESTING COMPLEX CONDITIONS ==="
    echo ""
    
    # Test 1: Environment check
    check_environment "production"
    check_environment "staging"
    check_environment "invalid"
    echo ""
    
    # Test 2: Version validation
    validate_deployment "v1.2.3" "false"
    validate_deployment "v1.2.3" "true"
    validate_deployment "invalid" "false"
    echo ""
    
    # Test 3: System ready
    check_system_ready 75 85 70 true
    check_system_ready 95 85 70 true
    check_system_ready 75 95 70 true
    echo ""
    
    # Test 4: Version compatibility
    check_version_compatibility "v1.0.0" "v1.1.0"
    check_version_compatibility "v1.0.0" "v2.0.0"
    check_version_compatibility "v1.0.0" "v3.0.0"
    echo ""
    
    # Test 5: Arguments validation
    validate_arguments "production" "v1.2.3" "true"
    validate_arguments "invalid" "v1.2.3" "true"
    echo ""
    
    # Test 6: Nested conditions (all in one)
    if check_environment "development" && validate_deployment "v2.0.0" "true"; then
        if check_system_ready 60 70 80 true; then
            echo "✅ All checks passed!"
        else
            echo "❌ System check failed"
        fi
    else
        echo "❌ Environment or deployment validation failed"
        
        if check_environment "development"; then
            echo "Environment is OK but deployment failed"
        else
            echo "Environment validation failed!"
        fi
    fi
fi
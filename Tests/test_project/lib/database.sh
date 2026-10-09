#!/bin/bash
# Database operations

# Global database variables
DB_HOST="localhost"
DB_PORT="3306"
DB_USER="deploy_user"
DB_PASSWORD=""

# Check database connectivity
check_database_connectivity() {
    local environment="$1"
    
    # Set database credentials based on environment
    case "${environment}" in
        production)
            DB_HOST="prod-db-01"
            DB_PORT="3306"
            DB_NAME="prod_app"
            ;;
        staging)
            DB_HOST="staging-db-01"
            DB_PORT="3306"
            DB_NAME="staging_app"
            ;;
        development)
            DB_HOST="localhost"
            DB_PORT="3306"
            DB_NAME="dev_app"
            ;;
        *)
            return 1
            ;;
    esac
    
    # Test database connection with retry
    local retry=0
    local max_retries=10
    local backoff=2
    
    for ((retry=1; retry<=max_retries; retry++)); do
        if mysqladmin ping -h "${DB_HOST}" -P "${DB_PORT}" -u "${DB_USER}" 2>/dev/null; then
            return 0
        fi
        sleep ${backoff}
        backoff=$((backoff * 2))
    done
    
    log_error "Failed to connect to database after ${max_retries} attempts"
    return 1
}

# Check database schema
check_database_schema() {
    local environment="$1"
    local version="$2"
    local required_tables=()
    
    # Define required tables based on environment
    if [[ "${environment}" == "production" ]]; then
        required_tables=(
            "users"
            "orders"
            "products"
            "inventory"
            "payments"
            "audit_log"
            "notifications"
        )
    elif [[ "${environment}" == "staging" ]]; then
        required_tables=(
            "users"
            "orders"
            "products"
            "inventory"
            "payments"
        )
    else
        required_tables=(
            "users"
            "orders"
            "products"
        )
    fi
    
    # Check if version requires additional tables
    if [[ "${version}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        # Major version changes might need new tables
        local major_version=$(echo "${version}" | cut -d. -f1 | sed 's/v//')
        if [[ ${major_version} -ge 2 ]]; then
            required_tables+=("analytics" "reports")
        fi
    fi
    
    local missing_tables=()
    for table in "${required_tables[@]}"; do
        if ! mysql -h "${DB_HOST}" -P "${DB_PORT}" -u "${DB_USER}" \
            -e "SHOW TABLES LIKE '${table}'" "${DB_NAME}" | grep -q "${table}"; then
            missing_tables+=("${table}")
        fi
    done
    
    if [[ ${#missing_tables[@]} -gt 0 ]]; then
        log_error "Missing database tables: ${missing_tables[*]}"
        return 1
    fi
    
    # Check table structures for critical tables
    if [[ "${environment}" == "production" ]]; then
        if ! check_table_structure "users" "id,email,name,created_at,updated_at"; then
            return 2
        fi
        if ! check_table_structure "orders" "id,user_id,total,status,created_at"; then
            return 3
        fi
    fi
    
    return 0
}

# Check table structure
check_table_structure() {
    local table="$1"
    local required_columns="$2"
    
    local actual_columns=$(mysql -h "${DB_HOST}" -P "${DB_PORT}" -u "${DB_USER}" \
        -e "DESCRIBE ${table}" "${DB_NAME}" | awk 'NR>1 {print $1}' | tr '\n' ',' | sed 's/,$//')
    
    IFS=',' read -ra required_array <<< "${required_columns}"
    for column in "${required_array[@]}"; do
        if ! echo "${actual_columns}" | grep -q "${column}"; then
            log_error "Missing column '${column}' in table '${table}'"
            return 1
        fi
    done
    
    return 0
}

# Check version compatibility
check_version_compatibility() {
    local environment="$1"
    local version="$2"
    
    # Parse version
    if [[ ! "${version}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        log_error "Invalid version format: ${version}"
        return 1
    fi
    
    local major=$(echo "${version}" | cut -d. -f1 | sed 's/v//')
    local minor=$(echo "${version}" | cut -d. -f2)
    local patch=$(echo "${version}" | cut -d. -f3)
    
    # Check if version is supported
    if [[ ${major} -eq 0 ]]; then
        log_warn "Version ${version} is a major version 0 - may be unstable"
    fi
    
    # Check for breaking changes
    if [[ ${major} -ge 2 ]] && [[ "${environment}" == "production" ]]; then
        if ! confirm_breaking_changes "${version}" "${environment}"; then
            return 1
        fi
    fi
    
    # Check minimum version requirements
    if [[ "${environment}" == "production" ]] && [[ ${major} -lt 1 ]]; then
        log_error "Production requires at least v1.x.x, got ${version}"
        return 1
    fi
    
    # Check against current deployed version
    if [[ "${environment}" == "production" ]]; then
        local current_version=$(get_current_version "production")
        if [[ -n "${current_version}" ]]; then
            local current_major=$(echo "${current_version}" | cut -d. -f1 | sed 's/v//')
            if [[ ${major} -lt ${current_major} ]]; then
                log_error "Cannot downgrade major version: ${current_version} -> ${version}"
                return 1
            fi
        fi
    fi
    
    return 0
}

# Get current deployed version
get_current_version() {
    local environment="$1"
    
    # In a real scenario, this would query a version file or API
    if [[ "${environment}" == "production" ]]; then
        echo "v1.2.3"  # Simulated current version
    elif [[ "${environment}" == "staging" ]]; then
        echo "v1.3.0"
    else
        echo "v2.0.0"
    fi
}
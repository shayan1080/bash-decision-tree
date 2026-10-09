#!/bin/bash
# env_config.sh - Environment-specific configuration

# ============================================================================
# Environment variables with defaults
# ============================================================================

# Database configuration
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-3306}"
DB_USER="${DB_USER:-deploy_user}"
DB_PASSWORD="${DB_PASSWORD:-}"
DB_NAME="${DB_NAME:-app_db}"

# Redis configuration
REDIS_HOST="${REDIS_HOST:-localhost}"
REDIS_PORT="${REDIS_PORT:-6379}"
REDIS_PASSWORD="${REDIS_PASSWORD:-}"

# Application configuration
APP_PORT="${APP_PORT:-8080}"
APP_HOST="${APP_HOST:-0.0.0.0}"
APP_WORKERS="${APP_WORKERS:-4}"
APP_TIMEOUT="${APP_TIMEOUT:-30}"
APP_MAX_REQUESTS="${APP_MAX_REQUESTS:-1000}"
APP_KEEPALIVE="${APP_KEEPALIVE:-65}"

# Logging configuration
LOG_LEVEL="${LOG_LEVEL:-info}"
LOG_FORMAT="${LOG_FORMAT:-json}"
LOG_FILE="${LOG_FILE:-/var/log/app.log}"

# Feature flags
FEATURE_NEW_UI="${FEATURE_NEW_UI:-false}"
FEATURE_DARK_MODE="${FEATURE_DARK_MODE:-true}"
FEATURE_BETA_FEATURES="${FEATURE_BETA_FEATURES:-false}"
FEATURE_ANALYTICS="${FEATURE_ANALYTICS:-true}"
FEATURE_ADVANCED_LOGGING="${FEATURE_ADVANCED_LOGGING:-false}"

# ============================================================================
# Environment validation and setup
# ============================================================================

validate_environment() {
    local env="$1"
    
    if [[ -z "$env" ]]; then
        echo "ERROR: Environment not specified"
        return 1
    fi
    
    case "$env" in
        production|prod)
            echo "Setting up PRODUCTION environment"
            DB_HOST="prod-db-01"
            REDIS_HOST="prod-cache-01"
            APP_WORKERS="8"
            APP_MAX_REQUESTS="2000"
            LOG_LEVEL="warn"
            FEATURE_NEW_UI="false"
            FEATURE_BETA_FEATURES="false"
            FEATURE_ANALYTICS="true"
            FEATURE_ADVANCED_LOGGING="true"
            return 0
            ;;
        staging|stg)
            echo "Setting up STAGING environment"
            DB_HOST="staging-db-01"
            REDIS_HOST="staging-cache-01"
            APP_WORKERS="4"
            APP_MAX_REQUESTS="1000"
            LOG_LEVEL="info"
            FEATURE_NEW_UI="true"
            FEATURE_BETA_FEATURES="true"
            FEATURE_ANALYTICS="true"
            FEATURE_ADVANCED_LOGGING="true"
            return 0
            ;;
        development|dev)
            echo "Setting up DEVELOPMENT environment"
            DB_HOST="localhost"
            REDIS_HOST="localhost"
            APP_WORKERS="2"
            APP_MAX_REQUESTS="500"
            LOG_LEVEL="debug"
            FEATURE_NEW_UI="true"
            FEATURE_DARK_MODE="true"
            FEATURE_BETA_FEATURES="true"
            FEATURE_ANALYTICS="false"
            FEATURE_ADVANCED_LOGGING="true"
            return 0
            ;;
        testing|test)
            echo "Setting up TESTING environment"
            DB_HOST="test-db-01"
            REDIS_HOST="test-cache-01"
            APP_WORKERS="1"
            APP_MAX_REQUESTS="100"
            LOG_LEVEL="debug"
            FEATURE_NEW_UI="true"
            FEATURE_BETA_FEATURES="true"
            FEATURE_ANALYTICS="false"
            FEATURE_ADVANCED_LOGGING="false"
            return 0
            ;;
        *)
            echo "ERROR: Unknown environment: $env"
            echo "Valid environments: production, staging, development, testing"
            return 1
            ;;
    esac
}

load_env_file() {
    local env_file="$1"
    
    if [[ -z "$env_file" ]]; then
        echo "ERROR: Environment file path is required"
        return 1
    fi
    
    if [[ ! -f "$env_file" ]]; then
        echo "ERROR: Environment file not found: $env_file"
        return 2
    fi
    
    # Load the file
    if source "$env_file" 2>/dev/null; then
        echo "Loaded environment from: $env_file"
        return 0
    else
        echo "ERROR: Failed to load environment file: $env_file"
        return 3
    fi
}

get_env_value() {
    local key="$1"
    local default="$2"
    
    if [[ -z "$key" ]]; then
        echo "ERROR: Key is required"
        return 1
    fi
    
    local value="${!key}"
    
    if [[ -n "$value" ]]; then
        echo "$value"
        return 0
    elif [[ -n "$default" ]]; then
        echo "$default"
        return 0
    else
        echo "ERROR: Environment variable '$key' is not set"
        return 2
    fi
}

set_env_value() {
    local key="$1"
    local value="$2"
    
    if [[ -z "$key" ]]; then
        echo "ERROR: Key is required"
        return 1
    fi
    
    if [[ -z "$value" ]]; then
        echo "WARNING: Setting empty value for '$key'"
    fi
    
    export "$key=$value"
    echo "Set $key=$value"
    return 0
}

# ============================================================================
# Configuration validation
# ============================================================================

validate_config() {
    local env="$1"
    
    if [[ -z "$env" ]]; then
        echo "ERROR: Environment is required for validation"
        return 1
    fi
    
    # Check required variables
    local required_vars=(
        "DB_HOST"
        "DB_PORT"
        "DB_USER"
        "DB_NAME"
        "APP_PORT"
        "APP_HOST"
        "APP_WORKERS"
        "LOG_LEVEL"
    )
    
    local missing_vars=()
    for var in "${required_vars[@]}"; do
        if [[ -z "${!var}" ]]; then
            missing_vars+=("$var")
        fi
    done
    
    if [[ ${#missing_vars[@]} -gt 0 ]]; then
        echo "ERROR: Missing required environment variables:"
        for var in "${missing_vars[@]}"; do
            echo "  - $var"
        done
        return 2
    fi
    
    # Validate numeric values
    if [[ ! "$DB_PORT" =~ ^[0-9]+$ ]] || [[ "$DB_PORT" -lt 1 ]] || [[ "$DB_PORT" -gt 65535 ]]; then
        echo "ERROR: Invalid DB_PORT: $DB_PORT"
        return 3
    fi
    
    if [[ ! "$APP_PORT" =~ ^[0-9]+$ ]] || [[ "$APP_PORT" -lt 1 ]] || [[ "$APP_PORT" -gt 65535 ]]; then
        echo "ERROR: Invalid APP_PORT: $APP_PORT"
        return 3
    fi
    
    if [[ ! "$APP_WORKERS" =~ ^[0-9]+$ ]] || [[ "$APP_WORKERS" -lt 1 ]] || [[ "$APP_WORKERS" -gt 32 ]]; then
        echo "ERROR: Invalid APP_WORKERS: $APP_WORKERS (must be between 1 and 32)"
        return 3
    fi
    
    # Validate log level
    local valid_log_levels=("debug" "info" "warn" "error" "fatal")
    local is_valid=false
    for level in "${valid_log_levels[@]}"; do
        if [[ "$LOG_LEVEL" == "$level" ]]; then
            is_valid=true
            break
        fi
    done
    
    if [[ "$is_valid" == "false" ]]; then
        echo "ERROR: Invalid LOG_LEVEL: $LOG_LEVEL"
        echo "Valid values: ${valid_log_levels[*]}"
        return 4
    fi
    
    echo "✅ Configuration validation passed for environment: $env"
    return 0
}

# ============================================================================
# Point d'entrée (pour test direct)
# ============================================================================

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "=== ENVIRONMENT CONFIGURATION TEST ==="
    
    # Test 1: Validate production environment
    if validate_environment "production"; then
        echo "✅ Production environment validated"
    else
        echo "❌ Production environment validation failed"
    fi
    
    # Test 2: Validate development environment
    if validate_environment "development"; then
        echo "✅ Development environment validated"
    else
        echo "❌ Development environment validation failed"
    fi
    
    # Test 3: Validate config
    if validate_config "production"; then
        echo "✅ Config validation passed"
    else
        echo "❌ Config validation failed"
    fi
    
    # Test 4: Get env value
    if get_env_value "DB_HOST"; then
        echo "✅ DB_HOST is set"
    else
        echo "❌ DB_HOST is not set"
    fi
fi
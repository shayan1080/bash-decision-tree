#!/bin/bash
# Application configuration

# Global configuration
APP_NAME="MyApp"
APP_VERSION="1.0.0"
APP_ENV="${1:-development}"

# Feature flags
declare -A FEATURE_FLAGS
FEATURE_FLAGS["new_ui"]="${NEW_UI:-false}"
FEATURE_FLAGS["dark_mode"]="${DARK_MODE:-true}"
FEATURE_FLAGS["beta_features"]="${BETA_FEATURES:-false}"
FEATURE_FLAGS["analytics"]="${ANALYTICS:-true}"
FEATURE_FLAGS["advanced_logging"]="${ADVANCED_LOGGING:-false}"

# Application paths
APP_HOME="/opt/${APP_NAME}"
APP_DATA="${APP_HOME}/data"
APP_LOGS="${APP_HOME}/logs"
APP_CONFIG="${APP_HOME}/config"
APP_TEMP="${APP_HOME}/tmp"

# Application settings
APP_PORT="${APP_PORT:-8080}"
APP_HOST="${APP_HOST:-0.0.0.0}"
APP_WORKERS="${APP_WORKERS:-4}"
APP_MAX_REQUESTS="${APP_MAX_REQUESTS:-1000}"
APP_TIMEOUT="${APP_TIMEOUT:-30}"
APP_KEEPALIVE="${APP_KEEPALIVE:-65}"

# Feature-specific configuration
configure_features() {
    local environment="$1"
    
    case "${environment}" in
        production)
            FEATURE_FLAGS["new_ui"]="false"
            FEATURE_FLAGS["beta_features"]="false"
            FEATURE_FLAGS["analytics"]="true"
            FEATURE_FLAGS["advanced_logging"]="true"
            APP_WORKERS="8"
            APP_MAX_REQUESTS="2000"
            ;;
        staging)
            FEATURE_FLAGS["new_ui"]="true"
            FEATURE_FLAGS["beta_features"]="true"
            FEATURE_FLAGS["analytics"]="true"
            FEATURE_FLAGS["advanced_logging"]="true"
            APP_WORKERS="4"
            APP_MAX_REQUESTS="1000"
            ;;
        development)
            FEATURE_FLAGS["new_ui"]="true"
            FEATURE_FLAGS["dark_mode"]="true"
            FEATURE_FLAGS["beta_features"]="true"
            FEATURE_FLAGS["analytics"]="false"
            FEATURE_FLAGS["advanced_logging"]="true"
            APP_WORKERS="2"
            APP_MAX_REQUESTS="500"
            ;;
        *)
            log_error "Unknown environment: ${environment}"
            return 1
            ;;
    esac
    
    # Log feature flags
    log_info "Feature flags configured for ${environment}:"
    for flag in "${!FEATURE_FLAGS[@]}"; do
        log_info "  ${flag}=${FEATURE_FLAGS[${flag}]}"
    done
    
    return 0
}

# Validate configuration
validate_config() {
    local environment="$1"
    
    log_info "Validating configuration for ${environment}"
    
    # Check required directories
    local required_dirs=(
        "${APP_HOME}"
        "${APP_DATA}"
        "${APP_LOGS}"
        "${APP_CONFIG}"
        "${APP_TEMP}"
    )
    
    local missing_dirs=()
    for dir in "${required_dirs[@]}"; do
        if [[ ! -d "${dir}" ]]; then
            missing_dirs+=("${dir}")
        fi
    done
    
    if [[ ${#missing_dirs[@]} -gt 0 ]]; then
        log_error "Missing directories: ${missing_dirs[*]}"
        return 1
    fi
    
    # Check permissions
    if [[ ! -w "${APP_LOGS}" ]]; then
        log_error "Log directory ${APP_LOGS} is not writable"
        return 2
    fi
    
    if [[ ! -r "${APP_CONFIG}" ]]; then
        log_error "Config directory ${APP_CONFIG} is not readable"
        return 3
    fi
    
    # Validate port
    if [[ ${APP_PORT} -lt 1 ]] || [[ ${APP_PORT} -gt 65535 ]]; then
        log_error "Invalid port: ${APP_PORT}"
        return 4
    fi
    
    # Validate workers
    if [[ ${APP_WORKERS} -lt 1 ]] || [[ ${APP_WORKERS} -gt 32 ]]; then
        log_error "Invalid worker count: ${APP_WORKERS}"
        return 5
    fi
    
    log_info "Configuration validation successful"
    return 0
}
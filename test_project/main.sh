#!/bin/bash
# Main entry point for the deployment system

set -euo pipefail

# Source all dependencies
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/network.sh"
source "${SCRIPT_DIR}/lib/database.sh"
source "${SCRIPT_DIR}/lib/deployment.sh"
source "${SCRIPT_DIR}/lib/monitoring.sh"
source "${SCRIPT_DIR}/config/app_config.sh"
source "${SCRIPT_DIR}/config/env_config.sh"
source "${SCRIPT_DIR}/scripts/backup.sh"
source "${SCRIPT_DIR}/scripts/cleanup.sh"

# Global variables
DEPLOYMENT_ID=$(date +%Y%m%d_%H%M%S)
LOG_FILE="/var/log/deployment_${DEPLOYMENT_ID}.log"
RETRY_COUNT=3
TIMEOUT=30

# Main deployment function
deploy_system() {
    local environment="$1"
    local version="$2"
    local force="${3:-false}"
    
    log_info "Starting deployment of version ${version} to ${environment}"
    
    # Pre-deployment checks
    if ! pre_deployment_checks "${environment}"; then
        log_error "Pre-deployment checks failed"
        return 1
    fi
    
    # Create backup before deployment
    if ! create_backup "${environment}" "${version}"; then
        log_error "Backup creation failed"
        return 2
    fi
    
    # Main deployment steps
    if [[ "${environment}" == "production" ]]; then
        if [[ "${force}" == "true" ]]; then
            deploy_production_force "${version}"
        else
            deploy_production_safe "${version}"
        fi
    elif [[ "${environment}" == "staging" ]]; then
        deploy_staging "${version}"
    elif [[ "${environment}" == "development" ]]; then
        deploy_development "${version}"
    else
        log_error "Unknown environment: ${environment}"
        return 3
    fi
    
    local deploy_result=$?
    
    # Post-deployment
    if [[ ${deploy_result} -eq 0 ]]; then
        if ! post_deployment_verify "${environment}" "${version}"; then
            log_error "Post-deployment verification failed"
            if [[ "${environment}" == "production" ]]; then
                rollback_production "${version}"
                return 4
            fi
            return 5
        fi
        
        # Start monitoring
        start_monitoring "${environment}" "${version}" &
    else
        log_error "Deployment failed with code ${deploy_result}"
        handle_deployment_failure "${environment}" "${version}" "${deploy_result}"
        return ${deploy_result}
    fi
    
    log_info "Deployment completed successfully"
    return 0
}

# Pre-deployment checks
pre_deployment_checks() {
    local environment="$1"
    
    log_info "Running pre-deployment checks for ${environment}"
    
    # Check network connectivity
    if ! check_network_connectivity "${environment}"; then
        log_error "Network connectivity check failed"
        return 1
    fi
    
    # Check database connectivity
    if ! check_database_connectivity "${environment}"; then
        log_error "Database connectivity check failed"
        return 2
    fi
    
    # Check disk space
    if ! check_disk_space "${environment}"; then
        log_error "Insufficient disk space"
        return 3
    fi
    
    # Check version compatibility
    if ! check_version_compatibility "${environment}" "${version}"; then
        log_error "Version compatibility check failed"
        return 4
    fi
    
    # Check if any existing deployment is running
    if check_deployment_lock "${environment}"; then
        log_error "Another deployment is already running"
        return 5
    fi
    
    # Acquire deployment lock
    if ! acquire_deployment_lock "${environment}"; then
        log_error "Failed to acquire deployment lock"
        return 6
    fi
    
    return 0
}

# Safe production deployment (with canary)
deploy_production_safe() {
    local version="$1"
    
    log_info "Starting safe production deployment for version ${version}"
    
    # Canary deployment (1% of traffic)
    if ! canary_deploy "${version}" "1"; then
        log_error "Canary deployment failed"
        return 1
    fi
    
    # Monitor canary for 5 minutes
    if ! monitor_canary "${version}" 300; then
        log_error "Canary monitoring failed - rolling back"
        rollback_canary "${version}"
        return 2
    fi
    
    # Increase to 10%
    if ! canary_deploy "${version}" "10"; then
        log_error "Canary phase 2 failed"
        rollback_canary "${version}"
        return 3
    fi
    
    # Monitor for 2 minutes
    if ! monitor_canary "${version}" 120; then
        log_error "Canary phase 2 monitoring failed"
        rollback_canary "${version}"
        return 4
    fi
    
    # Full deployment
    if ! full_deploy "${version}"; then
        log_error "Full deployment failed"
        rollback_production "${version}"
        return 5
    fi
    
    return 0
}

# Force production deployment (no canary)
deploy_production_force() {
    local version="$1"
    
    log_warn "FORCE deploying version ${version} to production (no canary)"
    
    # Check if maintenance mode is required
    if is_maintenance_required "${version}"; then
        log_info "Maintenance mode required for this version"
        enable_maintenance_mode
        local maintenance_enabled=true
    else
        local maintenance_enabled=false
    fi
    
    # Deploy directly
    if ! full_deploy "${version}"; then
        log_error "Force deployment failed"
        if [[ "${maintenance_enabled}" == "true" ]]; then
            disable_maintenance_mode
        fi
        return 1
    fi
    
    if [[ "${maintenance_enabled}" == "true" ]]; then
        disable_maintenance_mode
    fi
    
    return 0
}

# Staging deployment
deploy_staging() {
    local version="$1"
    
    log_info "Deploying version ${version} to staging"
    
    # Staging can have more aggressive deployment
    if ! full_deploy "${version}"; then
        log_error "Staging deployment failed"
        return 1
    fi
    
    # Run integration tests
    if ! run_integration_tests "${version}"; then
        log_error "Integration tests failed"
        return 2
    fi
    
    return 0
}

# Development deployment
deploy_development() {
    local version="$1"
    
    log_info "Deploying version ${version} to development"
    
    # Dev deployment is simpler
    if ! dev_deploy "${version}"; then
        log_error "Development deployment failed"
        return 1
    fi
    
    # Run unit tests
    if ! run_unit_tests "${version}"; then
        log_error "Unit tests failed"
        return 2
    fi
    
    return 0
}

# Post-deployment verification
post_deployment_verify() {
    local environment="$1"
    local version="$2"
    
    log_info "Running post-deployment verification for ${environment}"
    
    local checks_passed=0
    local checks_failed=0
    
    # Health check
    if health_check "${environment}" "${version}"; then
        ((checks_passed++))
    else
        log_error "Health check failed"
        ((checks_failed++))
    fi
    
    # Database schema check
    if check_database_schema "${environment}" "${version}"; then
        ((checks_passed++))
    else
        log_error "Database schema check failed"
        ((checks_failed++))
    fi
    
    # Service availability check
    if check_services "${environment}" "${version}"; then
        ((checks_passed++))
    else
        log_error "Service availability check failed"
        ((checks_failed++))
    fi
    
    # Performance check
    if check_performance "${environment}" "${version}"; then
        ((checks_passed++))
    else
        log_error "Performance check failed"
        ((checks_failed++))
    fi
    
    # Security check
    if check_security "${environment}" "${version}"; then
        ((checks_passed++))
    else
        log_error "Security check failed"
        ((checks_failed++))
    fi
    
    log_info "Verification complete: ${checks_passed} passed, ${checks_failed} failed"
    
    if [[ ${checks_failed} -gt 0 ]]; then
        return 1
    fi
    
    return 0
}

# Handle deployment failure
handle_deployment_failure() {
    local environment="$1"
    local version="$2"
    local error_code="$3"
    
    log_error "Handling deployment failure: ${error_code}"
    
    case ${error_code} in
        1)
            log_error "Pre-deployment checks failed - cleaning up"
            cleanup_failed_deployment "${environment}" "${version}"
            ;;
        2)
            log_error "Backup creation failed - no rollback needed"
            notify_admin "Backup failed for ${environment}"
            ;;
        3)
            log_error "Unknown environment - configuration error"
            notify_admin "Invalid environment: ${environment}"
            ;;
        4)
            log_error "Deployment failed - rolling back"
            rollback_production "${version}"
            ;;
        5)
            log_error "Post-deployment verification failed"
            rollback_production "${version}"
            notify_admin "Verification failed for ${environment}"
            ;;
        *)
            log_error "Unknown error - performing emergency cleanup"
            emergency_cleanup "${environment}" "${version}"
            notify_admin "Emergency cleanup required for ${environment}"
            ;;
    esac
    
    # Always release deployment lock
    release_deployment_lock "${environment}"
    
    # Send alert
    send_alert "Deployment failed: ${environment} ${version} (${error_code})"
}

# Logging functions
log_info() {
    local message="$1"
    echo "[INFO] $(date -Iseconds) - ${message}" | tee -a "${LOG_FILE}"
}

log_error() {
    local message="$1"
    echo "[ERROR] $(date -Iseconds) - ${message}" | tee -a "${LOG_FILE}" >&2
}

log_warn() {
    local message="$1"
    echo "[WARN] $(date -Iseconds) - ${message}" | tee -a "${LOG_FILE}"
}

# Main execution
main() {
    local environment="${1:-development}"
    local version="${2:-latest}"
    local force="${3:-false}"
    
    log_info "=== Deployment System Started ==="
    log_info "Environment: ${environment}"
    log_info "Version: ${version}"
    log_info "Force: ${force}"
    
    # Validate environment
    case "${environment}" in
        production|staging|development)
            ;;
        *)
            log_error "Invalid environment: ${environment}"
            echo "Usage: $0 <environment> [version] [force]"
            echo "Valid environments: production, staging, development"
            exit 1
            ;;
    esac
    
    # Check if script is run as root
    if [[ $EUID -eq 0 ]]; then
        log_warn "Running as root - this is not recommended"
    fi
    
    # Execute deployment
    if deploy_system "${environment}" "${version}" "${force}"; then
        log_info "Deployment system finished successfully"
        exit 0
    else
        log_error "Deployment system finished with errors"
        exit 1
    fi
}

# Only run if executed directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
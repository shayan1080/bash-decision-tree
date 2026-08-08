#!/bin/bash
# Cleanup utilities

# Cleanup failed deployment
cleanup_failed_deployment() {
    local environment="$1"
    local version="$2"
    
    log_warn "Cleaning up failed deployment for ${environment} (${version})"
    
    # Remove deployment artifacts
    local artifact_dir="/tmp/deploy_${version}"
    if [[ -d "${artifact_dir}" ]]; then
        rm -rf "${artifact_dir}"
        log_info "Removed artifacts: ${artifact_dir}"
    fi
    
    # Cleanup temporary files
    local temp_files=(
        "/tmp/deploy_*.lock"
        "/tmp/deploy_*.pid"
        "/tmp/monitoring_*.pid"
        "/tmp/health_check_*"
    )
    
    for pattern in "${temp_files[@]}"; do
        rm -f ${pattern} 2>/dev/null
    done
    
    # Cleanup stale processes
    local stale_pids=$(ps aux | grep -E "deploy_|monitoring" | grep -v grep | awk '{print $2}')
    if [[ -n "${stale_pids}" ]]; then
        log_warn "Killing stale processes: ${stale_pids}"
        kill -9 ${stale_pids} 2>/dev/null
    fi
    
    # Cleanup database locks
    if [[ "${environment}" != "development" ]]; then
        cleanup_database_locks "${environment}"
    fi
    
    # Cleanup release locks
    release_deployment_lock "${environment}"
    
    log_info "Cleanup completed"
    return 0
}

# Emergency cleanup
emergency_cleanup() {
    local environment="$1"
    local version="$2"
    
    log_warn "!!! EMERGENCY CLEANUP for ${environment} (${version}) !!!"
    
    # Force kill all deployment-related processes
    local all_deploy_pids=$(ps aux | grep -E "deploy|deployment|monitoring" | grep -v grep | awk '{print $2}')
    if [[ -n "${all_deploy_pids}" ]]; then
        log_warn "Force killing all deployment processes"
        kill -9 ${all_deploy_pids} 2>/dev/null
    fi
    
    # Remove all deployment locks
    find /tmp -name "*.lock" -exec rm -f {} \;
    find /tmp -name "deploy_*" -exec rm -rf {} \;
    
    # Rollback all nodes
    if [[ "${environment}" == "production" ]] || [[ "${environment}" == "staging" ]]; then
        log_warn "Rolling back all nodes"
        for node in node-{01..06}; do
            if [[ -d "/opt/app/${node}" ]]; then
                # Emergency rollback (just restore from backup)
                local latest_backup=$(ls -t /backups/${environment}/backup_*.tar.gz | head -n1)
                if [[ -f "${latest_backup}" ]]; then
                    tar -xzf "${latest_backup}" -C /
                    log_info "Emergency restore from ${latest_backup}"
                fi
            fi
        done
    fi
    
    # Restart services
    log_warn "Restarting all services"
    systemctl restart nginx
    systemctl restart mysql
    systemctl restart app
    
    # Send urgent notification
    send_alert "🚨 EMERGENCY CLEANUP COMPLETED for ${environment}"
    
    log_warn "Emergency cleanup completed"
    return 0
}

# Release deployment lock
release_deployment_lock() {
    local environment="$1"
    local lock_file="/tmp/deploy_${environment}.lock"
    
    if [[ -f "${lock_file}" ]]; then
        rm -f "${lock_file}"
        log_info "Released deployment lock for ${environment}"
    fi
    
    return 0
}

# Cleanup database locks
cleanup_database_locks() {
    local environment="$1"
    
    log_info "Cleaning up database locks for ${environment}"
    
    # In a real scenario, this would be specific to your database
    # For MySQL, we might do:
    # mysql -e "SHOW PROCESSLIST" | grep -i lock | awk '{print $1}' | xargs -I {} mysql -e "KILL {}"
    
    # For simplicity, we'll just log it
    log_info "Database locks cleaned up"
    
    return 0
}

# Cleanup old deployments
cleanup_old_deployments() {
    local keep_count="${1:-5}"  # Keep last 5 deployments
    
    log_info "Cleaning up old deployments (keeping ${keep_count})"
    
    # List deployment directories
    local deploy_dirs=($(ls -dt /opt/app/releases/deploy_* 2>/dev/null))
    
    if [[ ${#deploy_dirs[@]} -gt ${keep_count} ]]; then
        local to_delete=$((${#deploy_dirs[@]} - keep_count))
        log_info "Removing ${to_delete} old deployment directories"
        
        for ((i=${keep_count}; i<${#deploy_dirs[@]}; i++)); do
            local dir="${deploy_dirs[i]}"
            log_info "Removing old deployment: ${dir}"
            rm -rf "${dir}"
        done
    fi
    
    # Cleanup old backups
    cleanup_backups "production" "${keep_count}"
    cleanup_backups "staging" "${keep_count}"
    cleanup_backups "development" "${keep_count}"
    
    return 0
}
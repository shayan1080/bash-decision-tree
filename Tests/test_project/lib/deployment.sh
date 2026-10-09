#!/bin/bash
# Core deployment functions

# Canary deployment
canary_deploy() {
    local version="$1"
    local percentage="$2"
    
    log_info "Starting canary deployment: ${version} to ${percentage}% of traffic"
    
    # Validate percentage
    if [[ ${percentage} -lt 1 ]] || [[ ${percentage} -gt 100 ]]; then
        log_error "Invalid canary percentage: ${percentage}"
        return 1
    fi
    
    # Check if canary version exists
    if ! version_exists "${version}"; then
        log_error "Version ${version} not found in registry"
        return 2
    fi
    
    # Deploy to canary nodes
    local canary_nodes=()
    if [[ "${percentage}" -le 10 ]]; then
        canary_nodes=("node-01" "node-02")
    elif [[ "${percentage}" -le 30 ]]; then
        canary_nodes=("node-01" "node-02" "node-03" "node-04")
    else
        canary_nodes=("node-01" "node-02" "node-03" "node-04" "node-05" "node-06")
    fi
    
    local failed_nodes=()
    for node in "${canary_nodes[@]}"; do
        if ! deploy_to_node "${node}" "${version}"; then
            failed_nodes+=("${node}")
        fi
    done
    
    if [[ ${#failed_nodes[@]} -gt 0 ]]; then
        log_error "Canary deployment failed on nodes: ${failed_nodes[*]}"
        return 3
    fi
    
    # Update load balancer
    if ! update_load_balancer "${percentage}"; then
        log_error "Failed to update load balancer for canary"
        return 4
    fi
    
    return 0
}

# Full deployment
full_deploy() {
    local version="$1"
    
    log_info "Starting full deployment: ${version}"
    
    # Deploy to all nodes
    local all_nodes=("node-01" "node-02" "node-03" "node-04" "node-05" "node-06")
    local failed_nodes=()
    
    for node in "${all_nodes[@]}"; do
        if ! deploy_to_node "${node}" "${version}"; then
            failed_nodes+=("${node}")
            # Check if we should stop on failure
            if [[ "${ROLLBACK_ON_FAILURE:-true}" == "true" ]]; then
                log_error "Rolling back due to failure on ${node}"
                for rollback_node in "${all_nodes[@]}"; do
                    if [[ "${rollback_node}" != "${node}" ]]; then
                        rollback_node "${rollback_node}" "${version}"
                    fi
                done
                return 1
            fi
        fi
    done
    
    if [[ ${#failed_nodes[@]} -gt 0 ]]; then
        log_error "Full deployment failed on: ${failed_nodes[*]}"
        return 2
    fi
    
    # Update load balancer to 100%
    if ! update_load_balancer "100"; then
        log_error "Failed to update load balancer to 100%"
        return 3
    fi
    
    return 0
}

# Deploy to specific node
deploy_to_node() {
    local node="$1"
    local version="$2"
    
    log_info "Deploying to ${node}: ${version}"
    
    # Check if node is healthy
    if ! check_node_health "${node}"; then
        log_error "Node ${node} is not healthy"
        return 1
    fi
    
    # Download artifacts
    if ! download_artifacts "${node}" "${version}"; then
        log_error "Failed to download artifacts for ${node}"
        return 2
    fi
    
    # Stop services
    if ! stop_services "${node}"; then
        log_error "Failed to stop services on ${node}"
        return 3
    fi
    
    # Install version
    if ! install_version "${node}" "${version}"; then
        log_error "Failed to install ${version} on ${node}"
        # Attempt to restart services with old version
        start_services "${node}"
        return 4
    fi
    
    # Start services
    if ! start_services "${node}"; then
        log_error "Failed to start services on ${node}"
        # Rollback to previous version
        rollback_node "${node}" "${version}"
        return 5
    fi
    
    # Verify deployment on node
    if ! verify_node_deployment "${node}" "${version}"; then
        log_error "Deployment verification failed on ${node}"
        rollback_node "${node}" "${version}"
        return 6
    fi
    
    return 0
}

# Rollback production
rollback_production() {
    local version="$1"
    
    log_warn "ROLLING BACK production to previous version"
    
    # Get previous version
    local previous_version=$(get_previous_version "${version}")
    if [[ -z "${previous_version}" ]]; then
        log_error "No previous version found for rollback"
        return 1
    fi
    
    # Rollback all nodes
    local all_nodes=("node-01" "node-02" "node-03" "node-04" "node-05" "node-06")
    local failed_rollbacks=()
    
    for node in "${all_nodes[@]}"; do
        if ! rollback_node "${node}" "${version}"; then
            failed_rollbacks+=("${node}")
        fi
    done
    
    if [[ ${#failed_rollbacks[@]} -gt 0 ]]; then
        log_error "Rollback failed on: ${failed_rollbacks[*]}"
        return 2
    fi
    
    # Update load balancer
    if ! update_load_balancer "0"; then
        log_error "Failed to update load balancer after rollback"
        return 3
    fi
    
    log_info "Rollback completed successfully"
    return 0
}

# Rollback canary
rollback_canary() {
    local version="$1"
    
    log_warn "ROLLING BACK canary deployment"
    
    # Remove canary nodes
    local canary_nodes=("node-01" "node-02")
    local failed_rollbacks=()
    
    for node in "${canary_nodes[@]}"; do
        if ! rollback_node "${node}" "${version}"; then
            failed_rollbacks+=("${node}")
        fi
    done
    
    if [[ ${#failed_rollbacks[@]} -gt 0 ]]; then
        log_error "Canary rollback failed on: ${failed_rollbacks[*]}"
        return 1
    fi
    
    # Reset load balancer
    if ! update_load_balancer "0"; then
        log_error "Failed to reset load balancer after canary rollback"
        return 2
    fi
    
    return 0
}

# Rollback a specific node
rollback_node() {
    local node="$1"
    local failed_version="$2"
    
    log_warn "Rolling back ${node} from ${failed_version}"
    
    # Stop services
    if ! stop_services "${node}"; then
        log_error "Failed to stop services on ${node} for rollback"
        return 1
    fi
    
    # Restore previous version
    if ! restore_previous_version "${node}"; then
        log_error "Failed to restore previous version on ${node}"
        return 2
    fi
    
    # Start services
    if ! start_services "${node}"; then
        log_error "Failed to start services on ${node} after rollback"
        return 3
    fi
    
    # Verify rollback
    if ! verify_node_health "${node}"; then
        log_error "Node ${node} is unhealthy after rollback"
        return 4
    fi
    
    return 0
}
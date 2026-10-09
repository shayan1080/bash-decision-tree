#!/bin/bash
# Network utilities and checks

# Check network connectivity
check_network_connectivity() {
    local environment="$1"
    local hosts=()
    
    case "${environment}" in
        production)
            hosts=("prod-api-01" "prod-api-02" "prod-db-01" "prod-cache-01")
            ;;
        staging)
            hosts=("staging-api-01" "staging-db-01")
            ;;
        development)
            hosts=("dev-api-01" "dev-db-01")
            ;;
        *)
            return 1
            ;;
    esac
    
    local failed_hosts=()
    for host in "${hosts[@]}"; do
        if ! ping -c 1 -W 2 "${host}" >/dev/null 2>&1; then
            failed_hosts+=("${host}")
        fi
    done
    
    if [[ ${#failed_hosts[@]} -gt 0 ]]; then
        log_error "Failed to connect to: ${failed_hosts[*]}"
        return 1
    fi
    
    return 0
}

# Check service health via HTTP
health_check() {
    local environment="$1"
    local version="$2"
    local endpoints=()
    
    # Configure endpoints based on environment
    if [[ "${environment}" == "production" ]]; then
        endpoints=(
            "https://api.example.com/health"
            "https://api.example.com/ready"
            "https://admin.example.com/health"
        )
    elif [[ "${environment}" == "staging" ]]; then
        endpoints=(
            "https://staging-api.example.com/health"
            "https://staging-admin.example.com/health"
        )
    else
        endpoints=(
            "http://localhost:8080/health"
            "http://localhost:8081/health"
        )
    fi
    
    local retry=0
    local max_retries=5
    local timeout=10
    
    for endpoint in "${endpoints[@]}"; do
        local success=false
        for ((retry=1; retry<=max_retries; retry++)); do
            if curl -s -f -o /dev/null -w "%{http_code}" --max-time "${timeout}" "${endpoint}" | grep -q "^2"; then
                success=true
                break
            fi
            sleep 2
        done
        
        if [[ "${success}" != "true" ]]; then
            log_error "Health check failed for ${endpoint} after ${max_retries} attempts"
            return 1
        fi
    done
    
    return 0
}

# Check service availability
check_services() {
    local environment="$1"
    local version="$2"
    local services=()
    
    # Define required services
    if [[ "${environment}" == "production" ]]; then
        services=("nginx" "mysql" "redis" "elasticsearch" "kafka")
    elif [[ "${environment}" == "staging" ]]; then
        services=("nginx" "mysql" "redis")
    else
        services=("nginx" "mysql")
    fi
    
    local failed_services=()
    for service in "${services[@]}"; do
        if ! systemctl is-active --quiet "${service}"; then
            failed_services+=("${service}")
        fi
    done
    
    if [[ ${#failed_services[@]} -gt 0 ]]; then
        log_error "Services not running: ${failed_services[*]}"
        return 1
    fi
    
    return 0
}

# Check performance metrics
check_performance() {
    local environment="$1"
    local version="$2"
    local thresholds=()
    
    # Configure thresholds based on environment
    if [[ "${environment}" == "production" ]]; then
        thresholds=(
            "cpu_usage:80"
            "memory_usage:90"
            "disk_usage:85"
            "response_time:500"
            "error_rate:1"
        )
    elif [[ "${environment}" == "staging" ]]; then
        thresholds=(
            "cpu_usage:85"
            "memory_usage:95"
            "disk_usage:90"
            "response_time:1000"
        )
    else
        thresholds=(
            "cpu_usage:90"
            "memory_usage:95"
            "disk_usage:95"
            "response_time:2000"
        )
    fi
    
    local failed_checks=()
    for threshold in "${thresholds[@]}"; do
        local metric="${threshold%:*}"
        local max_value="${threshold#*:}"
        
        case "${metric}" in
            cpu_usage)
                local current_cpu=$(top -bn1 | grep "Cpu(s)" | awk '{print $2}' | cut -d. -f1)
                if [[ ${current_cpu} -gt ${max_value} ]]; then
                    failed_checks+=("CPU usage: ${current_cpu}% > ${max_value}%")
                fi
                ;;
            memory_usage)
                local current_memory=$(free | grep Mem | awk '{printf("%.0f"), $3/$2 * 100}')
                if [[ ${current_memory} -gt ${max_value} ]]; then
                    failed_checks+=("Memory usage: ${current_memory}% > ${max_value}%")
                fi
                ;;
            disk_usage)
                local current_disk=$(df -h / | awk 'NR==2 {print $5}' | cut -d% -f1)
                if [[ ${current_disk} -gt ${max_value} ]]; then
                    failed_checks+=("Disk usage: ${current_disk}% > ${max_value}%")
                fi
                ;;
            response_time)
                local avg_response=$(curl -s -o /dev/null -w "%{time_total}" http://localhost/ | cut -d. -f1)
                if [[ ${avg_response} -gt ${max_value} ]]; then
                    failed_checks+=("Response time: ${avg_response}ms > ${max_value}ms")
                fi
                ;;
            error_rate)
                local error_rate=$(grep -c "ERROR" "${LOG_FILE}" 2>/dev/null || echo "0")
                local total_requests=$(grep -c "REQUEST" "${LOG_FILE}" 2>/dev/null || echo "1")
                local current_rate=$((error_rate * 100 / total_requests))
                if [[ ${current_rate} -gt ${max_value} ]]; then
                    failed_checks+=("Error rate: ${current_rate}% > ${max_value}%")
                fi
                ;;
        esac
    done
    
    if [[ ${#failed_checks[@]} -gt 0 ]]; then
        log_error "Performance checks failed:"
        for check in "${failed_checks[@]}"; do
            log_error "  - ${check}"
        done
        return 1
    fi
    
    return 0
}
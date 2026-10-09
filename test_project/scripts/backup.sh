#!/bin/bash
# Backup utilities

# Create backup
create_backup() {
    local environment="$1"
    local version="$2"
    
    log_info "Creating backup for ${environment} before deployment"
    
    local backup_dir="/backups/${environment}"
    local timestamp=$(date +%Y%m%d_%H%M%S)
    local backup_file="${backup_dir}/backup_${timestamp}_${version}.tar.gz"
    
    # Ensure backup directory exists
    if [[ ! -d "${backup_dir}" ]]; then
        mkdir -p "${backup_dir}"
        if [[ $? -ne 0 ]]; then
            log_error "Failed to create backup directory: ${backup_dir}"
            return 1
        fi
    fi
    
    # Check available space
    local available_space=$(df -BG "${backup_dir}" | awk 'NR==2 {print $4}' | sed 's/G//')
    local required_space=10  # GB
    
    if [[ ${available_space} -lt ${required_space} ]]; then
        log_error "Insufficient space for backup: ${available_space}GB available, ${required_space}GB required"
        return 2
    fi
    
    # Backup configuration
    if ! tar -czf "${backup_file}" -C /etc "${APP_NAME}" 2>/dev/null; then
        log_error "Failed to backup configuration"
        return 3
    fi
    
    # Backup database
    if ! backup_database "${environment}" "${backup_file}.db"; then
        log_error "Failed to backup database"
        return 4
    fi
    
    # Backup application data
    if ! tar -czf "${backup_file}.data" -C "${APP_DATA}" . 2>/dev/null; then
        log_error "Failed to backup application data"
        return 5
    fi
    
    # Create manifest
    local manifest="${backup_dir}/manifest_${timestamp}.txt"
    cat > "${manifest}" <<EOF
Backup created: $(date)
Environment: ${environment}
Version: ${version}
Files:
  - ${backup_file}
  - ${backup_file}.db
  - ${backup_file}.data
EOF
    
    # Verify backup integrity
    if ! verify_backup "${backup_file}"; then
        log_error "Backup verification failed"
        return 6
    fi
    
    log_info "Backup created successfully: ${backup_file}"
    return 0
}

# Backup database
backup_database() {
    local environment="$1"
    local backup_file="$2"
    
    log_info "Backing up database for ${environment}"
    
    # Configure database credentials based on environment
    local db_host="localhost"
    local db_user="backup_user"
    local db_password=""
    local databases=()
    
    case "${environment}" in
        production)
            db_host="prod-db-01"
            databases=("prod_app" "prod_analytics" "prod_audit")
            ;;
        staging)
            db_host="staging-db-01"
            databases=("staging_app" "staging_analytics")
            ;;
        development)
            db_host="localhost"
            databases=("dev_app" "dev_test")
            ;;
        *)
            return 1
            ;;
    esac
    
    # Backup each database
    local failed_backups=()
    for db in "${databases[@]}"; do
        if ! mysqldump -h "${db_host}" -u "${db_user}" --password="${db_password}" \
            --single-transaction --routines --triggers "${db}" >> "${backup_file}" 2>/dev/null; then
            failed_backups+=("${db}")
        fi
    done
    
    if [[ ${#failed_backups[@]} -gt 0 ]]; then
        log_error "Failed to backup databases: ${failed_backups[*]}"
        return 1
    fi
    
    return 0
}

# Verify backup
verify_backup() {
    local backup_file="$1"
    
    # Check if backup file exists
    if [[ ! -f "${backup_file}" ]]; then
        log_error "Backup file does not exist: ${backup_file}"
        return 1
    fi
    
    # Check file size (must be > 1KB)
    local file_size=$(stat -c%s "${backup_file}" 2>/dev/null || stat -f%z "${backup_file}" 2>/dev/null)
    if [[ ${file_size} -lt 1024 ]]; then
        log_error "Backup file is too small: ${file_size} bytes"
        return 2
    fi
    
    # Test decompression
    if ! tar -tzf "${backup_file}" >/dev/null 2>&1; then
        log_error "Backup file is corrupt or not a valid tar.gz"
        return 3
    fi
    
    return 0
}

# Cleanup old backups
cleanup_backups() {
    local environment="$1"
    local keep_count="${2:-7}"  # Keep last 7 backups by default
    
    local backup_dir="/backups/${environment}"
    
    if [[ ! -d "${backup_dir}" ]]; then
        log_warn "Backup directory does not exist: ${backup_dir}"
        return 0
    fi
    
    # List backups sorted by date (newest first)
    local backup_files=($(ls -t "${backup_dir}"/backup_*.tar.gz 2>/dev/null))
    
    if [[ ${#backup_files[@]} -gt ${keep_count} ]]; then
        local to_delete=$((${#backup_files[@]} - keep_count))
        log_info "Cleaning up ${to_delete} old backups"
        
        for ((i=${keep_count}; i<${#backup_files[@]}; i++)); do
            local file="${backup_files[i]}"
            log_info "Removing old backup: ${file}"
            rm -f "${file}"
            rm -f "${file}.db"
            rm -f "${file}.data"
            rm -f "$(dirname "${file}")/manifest_$(basename "${file}" .tar.gz).txt"
        done
    fi
    
    return 0
}
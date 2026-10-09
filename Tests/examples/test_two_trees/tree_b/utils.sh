#!/bin/bash
# utils.sh - ابزارهای محاسباتی و رشته‌ای (درخت مستقل، بدون ارتباط با app.sh)

# ============================================
# توابع محاسباتی
# ============================================

calculate_sum() {
    local a="$1"
    local b="$2"
    
    if [[ -z "$a" ]] || [[ -z "$b" ]]; then
        echo "ERROR: Both numbers are required"
        return 1
    fi
    
    if [[ ! "$a" =~ ^-?[0-9]+$ ]] || [[ ! "$b" =~ ^-?[0-9]+$ ]]; then
        echo "ERROR: Invalid numbers: $a, $b"
        return 2
    fi
    
    local sum=$((a + b))
    echo "Sum: $sum"
    return 0
}

calculate_factorial() {
    local n="$1"
    
    if [[ -z "$n" ]]; then
        echo "ERROR: Number is required"
        return 1
    fi
    
    if [[ ! "$n" =~ ^[0-9]+$ ]]; then
        echo "ERROR: Invalid number: $n"
        return 2
    fi
    
    if [[ "$n" -eq 0 ]] || [[ "$n" -eq 1 ]]; then
        echo "Factorial: 1"
        return 0
    else
        local result=1
        for ((i=2; i<=n; i++)); do
            result=$((result * i))
        done
        echo "Factorial: $result"
        return 0
    fi
}

is_prime() {
    local n="$1"
    
    if [[ -z "$n" ]]; then
        echo "ERROR: Number is required"
        return 1
    fi
    
    if [[ ! "$n" =~ ^[0-9]+$ ]]; then
        echo "ERROR: Invalid number: $n"
        return 2
    fi
    
    if [[ "$n" -lt 2 ]]; then
        echo "$n is NOT prime"
        return 1
    fi
    
    local is_prime=true
    for ((i=2; i*i<=n; i++)); do
        if [[ $((n % i)) -eq 0 ]]; then
            is_prime=false
            break
        fi
    done
    
    if [[ "$is_prime" == "true" ]]; then
        echo "$n is prime"
        return 0
    else
        echo "$n is NOT prime"
        return 1
    fi
}

# ============================================
# توابع رشته‌ای
# ============================================

reverse_string() {
    local str="$1"
    
    if [[ -z "$str" ]]; then
        echo "ERROR: String is required"
        return 1
    fi
    
    local reversed=""
    for ((i=${#str}-1; i>=0; i--)); do
        reversed="${reversed}${str:$i:1}"
    done
    
    echo "Reversed: $reversed"
    return 0
}

to_uppercase() {
    local str="$1"
    
    if [[ -z "$str" ]]; then
        echo "ERROR: String is required"
        return 1
    fi
    
    echo "${str^^}"
    return 0
}

to_lowercase() {
    local str="$1"
    
    if [[ -z "$str" ]]; then
        echo "ERROR: String is required"
        return 1
    fi
    
    echo "${str,,}"
    return 0
}

# ============================================
# نقطه ورود - ابزارهای محاسباتی
# ============================================

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "=== UTILITY TOOLS ==="
    
    # Test calculate_sum
    if calculate_sum 5 3; then
        echo "Sum test passed"
    else
        echo "Sum test failed"
    fi
    
    # Test calculate_factorial
    if calculate_factorial 5; then
        echo "Factorial test passed"
    else
        echo "Factorial test failed"
    fi
    
    # Test is_prime
    if is_prime 7; then
        echo "Prime test passed"
    else
        echo "Prime test failed"
    fi
    
    # Test reverse_string
    if reverse_string "hello"; then
        echo "Reverse test passed"
    else
        echo "Reverse test failed"
    fi
fi
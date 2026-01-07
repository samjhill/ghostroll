#!/usr/bin/env python3
"""
Cost analysis for Lambda image enhancement.
Calculates estimated costs and identifies optimization opportunities.
"""

def calculate_lambda_costs():
    """Calculate estimated Lambda costs."""
    print("=== Lambda Cost Analysis ===\n")
    
    # AWS Lambda pricing (us-east-1, as of 2024)
    INVOCATION_COST = 0.20 / 1_000_000  # $0.20 per 1M requests
    COMPUTE_COST_PER_GB_SEC = 0.0000166667  # $0.0000166667 per GB-second
    
    # Configuration
    MEMORY_GB = 1.0  # 1024 MB
    AVG_DURATION_SEC = 2.0  # Average processing time
    IMAGES_PER_MONTH = 1000  # Example: 1000 images/month
    
    # Calculate costs
    invocations_cost = IMAGES_PER_MONTH * INVOCATION_COST
    compute_cost = IMAGES_PER_MONTH * MEMORY_GB * AVG_DURATION_SEC * COMPUTE_COST_PER_GB_SEC
    
    total_lambda = invocations_cost + compute_cost
    
    print(f"Configuration:")
    print(f"  Memory: {MEMORY_GB} GB")
    print(f"  Avg Duration: {AVG_DURATION_SEC} seconds")
    print(f"  Images/month: {IMAGES_PER_MONTH:,}")
    print()
    print(f"Lambda Costs:")
    print(f"  Invocations: ${invocations_cost:.6f} ({IMAGES_PER_MONTH:,} × ${INVOCATION_COST:.8f})")
    print(f"  Compute: ${compute_cost:.6f} ({IMAGES_PER_MONTH:,} × {MEMORY_GB}GB × {AVG_DURATION_SEC}s × ${COMPUTE_COST_PER_GB_SEC:.10f})")
    print(f"  Total Lambda: ${total_lambda:.6f}")
    print()
    
    # S3 costs
    PUT_COST = 0.005 / 1000  # $0.005 per 1,000 PUT requests
    STORAGE_COST_PER_GB = 0.023  # $0.023 per GB/month (Standard storage)
    AVG_IMAGE_SIZE_MB = 0.4  # Average enhanced image size
    
    s3_put_cost = IMAGES_PER_MONTH * PUT_COST
    s3_storage_cost = (IMAGES_PER_MONTH * AVG_IMAGE_SIZE_MB / 1024) * STORAGE_COST_PER_GB
    
    total_s3 = s3_put_cost + s3_storage_cost
    
    print(f"S3 Costs:")
    print(f"  PUT requests: ${s3_put_cost:.6f} ({IMAGES_PER_MONTH:,} × ${PUT_COST:.6f})")
    print(f"  Storage: ${s3_storage_cost:.6f} ({IMAGES_PER_MONTH * AVG_IMAGE_SIZE_MB / 1024:.2f} GB × ${STORAGE_COST_PER_GB})")
    print(f"  Total S3: ${s3_storage_cost:.6f}")
    print()
    
    total_monthly = total_lambda + total_s3
    
    print(f"Total Monthly Cost: ${total_monthly:.6f}")
    print(f"Cost per Image: ${total_monthly / IMAGES_PER_MONTH:.6f}")
    print()
    
    # Optimization scenarios
    print("=== Optimization Scenarios ===\n")
    
    # Scenario 1: Idempotency saves 10% (duplicate uploads)
    savings_idempotency = total_monthly * 0.10
    print(f"1. Idempotency (prevents 10% duplicate processing):")
    print(f"   Savings: ${savings_idempotency:.6f}/month")
    
    # Scenario 2: Early exit for non-JPEG saves 5%
    savings_early_exit = total_monthly * 0.05
    print(f"2. Early exit for non-JPEG files (saves 5%):")
    print(f"   Savings: ${savings_early_exit:.6f}/month")
    
    # Scenario 3: Optimize memory (if we can reduce to 512MB)
    optimized_memory = 0.5
    optimized_compute = IMAGES_PER_MONTH * optimized_memory * AVG_DURATION_SEC * COMPUTE_COST_PER_GB_SEC
    savings_memory = compute_cost - optimized_compute
    print(f"3. Memory optimization (512MB instead of 1024MB):")
    print(f"   Savings: ${savings_memory:.6f}/month")
    
    total_savings = savings_idempotency + savings_early_exit + savings_memory
    optimized_total = total_monthly - total_savings
    
    print()
    print(f"Total Potential Savings: ${total_savings:.6f}/month")
    print(f"Optimized Monthly Cost: ${optimized_total:.6f}")
    print(f"Optimized Cost per Image: ${optimized_total / IMAGES_PER_MONTH:.6f}")
    
    return {
        "current_monthly": total_monthly,
        "optimized_monthly": optimized_total,
        "savings": total_savings,
    }

if __name__ == "__main__":
    calculate_lambda_costs()


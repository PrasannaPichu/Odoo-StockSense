# -*- coding: utf-8 -*-
"""
StockSense Explainable Inventory Health Engine
Computes deterministic, factor-based health scores and explicit causal explanations.
Never outputs an unexplained black-box number.
"""

import logging

_logger = logging.getLogger(__name__)


def evaluate_product_health(
    current_stock,
    min_threshold,
    max_threshold=None,
    avg_daily_outflow=0.0,
    pending_receipts_qty=0.0,
    recent_adjustments_count=0,
    recent_loss_qty=0.0
):
    """
    Evaluate product inventory health.
    Returns:
        dict: {
            'health_score': float (0-100),
            'health_status': 'healthy' | 'attention' | 'critical',
            'days_of_inventory': float or None,
            'factors': {
                'stock_ratio_score': float,
                'velocity_score': float,
                'pipeline_score': float,
                'stability_score': float
            },
            'explanations': list of str (Human-readable reasons)
        }
    """
    explanations = []

    # 1. Stock Level vs Threshold (Weight: 40%)
    # Ratio = Current / Min
    min_thresh = max(float(min_threshold or 1.0), 1.0)
    stock = float(current_stock or 0.0)
    stock_ratio = stock / min_thresh

    if stock <= 0:
        stock_ratio_score = 0.0
        explanations.append(f"OUT OF STOCK: Current stock is {stock:.1f} units (Threshold: {min_thresh:.1f}).")
    elif stock_ratio < 0.5:
        stock_ratio_score = 20.0
        deficit = min_thresh - stock
        explanations.append(f"Severely depleted: Stock ({stock:.1f}) is {deficit:.1f} units below minimum threshold ({min_thresh:.1f}).")
    elif stock_ratio < 1.0:
        stock_ratio_score = 50.0
        deficit = min_thresh - stock
        explanations.append(f"Low Stock: Stock ({stock:.1f}) is {deficit:.1f} units below minimum threshold ({min_thresh:.1f}).")
    elif stock_ratio <= 1.5:
        stock_ratio_score = 80.0
        explanations.append(f"Adequate Stock: Current level ({stock:.1f}) is safely above minimum threshold ({min_thresh:.1f}).")
    else:
        stock_ratio_score = 100.0
        explanations.append(f"Optimal Buffer: Stock ({stock:.1f}) represents {stock_ratio:.1f}x the minimum requirement.")

    if max_threshold and stock > float(max_threshold):
        excess = stock - float(max_threshold)
        stock_ratio_score = max(stock_ratio_score - 15.0, 50.0)
        explanations.append(f"Overstock Warning: Stock exceeds maximum threshold ({max_threshold:.1f}) by {excess:.1f} units (Carrying cost risk).")

    # 2. Consumption Velocity & Days of Inventory Remaining (Weight: 30%)
    avg_outflow = float(avg_daily_outflow or 0.0)
    if avg_outflow > 0:
        days_of_inventory = stock / avg_outflow
        if days_of_inventory < 3.0:
            velocity_score = 10.0
            explanations.append(f"Imminent Depletion: Rapid consumption ({avg_outflow:.1f}/day) implies only {days_of_inventory:.1f} days of inventory remaining.")
        elif days_of_inventory < 7.0:
            velocity_score = 45.0
            explanations.append(f"High Velocity: Stock will exhaust in {days_of_inventory:.1f} days based on current demand velocity.")
        elif days_of_inventory < 21.0:
            velocity_score = 85.0
            explanations.append(f"Balanced Velocity: {days_of_inventory:.1f} days of supply based on recent consumption.")
        else:
            velocity_score = 100.0
            explanations.append(f"Stable Runway: Robust {days_of_inventory:.1f} days of supply coverage.")
    else:
        days_of_inventory = None
        velocity_score = 90.0
        explanations.append("Stable Velocity: No significant recent outbound consumption detected.")

    # 3. Inbound Pipeline & Pending Purchase Receipts (Weight: 20%)
    pending_qty = float(pending_receipts_qty or 0.0)
    if stock < min_thresh:
        if pending_qty >= (min_thresh - stock):
            pipeline_score = 95.0
            explanations.append(f"Replenishment Secured: Incoming pending receipts ({pending_qty:.1f} units) will fully resolve the stock deficit.")
        elif pending_qty > 0:
            pipeline_score = 60.0
            explanations.append(f"Partial Replenishment: Incoming pending receipts ({pending_qty:.1f} units) cover only part of the deficit.")
        else:
            pipeline_score = 10.0
            explanations.append("Supply Chain Gap: Zero pending supplier receipts scheduled to replenish low stock!")
    else:
        if pending_qty > 0:
            pipeline_score = 100.0
            explanations.append(f"Pipeline Healthy: {pending_qty:.1f} units scheduled for future delivery.")
        else:
            pipeline_score = 85.0
            explanations.append("Pipeline Clear: No pending receipts currently inbound.")

    # 4. Physical Stability & Shrinkage History (Weight: 10%)
    adj_count = int(recent_adjustments_count or 0)
    loss_qty = float(recent_loss_qty or 0.0)
    if adj_count == 0:
        stability_score = 100.0
    elif adj_count <= 2 and loss_qty <= 5.0:
        stability_score = 75.0
        explanations.append(f"Minor Variance: {adj_count} cycle count adjustment(s) logged recently ({loss_qty:.1f} units lost/damaged).")
    else:
        stability_score = 30.0
        explanations.append(f"High Shrinkage Risk: {adj_count} physical adjustments logged recently totaling {loss_qty:.1f} units in discrepancies.")

    # Weighted Composite Score
    composite = (
        (stock_ratio_score * 0.40) +
        (velocity_score * 0.30) +
        (pipeline_score * 0.20) +
        (stability_score * 0.10)
    )
    health_score = round(max(0.0, min(100.0, composite)), 1)

    # Categorical Status Mapping
    if health_score >= 75.0 and stock > 0:
        health_status = 'healthy'
    elif health_score >= 45.0 and stock > 0:
        health_status = 'attention'
    else:
        health_status = 'critical'

    return {
        'health_score': health_score,
        'health_status': health_status,
        'days_of_inventory': round(days_of_inventory, 1) if days_of_inventory is not None else None,
        'factors': {
            'stock_ratio_score': round(stock_ratio_score, 1),
            'velocity_score': round(velocity_score, 1),
            'pipeline_score': round(pipeline_score, 1),
            'stability_score': round(stability_score, 1)
        },
        'explanations': explanations
    }

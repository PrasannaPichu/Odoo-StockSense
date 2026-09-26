# -*- coding: utf-8 -*-
"""
StockSense Anomaly Detection Engine
Evaluates deterministic business rule anomalies and statistical distribution shifts (Z-score deviation).
Clearly distinguishes between deterministic rule breaches and statistical alerts.
"""

import math
import logging

_logger = logging.getLogger(__name__)


def detect_operational_anomalies(
    product_sku,
    current_operation_type,
    operation_quantity,
    available_stock,
    historical_movements_qty=None,
    recent_adjustments_count_7d=0,
    total_adjusted_qty_7d=0.0,
    days_since_last_movement=None
):
    """
    Detect operational and statistical anomalies for an inventory transaction.
    Returns:
        list of dict: [
            {
                'rule_code': str,
                'anomaly_type': 'deterministic_rule' | 'statistical_deviation',
                'severity': 'low' | 'medium' | 'high' | 'critical',
                'title': str,
                'description': str,
                'metrics': dict
            }
        ]
    """
    anomalies = []
    qty = float(operation_quantity or 0.0)
    avail = float(available_stock or 0.0)

    # 1. Deterministic Rule: Delivery exceeds available stock
    if current_operation_type == 'delivery' and qty > avail:
        anomalies.append({
            'rule_code': 'RULE_INSUFFICIENT_STOCK',
            'anomaly_type': 'deterministic_rule',
            'severity': 'critical',
            'title': 'Deficit Delivery Attempt',
            'description': f"Delivery quantity ({qty:.1f}) exceeds current physical stock ({avail:.1f}) by {qty - avail:.1f} units.",
            'metrics': {'requested_qty': qty, 'available_stock': avail, 'deficit': qty - avail}
        })

    # 2. Deterministic Rule: Repeated stock adjustments (Shrinkage / Discrepancy pattern)
    if recent_adjustments_count_7d >= 3:
        anomalies.append({
            'rule_code': 'RULE_REPEATED_ADJUSTMENTS',
            'anomaly_type': 'deterministic_rule',
            'severity': 'high',
            'title': 'High Adjustment Frequency',
            'description': f"Product {product_sku} has been manually adjusted {recent_adjustments_count_7d} times in the last 7 days (total discrepancy: {total_adjusted_qty_7d:.1f} units). Potential shrinkage or counting error.",
            'metrics': {'adjustment_count_7d': recent_adjustments_count_7d, 'total_adjusted_qty': total_adjusted_qty_7d}
        })

    # 3. Deterministic Rule: Dead stock sudden massive draw
    if days_since_last_movement is not None and days_since_last_movement > 45 and qty > 0 and current_operation_type == 'delivery':
        anomalies.append({
            'rule_code': 'RULE_DORMANT_STOCK_SURGE',
            'anomaly_type': 'deterministic_rule',
            'severity': 'medium',
            'title': 'Dormant SKU Reactivation',
            'description': f"Product {product_sku} had zero movements for {days_since_last_movement} days and suddenly experienced a large withdrawal of {qty:.1f} units.",
            'metrics': {'dormant_days': days_since_last_movement, 'withdrawal_qty': qty}
        })

    # 4. Statistical Anomaly: Z-Score Outbound Surge
    # If historical movements are provided (at least 5 samples), compute mean and std dev
    if historical_movements_qty and len(historical_movements_qty) >= 5 and qty > 0:
        n = len(historical_movements_qty)
        mean_qty = sum(historical_movements_qty) / n
        variance = sum((x - mean_qty) ** 2 for x in historical_movements_qty) / (n - 1)
        std_dev = math.sqrt(variance)

        if std_dev > 0.01:
            z_score = (qty - mean_qty) / std_dev
            if z_score >= 3.0:
                anomalies.append({
                    'rule_code': 'STAT_OUTBOUND_SURGE_Z3',
                    'anomaly_type': 'statistical_deviation',
                    'severity': 'high',
                    'title': 'Extreme Outbound Velocity Surge (Z >= 3.0)',
                    'description': f"Current movement quantity ({qty:.1f}) is {z_score:.2f} standard deviations above the 30-day baseline average ({mean_qty:.1f} ± {std_dev:.1f}).",
                    'metrics': {'z_score': round(z_score, 2), 'mean': round(mean_qty, 1), 'std_dev': round(std_dev, 1)}
                })
            elif z_score >= 2.0:
                anomalies.append({
                    'rule_code': 'STAT_OUTBOUND_SURGE_Z2',
                    'anomaly_type': 'statistical_deviation',
                    'severity': 'medium',
                    'title': 'Unusual Movement Volume (Z >= 2.0)',
                    'description': f"Current movement quantity ({qty:.1f}) exhibits statistically significant deviation (Z={z_score:.2f}) from normal consumption ({mean_qty:.1f}).",
                    'metrics': {'z_score': round(z_score, 2), 'mean': round(mean_qty, 1), 'std_dev': round(std_dev, 1)}
                })

    return anomalies

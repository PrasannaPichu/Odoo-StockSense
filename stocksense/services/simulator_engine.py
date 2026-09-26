# -*- coding: utf-8 -*-
"""
StockSense In-Memory What-If Simulator Engine
Provides safe, completely sandboxed hypothetical projection of inventory operations.
CRITICAL INVARIANT: Simulation NEVER mutates actual PostgreSQL stock, ledger, or picking records.
"""

from .health_engine import evaluate_product_health

def simulate_hypothetical_scenario(
    current_stock,
    min_threshold,
    max_threshold,
    scenario_type,  # 'delivery' | 'receipt' | 'transfer' | 'multi_event'
    quantity,
    avg_daily_outflow=0.0,
    pending_receipts_qty=0.0,
    source_location_stock=None,
    dest_location_stock=None
):
    """
    Simulate the operational and health impact of a hypothetical transaction entirely in-memory.
    Returns:
        dict: {
            'current_state': dict,
            'projected_state': dict,
            'delta': float,
            'health_impact': {
                'before': dict,
                'after': dict,
                'status_changed': bool
            },
            'warnings': list of str,
            'recommendations': list of str
        }
    """
    stock = float(current_stock or 0.0)
    qty = float(quantity or 0.0)
    min_th = float(min_threshold or 0.0)
    max_th = float(max_threshold or 0.0) if max_threshold else None

    # Baseline health before hypothetical operation
    initial_health = evaluate_product_health(
        current_stock=stock,
        min_threshold=min_th,
        max_threshold=max_th,
        avg_daily_outflow=avg_daily_outflow,
        pending_receipts_qty=pending_receipts_qty
    )

    warnings = []
    recommendations = []

    if scenario_type == 'delivery':
        projected_stock = stock - qty
        delta = -qty
        if projected_stock < 0:
            warnings.append(f"UNFEASIBLE: Hypothetical delivery of {qty:.1f} exceeds current stock ({stock:.1f}) by {abs(projected_stock):.1f} units.")
            recommendations.append("Splitting this order into multiple shipments or delaying fulfillment is required.")
        elif projected_stock < min_th:
            warnings.append(f"BREACH: Projected stock ({projected_stock:.1f}) falls below safety threshold ({min_th:.1f}).")
            recommendations.append(f"Trigger an urgent replenishment PO of at least {min_th - projected_stock + 20:.1f} units.")
        else:
            recommendations.append(f"Fulfillment feasible. Buffer remaining: {projected_stock - min_th:.1f} units above safety margin.")

    elif scenario_type == 'receipt':
        projected_stock = stock + qty
        delta = +qty
        if max_th and projected_stock > max_th:
            warnings.append(f"OVERSTOCK: Projected stock ({projected_stock:.1f}) exceeds warehouse maximum capacity ({max_th:.1f}).")
            recommendations.append("Ensure adequate physical bay storage prior to delivery arrival.")
        else:
            recommendations.append(f"Receipt feasible. New total will comfortably satisfy upcoming requirements.")

    elif scenario_type == 'transfer':
        # Internal transfer leaves total stock invariant, but redistributes across locations
        projected_stock = stock
        delta = 0.0
        src_stock = float(source_location_stock if source_location_stock is not None else stock)
        dst_stock = float(dest_location_stock if dest_location_stock is not None else 0.0)

        proj_src = src_stock - qty
        proj_dst = dst_stock + qty

        if proj_src < 0:
            warnings.append(f"Source location has insufficient stock ({src_stock:.1f}) to transfer {qty:.1f} units.")
        else:
            recommendations.append(f"Transfer feasible. Source will retain {proj_src:.1f}, destination will increase to {proj_dst:.1f}.")

    else:
        projected_stock = stock
        delta = 0.0

    # Projected health after hypothetical operation
    projected_health = evaluate_product_health(
        current_stock=projected_stock,
        min_threshold=min_th,
        max_threshold=max_th,
        avg_daily_outflow=avg_daily_outflow,
        pending_receipts_qty=pending_receipts_qty if scenario_type != 'receipt' else max(0.0, pending_receipts_qty - qty)
    )

    status_changed = initial_health['health_status'] != projected_health['health_status']

    return {
        'scenario_type': scenario_type,
        'simulated_quantity': qty,
        'current_stock': stock,
        'projected_stock': projected_stock,
        'stock_delta': delta,
        'health_impact': {
            'before': initial_health,
            'after': projected_health,
            'score_diff': round(projected_health['health_score'] - initial_health['health_score'], 1),
            'status_changed': status_changed,
            'transition': f"{initial_health['health_status'].upper()} -> {projected_health['health_status'].upper()}" if status_changed else f"Maintains {initial_health['health_status'].upper()}"
        },
        'warnings': warnings,
        'recommendations': recommendations
    }

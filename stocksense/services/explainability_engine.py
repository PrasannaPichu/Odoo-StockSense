# -*- coding: utf-8 -*-
"""
StockSense Explainability Engine
Generates transparent, factor-attributed diagnostic narratives for alerts, stock-outs, and operational risks.
"""

def generate_risk_explanation(product_dict, health_eval, anomalies=None):
    """
    Produce structured human-readable explainability report for a product.
    Returns:
        dict: {
            'summary': str,
            'status': str,
            'risk_level': 'Low' | 'Medium' | 'High' | 'Severe',
            'factor_breakdown': list of dict,
            'actionable_recommendations': list of str
        }
    """
    score = health_eval.get('health_score', 100.0)
    status = health_eval.get('health_status', 'healthy')
    factors = health_eval.get('factors', {})
    explanations = health_eval.get('explanations', [])

    factor_breakdown = [
        {
            'factor_name': 'Stock Availability Ratio',
            'weight': '40%',
            'score': factors.get('stock_ratio_score', 100.0),
            'assessment': 'Critical' if factors.get('stock_ratio_score', 100) < 50 else 'Normal'
        },
        {
            'factor_name': 'Consumption Velocity',
            'weight': '30%',
            'score': factors.get('velocity_score', 100.0),
            'assessment': 'High Drain' if factors.get('velocity_score', 100) < 50 else 'Normal'
        },
        {
            'factor_name': 'Inbound Pipeline Coverage',
            'weight': '20%',
            'score': factors.get('pipeline_score', 100.0),
            'assessment': 'Uncovered' if factors.get('pipeline_score', 100) < 50 else 'Secured'
        },
        {
            'factor_name': 'Inventory Stability & Shrinkage',
            'weight': '10%',
            'score': factors.get('stability_score', 100.0),
            'assessment': 'High Variance' if factors.get('stability_score', 100) < 50 else 'Stable'
        }
    ]

    recommendations = []
    if status == 'critical':
        recommendations.append("Place an immediate expedited replenishment Purchase Order to suppliers.")
        if factors.get('pipeline_score', 0) < 50:
            recommendations.append("Check with suppliers for lead-time acceleration as no incoming PO is scheduled.")
    elif status == 'attention':
        recommendations.append("Review consumption trends and verify if reorder point requires upward adjustment.")

    if anomalies:
        for a in anomalies:
            recommendations.append(f"Investigate anomaly: {a.get('title')} ({a.get('description')})")

    risk_level = "Severe" if score < 30 else ("High" if score < 50 else ("Medium" if score < 75 else "Low"))

    summary_text = (
        f"Product '{product_dict.get('name', 'SKU')}' is currently in {status.upper()} state "
        f"(Health Index: {score}/100, Risk Level: {risk_level}). "
        f"{'Primary concern: ' + explanations[0] if explanations else 'Stock levels and movements are within expected parameters.'}"
    )

    return {
        'summary': summary_text,
        'status': status,
        'risk_level': risk_level,
        'factor_breakdown': factor_breakdown,
        'reasons': explanations,
        'actionable_recommendations': recommendations
    }

# -*- coding: utf-8 -*-
"""
StockSense Tamper-Evident Hash-Chained Audit Trail Service
Provides cryptographic auditability for all critical inventory operations using SHA-256 hash chaining.
"""

import hashlib
import json
import logging

_logger = logging.getLogger(__name__)

GENESIS_HASH = hashlib.sha256(b"STOCKSENSE_GENESIS_2026").hexdigest()


def canonical_json(data):
    """Generate deterministic, canonical JSON representation."""
    return json.dumps(data, sort_keys=True, separators=(',', ':'), default=str)


def compute_block_hash(payload, previous_hash):
    """
    Compute current SHA-256 hash for an audit block.
    Hash = SHA256(canonical_json(payload) + previous_hash)
    """
    payload_str = canonical_json(payload)
    hasher = hashlib.sha256()
    hasher.update(payload_str.encode('utf-8'))
    hasher.update(previous_hash.encode('utf-8'))
    return hasher.hexdigest()


def verify_chain(records):
    """
    Verify the integrity of a sequence of audit trail records.
    Each record must have: sequence_number, payload (or payload_json), previous_hash, current_hash.
    Returns:
        dict: {
            'valid': bool,
            'total_verified': int,
            'broken_at_sequence': int or None,
            'error_message': str or None
        }
    """
    if not records:
        return {
            'valid': True,
            'total_verified': 0,
            'broken_at_sequence': None,
            'error_message': "Chain is empty (Valid Genesis state)"
        }

    expected_prev = GENESIS_HASH

    for idx, rec in enumerate(records):
        seq = rec.get('sequence_number', idx + 1)
        prev_hash = rec.get('previous_hash')
        curr_hash = rec.get('current_hash')
        payload = rec.get('payload')

        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception as e:
                return {
                    'valid': False,
                    'total_verified': idx,
                    'broken_at_sequence': seq,
                    'error_message': f"Corrupted payload JSON at block {seq}: {e}"
                }

        # Check previous hash link
        if prev_hash != expected_prev:
            return {
                'valid': False,
                'total_verified': idx,
                'broken_at_sequence': seq,
                'error_message': f"Hash chain break at block {seq}: previous_hash '{prev_hash}' does not match expected '{expected_prev}'"
            }

        # Verify current hash calculation
        computed = compute_block_hash(payload, prev_hash)
        if computed != curr_hash:
            return {
                'valid': False,
                'total_verified': idx,
                'broken_at_sequence': seq,
                'error_message': f"Hash mismatch at block {seq}: stored '{curr_hash}', recomputed '{computed}'. Data tampering detected!"
            }

        expected_prev = curr_hash

    return {
        'valid': True,
        'total_verified': len(records),
        'broken_at_sequence': None,
        'error_message': None,
        'latest_hash': expected_prev
    }

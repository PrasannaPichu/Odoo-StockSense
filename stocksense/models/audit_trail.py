# -*- coding: utf-8 -*-
import json
from odoo import models, fields, api, _
from odoo.exceptions import UserError
from ..services.audit_chain import GENESIS_HASH, compute_block_hash, verify_chain

class StocksenseAuditTrail(models.Model):
    _name = 'stocksense.audit.trail'
    _description = 'StockSense Tamper-Evident Hash-Chained Audit Trail'
    _order = 'sequence_number desc, id desc'

    sequence_number = fields.Integer(string='Block #', required=True, index=True)
    timestamp = fields.Datetime(string='Timestamp', default=fields.Datetime.now, required=True, index=True)
    event_type = fields.Char(string='Event Type', required=True, index=True)
    record_reference = fields.Char(string='Document Ref', required=True, index=True)
    payload_json = fields.Text(string='Audited State Payload', required=True)
    previous_hash = fields.Char(string='Previous Block Hash', size=64, required=True)
    current_hash = fields.Char(string='Current Block Hash (SHA-256)', size=64, required=True, index=True)
    is_verified = fields.Boolean(string='Cryptographically Valid', default=True)

    @api.model
    def append_audit_block(self, event_type, record_reference, payload):
        """
        Cryptographically append an event block to the tamper-evident hash chain.
        Ensures strict sequence numbering and SHA-256 chaining.
        """
        last_block = self.search([], order='sequence_number desc', limit=1)
        if last_block:
            prev_seq = last_block.sequence_number
            prev_hash = last_block.current_hash
        else:
            prev_seq = 0
            prev_hash = GENESIS_HASH

        curr_seq = prev_seq + 1
        curr_hash = compute_block_hash(payload, prev_hash)

        return self.create({
            'sequence_number': curr_seq,
            'event_type': event_type,
            'record_reference': record_reference,
            'payload_json': json.dumps(payload, sort_keys=True, default=str),
            'previous_hash': prev_hash,
            'current_hash': curr_hash,
            'is_verified': True
        })

    def action_verify_chain(self):
        """
        Forensic audit verification tool:
        Traverses the complete chain from Genesis block and flags any manual row tampering.
        """
        all_blocks = self.search([], order='sequence_number asc')
        record_list = [
            {
                'sequence_number': b.sequence_number,
                'previous_hash': b.previous_hash,
                'current_hash': b.current_hash,
                'payload': b.payload_json
            }
            for b in all_blocks
        ]

        verification = verify_chain(record_list)

        if verification['valid']:
            msg = _('Audit Chain Integrity Verified: All %s blocks match cryptographic SHA-256 signatures.') % verification['total_verified']
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Audit Trail 100% Valid'),
                    'message': msg,
                    'type': 'success',
                    'sticky': False,
                }
            }
        else:
            err = verification.get('error_message')
            broken = verification.get('broken_at_sequence')
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('TAMPERING DETECTED!'),
                    'message': _('Chain broken at Block #%s: %s') % (broken, err),
                    'type': 'danger',
                    'sticky': True,
                }
            }

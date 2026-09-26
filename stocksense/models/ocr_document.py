# -*- coding: utf-8 -*-
import base64
import json
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from ..services.ocr_service import process_document_bytes

_logger = logging.getLogger(__name__)

class StocksenseOcrDocument(models.Model):
    _name = 'stocksense.ocr.document'
    _description = 'StockSense Document Intake & Local OCR Review'
    _order = 'create_date desc, id desc'

    name = fields.Char(
        string='Document Intake Ref',
        required=True,
        copy=False,
        readonly=True,
        index=True,
        default=lambda self: self.env['ir.sequence'].next_by_code('stocksense.ocr.document') or _('New')
    )
    document_type = fields.Selection([
        ('receipt', 'Supplier Goods Receipt / Invoice'),
        ('delivery', 'Customer Delivery Order / Dispatch'),
        ('partner', 'Business Partner Registration (Vendor/Client)'),
    ], string='Intake Workflow', default='receipt', required=True, index=True)

    file_data = fields.Binary(string='Document Upload (PDF, PNG, JPG)', required=True, attachment=True)
    filename = fields.Char(string='Filename', required=True)
    mime_type = fields.Char(string='MIME Type')
    file_size = fields.Integer(string='File Size (Bytes)', compute='_compute_file_size', store=True, readonly=True)

    state = fields.Selection([
        ('draft', 'Document Uploaded'),
        ('processing', 'Processing OCR'),
        ('extracted', 'Review & Verification Required'),
        ('approved', 'Approved & Converted to Draft'),
        ('rejected', 'Rejected'),
        ('failed', 'Extraction Failed'),
    ], string='Intake Status', default='draft', required=True, index=True)

    ocr_engine = fields.Char(string='Local OCR Engine', default='RapidOCR ONNX Runtime (CPU)', readonly=True)
    confidence = fields.Float(string='Average Confidence (%)', digits=(5, 2), readonly=True)
    raw_text = fields.Text(string='Full Raw OCR Output', readonly=True)

    # Extracted Header Entities (Human-in-the-Loop reviewable)
    extracted_partner_name = fields.Char(string='Detected Partner Name')
    extracted_reference = fields.Char(string='Detected Ref / Invoice #')
    extracted_date = fields.Date(string='Detected Document Date')
    extracted_phone = fields.Char(string='Detected Phone')
    extracted_email = fields.Char(string='Detected Email')
    extracted_tax_id = fields.Char(string='Detected Tax / GST ID')
    extracted_address = fields.Char(string='Detected Street Address')

    # Operational Links & Targets
    partner_id = fields.Many2one('res.partner', string='Matched / Selected Partner')
    warehouse_id = fields.Many2one('stocksense.warehouse', string='Target Warehouse')
    receipt_id = fields.Many2one('stocksense.receipt', string='Generated Draft Receipt', readonly=True)
    delivery_id = fields.Many2one('stocksense.delivery', string='Generated Draft Delivery', readonly=True)

    # Verification & Audit Tracking
    reviewed_by = fields.Many2one('res.users', string='Verified By', readonly=True)
    reviewed_at = fields.Datetime(string='Verification Timestamp', readonly=True)
    review_notes = fields.Text(string='Reviewer Corrections & Audit Notes')

    line_ids = fields.One2many('stocksense.ocr.line', 'document_id', string='Detected Item Lines')

    @api.model
    def default_get(self, fields_list):
        res = super(StocksenseOcrDocument, self).default_get(fields_list)
        if 'name' in fields_list and (not res.get('name') or res.get('name') in (_('New'), 'New', '/')):
            res['name'] = self.env['ir.sequence'].next_by_code('stocksense.ocr.document') or _('New')
        return res

    @api.depends('file_data')
    def _compute_file_size(self):
        for rec in self:
            if rec.file_data:
                try:
                    data = rec.file_data
                    if isinstance(data, str):
                        raw_bytes = base64.b64decode(data.encode('utf-8'))
                    elif isinstance(data, bytes):
                        raw_bytes = base64.b64decode(data)
                    else:
                        raw_bytes = b''
                    rec.file_size = len(raw_bytes)
                except Exception:
                    rec.file_size = len(rec.file_data) if rec.file_data else 0
            else:
                rec.file_size = 0

    @api.onchange('file_data', 'filename')
    def _onchange_file_data(self):
        if self.file_data:
            try:
                data = self.file_data
                if isinstance(data, str):
                    raw_bytes = base64.b64decode(data.encode('utf-8'))
                elif isinstance(data, bytes):
                    raw_bytes = base64.b64decode(data)
                else:
                    raw_bytes = b''
                self.file_size = len(raw_bytes)
            except Exception:
                self.file_size = len(self.file_data) if self.file_data else 0
        else:
            self.file_size = 0

        if self.filename:
            fn = self.filename.lower()
            if fn.endswith('.pdf'):
                self.mime_type = 'application/pdf'
            elif fn.endswith('.png'):
                self.mime_type = 'image/png'
            elif fn.endswith(('.jpg', '.jpeg')):
                self.mime_type = 'image/jpeg'
            elif fn.endswith('.webp'):
                self.mime_type = 'image/webp'

    @api.constrains('file_data', 'file_size')
    def _check_file_data_size(self):
        for rec in self:
            if rec.file_size > 10 * 1024 * 1024:
                raise ValidationError(_('Uploaded document exceeds maximum allowed size (10 MB).'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') in (_('New'), 'New', _('OCR-NEW'), 'OCR-NEW', '/'):
                vals['name'] = self.env['ir.sequence'].next_by_code('stocksense.ocr.document') or _('New')
            if vals.get('file_data') and not vals.get('file_size'):
                try:
                    data = vals['file_data']
                    if isinstance(data, str):
                        raw_bytes = base64.b64decode(data.encode('utf-8'))
                    elif isinstance(data, bytes):
                        raw_bytes = base64.b64decode(data)
                    else:
                        raw_bytes = b''
                    vals['file_size'] = len(raw_bytes)
                except Exception:
                    vals['file_size'] = len(vals['file_data'])
            if vals.get('file_size', 0) > 10 * 1024 * 1024:
                raise ValidationError(_('Uploaded document exceeds maximum allowed size (10 MB).'))
            if vals.get('filename') and not vals.get('mime_type'):
                fn = vals['filename'].lower()
                if fn.endswith('.pdf'):
                    vals['mime_type'] = 'application/pdf'
                elif fn.endswith('.png'):
                    vals['mime_type'] = 'image/png'
                elif fn.endswith(('.jpg', '.jpeg')):
                    vals['mime_type'] = 'image/jpeg'
                elif fn.endswith('.webp'):
                    vals['mime_type'] = 'image/webp'
        records = super(StocksenseOcrDocument, self).create(vals_list)
        for rec in records:
            # Audit log document ingestion
            rec.env['stocksense.audit.trail'].append_audit_block(
                event_type='DOCUMENT_UPLOADED',
                record_reference=rec.name,
                payload={
                    'document_id': rec.id,
                    'document_name': rec.name,
                    'filename': rec.filename,
                    'document_type': rec.document_type,
                    'file_size': rec.file_size
                }
            )
        return records

    def write(self, vals):
        if vals.get('file_data'):
            try:
                data = vals['file_data']
                if isinstance(data, str):
                    raw_bytes = base64.b64decode(data.encode('utf-8'))
                elif isinstance(data, bytes):
                    raw_bytes = base64.b64decode(data)
                else:
                    raw_bytes = b''
                if len(raw_bytes) > 10 * 1024 * 1024:
                    raise ValidationError(_('Uploaded document exceeds maximum allowed size (10 MB).'))
                vals['file_size'] = len(raw_bytes)
            except Exception:
                pass
        return super(StocksenseOcrDocument, self).write(vals)

    def action_process_ocr(self):
        """
        Execute real local CPU RapidOCR on the uploaded document.
        Populates reviewable header fields and line items.
        CRITICAL: OCR execution strictly performs intake; ZERO stock changes occur.
        """
        self.ensure_one()
        if not self.file_data:
            raise UserError(_('No document file attached for OCR processing.'))

        # Check allowed file extensions
        allowed = ('.pdf', '.png', '.jpg', '.jpeg', '.webp', '.tiff', '.bmp')
        if not (self.filename or '').lower().endswith(allowed):
            raise ValidationError(_('Unsupported document format. Allowed: PDF, PNG, JPG, JPEG.'))

        self.write({'state': 'processing'})

        try:
            file_bytes = base64.b64decode(self.file_data)
            result = process_document_bytes(file_bytes, self.filename)

            if result.get('error'):
                self.write({
                    'state': 'failed',
                    'review_notes': f"OCR Error: {result.get('error')}"
                })
                return False

            raw_text = result.get('raw_text', '')
            confidence = result.get('average_confidence', 0.0)
            partner_name = result.get('partner_name', '')
            ref = result.get('reference', '')
            doc_date = result.get('date', False)
            phone = result.get('phone', '')
            email = result.get('email', '')
            tax_id = result.get('tax_id', '')
            address = result.get('address', '')

            # Match or suggest existing partner
            matched_partner = False
            if partner_name:
                matched_partner = self.env['res.partner'].search([
                    '|', ('name', 'ilike', partner_name), ('vat', '=', tax_id)
                ], limit=1)

            # Default warehouse if not assigned
            default_wh = self.warehouse_id or self.env['stocksense.warehouse'].search([], limit=1)

            # Prepare detected lines
            line_vals_list = []
            for item in result.get('lines', []):
                raw_desc = item.get('raw_description', '')
                detected_sku = item.get('detected_sku', '')
                qty = item.get('detected_qty', 1.0)
                uom = item.get('detected_uom', 'Units')

                # Try matching against existing StockSense products
                matched_prod = False
                match_status = 'review_required'

                if detected_sku:
                    matched_prod = self.env['stocksense.product'].search([
                        ('sku', '=', detected_sku)
                    ], limit=1)

                if not matched_prod and raw_desc:
                    # Search by product name or partial SKU
                    matched_prod = self.env['stocksense.product'].search([
                        '|', ('name', 'ilike', raw_desc), ('sku', 'ilike', raw_desc)
                    ], limit=1)

                if matched_prod:
                    match_status = 'matched'

                line_vals_list.append((0, 0, {
                    'raw_description': raw_desc,
                    'detected_sku': detected_sku or (matched_prod.sku if matched_prod else ''),
                    'detected_qty': qty,
                    'detected_uom': uom,
                    'product_id': matched_prod.id if matched_prod else False,
                    'match_status': match_status,
                    'confidence': confidence,
                }))

            # Clean previous lines if re-processing
            self.line_ids.unlink()

            vals_to_write = {
                'raw_text': raw_text,
                'confidence': confidence,
                'extracted_partner_name': partner_name,
                'extracted_reference': ref,
                'extracted_phone': phone,
                'extracted_email': email,
                'extracted_tax_id': tax_id,
                'extracted_address': address,
                'partner_id': matched_partner.id if matched_partner else False,
                'warehouse_id': default_wh.id if default_wh else False,
                'state': 'extracted',
                'line_ids': line_vals_list
            }
            if doc_date:
                vals_to_write['extracted_date'] = doc_date

            self.write(vals_to_write)

            # Record audit block for OCR processing
            self.env['stocksense.audit.trail'].append_audit_block(
                event_type='OCR_PROCESSED',
                record_reference=self.name,
                payload={
                    'document_id': self.id,
                    'partner_detected': partner_name,
                    'reference': ref,
                    'confidence': confidence,
                    'lines_detected': len(line_vals_list)
                }
            )

            return True

        except Exception as e:
            _logger.exception("OCR Extraction failed for %s", self.name)
            self.write({
                'state': 'failed',
                'review_notes': f"Processing exception: {str(e)}"
            })
            raise UserError(_("OCR Processing failed: %s") % str(e))

    def action_create_draft_receipt(self):
        """
        Human-in-the-Loop Approval:
        Converts verified OCR data into an Odoo DRAFT Goods Receipt.
        CRITICAL: The receipt is created in 'draft' status. Stock NEVER mutates here.
        Stock only mutates when the user separately clicks [ Validate ] on the receipt.
        """
        self.ensure_one()
        if self.state not in ['extracted', 'draft']:
            raise UserError(_('Document must be in Extracted state before converting to a Draft Receipt.'))

        # Check line items
        if not self.line_ids:
            raise UserError(_('No line items found. Please add or verify line items before creating a draft receipt.'))

        # Unmatched line verification
        unmatched = self.line_ids.filtered(lambda l: not l.product_id)
        if unmatched:
            raise UserError(
                _("Line item '%s' has no matched product. Please select the StockSense product before proceeding.")
                % unmatched[0].raw_description
            )

        # Partner resolution
        partner = self.partner_id
        if not partner:
            p_name = self.extracted_partner_name or _('OCR Supplier (%s)') % (self.extracted_reference or self.name)
            partner = self.env['res.partner'].create({
                'name': p_name,
                'phone': self.extracted_phone,
                'email': self.extracted_email,
                'street': self.extracted_address,
                'vat': self.extracted_tax_id,
            })
            self.partner_id = partner.id

        # Warehouse & Destination Location resolution
        warehouse = self.warehouse_id or self.env['stocksense.warehouse'].search([], limit=1)
        if not warehouse:
            raise UserError(_('No warehouse configured in StockSense.'))

        dest_loc = self.env['stocksense.location'].search([
            ('warehouse_id', '=', warehouse.id),
            ('usage', '=', 'internal')
        ], limit=1)
        if not dest_loc:
            dest_loc = self.env['stocksense.location'].search([('usage', '=', 'internal')], limit=1)

        # Build lines for receipt
        receipt_lines = []
        for line in self.line_ids:
            receipt_lines.append((0, 0, {
                'product_id': line.product_id.id,
                'quantity_expected': line.detected_qty,
                'quantity_received': line.detected_qty,
            }))

        # Create DRAFT Receipt
        receipt = self.env['stocksense.receipt'].create({
            'partner_id': partner.id,
            'warehouse_id': warehouse.id,
            'location_dest_id': dest_loc.id if dest_loc else False,
            'state': 'draft',
            'notes': _("Auto-generated from OCR Document Intake %s (Ref: %s). Requires human validation.")
                     % (self.name, self.extracted_reference or 'N/A'),
            'line_ids': receipt_lines
        })

        # Mark OCR document as approved
        self.write({
            'state': 'approved',
            'receipt_id': receipt.id,
            'reviewed_by': self.env.user.id,
            'reviewed_at': fields.Datetime.now(),
        })

        # Record Audit Trail for OCR Intake Approval
        self.env['stocksense.audit.trail'].append_audit_block(
            event_type='OCR_APPROVED',
            record_reference=self.name,
            payload={
                'ocr_document': self.name,
                'target_action': 'create_draft_receipt',
                'generated_receipt_ref': receipt.name,
                'lines_count': len(receipt_lines),
                'verified_by': self.env.user.name
            }
        )

        # Return action to open the newly created draft receipt
        return {
            'name': _('Draft Goods Receipt (from OCR)'),
            'type': 'ir.actions.act_window',
            'res_model': 'stocksense.receipt',
            'res_id': receipt.id,
            'views': [[False, 'form']],
            'target': 'current',
        }

    def action_create_draft_delivery(self):
        """
        Converts verified OCR customer order document into a DRAFT Delivery Order.
        Stock NEVER mutates here.
        """
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_('No line items found to generate a delivery order.'))

        unmatched = self.line_ids.filtered(lambda l: not l.product_id)
        if unmatched:
            raise UserError(
                _("Line item '%s' has no matched product. Please select the StockSense product.")
                % unmatched[0].raw_description
            )

        partner = self.partner_id
        if not partner:
            p_name = self.extracted_partner_name or _('OCR Customer (%s)') % (self.extracted_reference or self.name)
            partner = self.env['res.partner'].create({
                'name': p_name,
                'phone': self.extracted_phone,
                'email': self.extracted_email,
                'street': self.extracted_address,
                'vat': self.extracted_tax_id,
            })
            self.partner_id = partner.id

        warehouse = self.warehouse_id or self.env['stocksense.warehouse'].search([], limit=1)
        src_loc = self.env['stocksense.location'].search([
            ('warehouse_id', '=', warehouse.id),
            ('usage', '=', 'internal')
        ], limit=1)

        delivery_lines = []
        for line in self.line_ids:
            delivery_lines.append((0, 0, {
                'product_id': line.product_id.id,
                'quantity_requested': line.detected_qty,
                'quantity_delivered': line.detected_qty,
            }))

        delivery = self.env['stocksense.delivery'].create({
            'partner_id': partner.id,
            'warehouse_id': warehouse.id,
            'location_src_id': src_loc.id if src_loc else False,
            'state': 'draft',
            'notes': _("Auto-generated from OCR Document %s (Ref: %s). Requires Pick -> Pack -> Validate.")
                     % (self.name, self.extracted_reference or 'N/A'),
            'line_ids': delivery_lines
        })

        self.write({
            'state': 'approved',
            'delivery_id': delivery.id,
            'reviewed_by': self.env.user.id,
            'reviewed_at': fields.Datetime.now(),
        })

        self.env['stocksense.audit.trail'].append_audit_block(
            event_type='OCR_APPROVED',
            record_reference=self.name,
            payload={
                'ocr_document': self.name,
                'target_action': 'create_draft_delivery',
                'generated_delivery_ref': delivery.name,
                'lines_count': len(delivery_lines),
                'verified_by': self.env.user.name
            }
        )

        return {
            'name': _('Draft Delivery Order (from OCR)'),
            'type': 'ir.actions.act_window',
            'res_model': 'stocksense.delivery',
            'res_id': delivery.id,
            'views': [[False, 'form']],
            'target': 'current',
        }

    def action_create_partner(self):
        """
        Creates or updates a Business Partner record directly from OCR extracted metadata.
        """
        self.ensure_one()
        p_name = self.extracted_partner_name or _('New Partner (%s)') % (self.extracted_tax_id or self.name)
        partner = self.env['res.partner'].create({
            'name': p_name,
            'phone': self.extracted_phone,
            'email': self.extracted_email,
            'street': self.extracted_address,
            'vat': self.extracted_tax_id,
            'comment': f"Registered via StockSense OCR Document Intake {self.name}"
        })
        self.write({
            'partner_id': partner.id,
            'state': 'approved',
            'reviewed_by': self.env.user.id,
            'reviewed_at': fields.Datetime.now(),
        })

        self.env['stocksense.audit.trail'].append_audit_block(
            event_type='OCR_APPROVED',
            record_reference=self.name,
            payload={
                'ocr_document': self.name,
                'target_action': 'create_partner',
                'created_partner_id': partner.id,
                'created_partner_name': partner.name
            }
        )

        return {
            'name': _('Business Partner'),
            'type': 'ir.actions.act_window',
            'res_model': 'res.partner',
            'res_id': partner.id,
            'views': [[False, 'form']],
            'target': 'current',
        }

    def action_reject(self):
        """Rejects OCR intake document with mandatory audit log."""
        for rec in self:
            rec.write({
                'state': 'rejected',
                'reviewed_by': self.env.user.id,
                'reviewed_at': fields.Datetime.now(),
            })
            rec.env['stocksense.audit.trail'].append_audit_block(
                event_type='OCR_REJECTED',
                record_reference=rec.name,
                payload={
                    'document_id': rec.id,
                    'reason': rec.review_notes or 'Rejected by user',
                    'rejected_by': self.env.user.name
                }
            )
        return True


class StocksenseOcrLine(models.Model):
    _name = 'stocksense.ocr.line'
    _description = 'StockSense Detected OCR Line Item'

    document_id = fields.Many2one('stocksense.ocr.document', string='OCR Document', required=True, ondelete='cascade')
    raw_description = fields.Char(string='Detected Item Text', required=True)
    detected_sku = fields.Char(string='Detected SKU')
    detected_qty = fields.Float(string='Detected Quantity', default=1.0, digits=(12, 2))
    detected_uom = fields.Char(string='Detected UoM', default='Units')
    confidence = fields.Float(string='Confidence (%)', digits=(5, 2))

    product_id = fields.Many2one('stocksense.product', string='Matched StockSense Product')
    match_status = fields.Selection([
        ('matched', 'Exact SKU Match'),
        ('review_required', 'Product Match Requires Review'),
        ('manual', 'Manually Selected'),
    ], string='Match Verification', default='review_required', required=True)

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.match_status = 'manual'
            if not self.detected_sku:
                self.detected_sku = self.product_id.sku

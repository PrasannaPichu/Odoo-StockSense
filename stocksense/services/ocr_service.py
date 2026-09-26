# -*- coding: utf-8 -*-
import io
import re
import logging
from datetime import datetime

_logger = logging.getLogger(__name__)

# Lazy initialization of RapidOCR engine
_RAPID_OCR_ENGINE = None

def get_ocr_engine():
    global _RAPID_OCR_ENGINE
    if _RAPID_OCR_ENGINE is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            _RAPID_OCR_ENGINE = RapidOCR()
            _logger.info("StockSense: RapidOCR ONNX Runtime CPU engine successfully initialized.")
        except Exception as e:
            _logger.error("StockSense: Failed to load RapidOCR engine: %s", e)
            raise RuntimeError(f"RapidOCR engine initialization failed: {e}")
    return _RAPID_OCR_ENGINE


def process_document_bytes(file_bytes, filename=''):
    """
    Perform local OCR extraction on uploaded image or PDF document.
    Never uses external cloud APIs; runs 100% on CPU inside Docker.
    Returns structured dict with raw text, field heuristics, and confidence.
    """
    if not file_bytes:
        return {'error': 'Empty document data provided.'}

    fn_lower = (filename or '').lower()
    is_pdf = fn_lower.endswith('.pdf') or file_bytes.startswith(b'%PDF')

    text_lines = []
    confidences = []

    if is_pdf:
        # Extract text directly from PDF if available
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            for page_idx, page in enumerate(reader.pages):
                extracted = page.extract_text()
                if extracted and extracted.strip():
                    for line in extracted.split('\n'):
                        l = line.strip()
                        if l:
                            text_lines.append(l)
                            confidences.append(99.0)  # High confidence for digital text
                # Also inspect any embedded images with OCR if text was sparse
                if len(text_lines) < 3 and getattr(page, 'images', None):
                    engine = get_ocr_engine()
                    for img_obj in page.images:
                        res, _ = engine(img_obj.data)
                        if res:
                            for bbox, txt, score in res:
                                text_lines.append(txt.strip())
                                confidences.append(float(score) * 100.0)
        except Exception as e:
            _logger.warning("PDF extraction failed, falling back: %s", e)

    # If not PDF or no text extracted from PDF, run computer vision OCR
    if not text_lines:
        try:
            import cv2
            import numpy as np
            engine = get_ocr_engine()
            nparr = np.frombuffer(file_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img is not None:
                res, _ = engine(img)
                if res:
                    for bbox, txt, score in res:
                        text_lines.append(txt.strip())
                        confidences.append(float(score) * 100.0)
            else:
                _logger.error("Failed to decode image bytes with OpenCV")
        except Exception as e:
            _logger.error("RapidOCR image processing failed: %s", e)
            return {'error': f'Image OCR execution error: {e}'}

    if not text_lines:
        return {
            'raw_text': '',
            'average_confidence': 0.0,
            'partner_name': '',
            'reference': '',
            'date': False,
            'phone': '',
            'email': '',
            'address': '',
            'tax_id': '',
            'lines': []
        }

    full_text = '\n'.join(text_lines)
    avg_conf = sum(confidences) / len(confidences) if confidences else 85.0

    # Parse key structured fields using deterministic regex and heuristic rules
    parsed = extract_document_fields(text_lines, full_text)
    parsed['raw_text'] = full_text
    parsed['average_confidence'] = round(avg_conf, 1)

    return parsed


def extract_document_fields(text_lines, full_text):
    """
    Semantic extractor for invoices, challans, packing slips, and partner registrations.
    Extracts: Partner Name, Reference, Date, Phone, Email, Tax ID, Address, and Line Items.
    """
    partner_name = ''
    reference = ''
    doc_date = False
    phone = ''
    email = ''
    tax_id = ''
    address = ''
    detected_lines = []

    # 1. Email extraction
    email_match = re.search(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', full_text)
    if email_match:
        email = email_match.group(0)

    # 2. Phone extraction
    phone_match = re.search(r'(?:Phone|Tel|Mobile|Contact)?[:\s]*(\+?[0-9]{1,3}[-.\s]?[0-9]{3,5}[-.\s]?[0-9]{4,6})', full_text, re.IGNORECASE)
    if phone_match and len(phone_match.group(1).strip()) >= 7:
        phone = phone_match.group(1).strip()

    # 3. Tax / GST / VAT ID
    tax_match = re.search(r'(?:GSTIN|GST|VAT|Tax\s*ID|TIN|EIN)[:\s]*([A-Z0-9]{8,18})', full_text, re.IGNORECASE)
    if tax_match:
        tax_id = tax_match.group(1).strip()

    # 4. Invoice / Document Reference
    ref_match = re.search(r'(?:Invoice(?:\s*(?:Number|#|No\.?))?|Inv(?:\s*(?:Number|#|No\.?))?|Bill(?:\s*(?:#|No\.?))?|PO(?:\s*(?:#|No\.?))?|Order(?:\s*(?:#|No\.?))?|Reference|Ref)[:\t ]+([A-Z0-9\-_/]{3,30})', full_text, re.IGNORECASE)
    if ref_match:
        reference = ref_match.group(1).strip()
    else:
        # Fallback search for standalone pattern like INV-OCR-2026-001 or INV-1042 or PO-9921
        standalone_ref = re.search(r'\b(INV[-_][A-Z0-9\-_]{2,20}|PO[-_]?[0-9]{3,8}|REC[-_]?[0-9]{3,8})\b', full_text, re.IGNORECASE)
        if standalone_ref:
            reference = standalone_ref.group(1).upper()

    # 5. Date detection (supports DD Month YYYY, YYYY-MM-DD, DD-MM-YYYY)
    months_map = {
        'january': 1, 'february': 2, 'march': 3, 'april': 4, 'may': 5, 'june': 6,
        'july': 7, 'august': 8, 'september': 9, 'october': 10, 'november': 11, 'december': 12,
        'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'jun': 6, 'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
    }
    m_text_date = re.search(r'(?:Invoice\s*Date|Date|Dated)?[:\s]*([0-9]{1,2})\s+([A-Za-z]{3,12})\s+([0-9]{4})', full_text, re.IGNORECASE)
    if m_text_date:
        d_day = int(m_text_date.group(1))
        d_mon_str = m_text_date.group(2).lower()
        d_year = int(m_text_date.group(3))
        d_mon = months_map.get(d_mon_str)
        if d_mon:
            doc_date = f"{d_year:04d}-{d_mon:02d}-{d_day:02d}"

    if not doc_date:
        date_patterns = [
            r'(?:Date|Dated)[:\s]*([0-9]{4}[-/][0-9]{1,2}[-/][0-9]{1,2})',
            r'(?:Date|Dated)[:\s]*([0-9]{1,2}[-/][0-9]{1,2}[-/][0-9]{2,4})',
            r'\b([0-9]{4}[-/][0-9]{2}[-/][0-9]{2})\b',
            r'\b([0-9]{1,2}[-/][0-9]{2}[-/][0-9]{4})\b'
        ]
        for pattern in date_patterns:
            dmatch = re.search(pattern, full_text, re.IGNORECASE)
            if dmatch:
                raw_d = dmatch.group(1).replace('/', '-')
                parts = raw_d.split('-')
                try:
                    if len(parts[0]) == 4:
                        # YYYY-MM-DD
                        doc_date = f"{parts[0]}-{int(parts[1]):02d}-{int(parts[2]):02d}"
                    elif len(parts[2]) == 4:
                        # DD-MM-YYYY
                        doc_date = f"{parts[2]}-{int(parts[1]):02d}-{int(parts[0]):02d}"
                    elif len(parts[2]) == 2:
                        doc_date = f"20{parts[2]}-{int(parts[1]):02d}-{int(parts[0]):02d}"
                    if doc_date:
                        break
                except Exception:
                    pass

    # 6. Partner / Supplier / Customer extraction
    p_match = re.search(r'(?:Supplier\s*Name|Vendor\s*Name|Customer\s*Name|Company\s*Name)[:\s]+([^\n\r]+)', full_text, re.IGNORECASE)
    if p_match:
        partner_name = p_match.group(1).strip()
    else:
        for idx, line in enumerate(text_lines[:8]):
            m_partner = re.search(r'(?:Supplier|Vendor|Customer|Billed\s*To|Sold\s*By|From|To)[:\s]+([^,\n\r]+)', line, re.IGNORECASE)
            if m_partner:
                p_val = m_partner.group(1).strip()
                if len(p_val) > 2 and not any(kw in p_val.lower() for kw in ['invoice', 'date', 'phone', 'total', 'information', 'details']):
                    partner_name = p_val
                    break

    # If not explicitly prefixed, look at top lines (excluding invoice/header titles)
    if not partner_name:
        for line in text_lines[:4]:
            cleaned = line.strip()
            lower = cleaned.lower()
            if (len(cleaned) >= 3 and
                not any(kw in lower for kw in ['invoice', 'delivery', 'receipt', 'tax', 'bill', 'date', 'page', 'tel', 'phone', 'email', 'gst']) and
                not re.match(r'^[0-9\W]+$', cleaned)):
                partner_name = cleaned
                break

    # 7. Address extraction heuristics
    addr_match = re.search(r'(?:Address|Street)[:\s]+([^\n\r]+)', full_text, re.IGNORECASE)
    if addr_match:
        address = addr_match.group(1).strip()
    else:
        addr_lines = []
        for line in text_lines[1:10]:
            lower = line.lower()
            if any(term in lower for term in ['street', 'road', 'st.', 'rd.', 'ave', 'suite', 'floor', 'industrial', 'area', 'zone', 'city', 'pin', 'zip', 'box']):
                addr_lines.append(line.strip())
        if addr_lines:
            address = ', '.join(addr_lines[:2])

    # 8. Product Line items extraction
    # Supports both multiline tabular layout (PDF cells on sequential lines) and single-line layout
    i = 0
    while i < len(text_lines):
        line = text_lines[i].strip()
        lower = line.lower()
        if any(kw in lower for kw in ['total', 'subtotal', 'tax', 'gst', 'vat', 'discount', 'payment', 'balance', 'terms', 'bank', 'due', 'bill to', 'supplier info', 'warehouse:']):
            i += 1
            continue

        # Check for multiline table row starting with SKU pattern (e.g. STEEL-ROD-10MM, BEARING-6204, IOT-SENSOR-V2)
        sku_m = re.match(r'^([A-Z0-9]{3,}-[A-Z0-9\-_]{2,})$', line)
        if sku_m and i + 1 < len(text_lines):
            sku = sku_m.group(1).upper()
            desc = ''
            qty = 0.0
            uom = 'Units'
            price = 0.0
            j = i + 1
            consumed = 0
            while j < len(text_lines) and consumed < 5:
                nxt = text_lines[j].strip()
                nxt_lower = nxt.lower()
                if any(kw in nxt_lower for kw in ['subtotal', 'total', 'tax:']):
                    break
                if re.match(r'^[A-Z0-9]{3,}-[A-Z0-9\-_]{2,}$', nxt):
                    break
                qty_num_m = re.match(r'^([0-9]+(?:\.[0-9]+)?)$', nxt)
                if qty_num_m and qty == 0.0:
                    val = float(qty_num_m.group(1))
                    if 0 < val < 100000 and val != 2026:
                        qty = val
                elif nxt_lower in ['units', 'pcs', 'kg', 'meters', 'nos', 'boxes', 'ea']:
                    uom = nxt
                elif re.match(r'^[0-9]+\.[0-9]{2}$', nxt) and qty > 0.0 and price == 0.0:
                    price = float(nxt)
                elif not desc and not qty_num_m and len(nxt) > 2:
                    desc = nxt
                j += 1
                consumed += 1

            if qty > 0:
                detected_lines.append({
                    'raw_description': desc or sku,
                    'detected_sku': sku,
                    'detected_qty': qty,
                    'detected_uom': uom,
                    'detected_price': price
                })
                i = j
                continue

        # Single-line format fallback: "Steel Rod 10mm QTY: 100", "BEAR-6204 50 units"
        qty_match = re.search(r'(?:Qty|Quantity|Units|Pcs|Count)?[:\s]*([0-9]+(?:\.[0-9]+)?)\s*(?:Units|Pcs|Kg|Meters|Nos|Boxes)?\b', line, re.IGNORECASE)
        sku_match = re.search(r'\b([A-Z0-9]{3,}-[A-Z0-9\-_]{2,})\b', line)
        if qty_match and sku_match:
            try:
                candidate_qty = float(qty_match.group(1))
                if 0 < candidate_qty < 100000 and candidate_qty != 2026:
                    sku = sku_match.group(1).upper()
                    clean_desc = re.sub(r'(?:Qty|Quantity|Units|Pcs)?[:\s]*[0-9]+(?:\.[0-9]+)?', '', line, flags=re.IGNORECASE).strip()
                    clean_desc = re.sub(r'[:#\-–]+$', '', clean_desc).strip()
                    if clean_desc and not any(kw in clean_desc.lower() for kw in ['invoice', 'date', 'page', 'phone', 'vendor', 'supplier']):
                        detected_lines.append({
                            'raw_description': clean_desc or sku,
                            'detected_sku': sku,
                            'detected_qty': candidate_qty,
                            'detected_uom': 'Units',
                            'detected_price': 0.0
                        })
            except Exception:
                pass

        i += 1

    parsed = {
        'partner_name': partner_name,
        'reference': reference,
        'date': doc_date,
        'phone': phone,
        'email': email,
        'address': address,
        'tax_id': tax_id,
        'lines': detected_lines
    }
    return parsed

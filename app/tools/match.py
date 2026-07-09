from typing import List, Tuple, Optional
from rapidfuzz import fuzz
from app.schema import NormalizedRecord

def find_candidate_match(
    invoice: NormalizedRecord, 
    po_list: List[NormalizedRecord], 
    receipt_list: List[NormalizedRecord]
) -> Tuple[Optional[NormalizedRecord], Optional[NormalizedRecord]]:
    """
    Attempts to find the matching PO and Receipt for an invoice.
    1. First tries exact PO-number match.
    2. Falls back to rapidfuzz vendor-name similarity matching (threshold >= 80).
    Returns (po, receipt) tuple.
    """
    po_match: Optional[NormalizedRecord] = None
    receipt_match: Optional[NormalizedRecord] = None

    # 1. Try exact PO-number match if po_number is present
    if invoice.po_number:
        # Find PO
        for po in po_list:
            if po.po_number == invoice.po_number:
                po_match = po
                break
        
        # Find Receipt
        for receipt in receipt_list:
            if receipt.po_number == invoice.po_number:
                receipt_match = receipt
                break
        
        if po_match:
            return po_match, receipt_match

    # 2. Fallback to fuzzy vendor-name matching
    best_po: Optional[NormalizedRecord] = None
    best_po_score = 0.0

    for po in po_list:
        # Compare normalized vendor names
        score = fuzz.WRatio(invoice.vendor_name, po.vendor_name)
        if score > best_po_score:
            best_po_score = score
            best_po = po

    # Only accept match if similarity is at or above threshold
    if best_po and best_po_score >= 80.0:
        po_match = best_po
        # Once we have the PO, find its corresponding receipt
        for receipt in receipt_list:
            if receipt.po_number == po_match.po_number:
                receipt_match = receipt
                break
        return po_match, receipt_match

    # If no PO matched, try matching receipt directly by vendor name
    best_receipt: Optional[NormalizedRecord] = None
    best_receipt_score = 0.0
    for receipt in receipt_list:
        score = fuzz.WRatio(invoice.vendor_name, receipt.vendor_name)
        if score > best_receipt_score:
            best_receipt_score = score
            best_receipt = receipt

    if best_receipt and best_receipt_score >= 80.0:
        return None, best_receipt

    return None, None

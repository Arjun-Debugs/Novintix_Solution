from typing import Tuple, List, Dict, Any, Optional
from rapidfuzz import fuzz
from app.schema import NormalizedRecord

def score_match(
    invoice: NormalizedRecord,
    po: Optional[NormalizedRecord],
    receipt: Optional[Optional[NormalizedRecord]]
) -> Tuple[int, List[str], Dict[str, Any]]:
    """
    Computes a weighted confidence score (0-100) based on:
    1. Amount delta % (weight 40)
    2. Vendor name similarity (weight 25)
    3. Date plausibility (weight 15)
    4. Quantity match if present (weight 20)
    
    Returns (score, reasons, discrepancies).
    """
    reasons = []
    discrepancies = {}
    
    # 1. Amount Delta (weight 40)
    amount_score = 0.0
    amount_delta_pct = 100.0
    
    if po is not None or receipt is not None:
        # Determine comparison amount (prefer PO, fall back to receipt)
        compare_amount = po.amount_inr if po is not None else receipt.amount_inr
        
        if compare_amount > 0:
            amount_delta_pct = (abs(invoice.amount_inr - compare_amount) / compare_amount) * 100.0
        elif invoice.amount_inr == 0 and compare_amount == 0:
            amount_delta_pct = 0.0
        else:
            amount_delta_pct = 100.0
            
        amount_delta_pct = round(amount_delta_pct, 2)
        
        if amount_delta_pct == 0.0:
            amount_score = 40.0
            reasons.append("Amount matches exactly after currency conversion (40.0/40 pts)")
        else:
            # Linear decay up to 15% discrepancy, after which it drops to 0
            decay = max(0.0, 1.0 - (amount_delta_pct / 15.0))
            amount_score = 40.0 * decay
            reasons.append(
                f"Amount differs by {amount_delta_pct}% after FX conversion. "
                f"Expected {compare_amount} INR, got {invoice.amount_inr} INR "
                f"({round(amount_score, 2)}/40 pts)"
            )
    else:
        reasons.append("No purchase order or receipt found for amount comparison (0.0/40 pts)")
        
    discrepancies["amount_delta_pct"] = amount_delta_pct

    # 2. Vendor Name Similarity (weight 25)
    vendor_score = 0.0
    vendor_match_score = 0.0
    
    if po is not None or receipt is not None:
        compare_vendor = po.vendor_name if po is not None else receipt.vendor_name
        vendor_match_score = fuzz.WRatio(invoice.vendor_name, compare_vendor)
        vendor_score = 25.0 * (vendor_match_score / 100.0)
        reasons.append(
            f"Vendor similarity is {round(vendor_match_score, 1)}% "
            f"('{invoice.vendor_name}' vs '{compare_vendor}') "
            f"({round(vendor_score, 2)}/25 pts)"
        )
    else:
        reasons.append("No matching document found to compare vendor name (0.0/25 pts)")
        
    discrepancies["vendor_match_score"] = float(vendor_match_score)

    # 3. Date Plausibility (weight 15)
    date_score = 0.0
    date_valid = False
    
    if po is not None:
        # Invoice date should be after or equal to PO date
        if invoice.date >= po.date:
            date_valid = True
            date_score = 15.0
            reasons.append(
                f"Date plausibility verified: Invoice date {invoice.date} is on/after PO date {po.date} (15.0/15 pts)"
            )
        else:
            reasons.append(
                f"Date plausibility check failed: Invoice date {invoice.date} is before PO date {po.date} (0.0/15 pts)"
            )
    else:
        reasons.append("No PO found to verify date plausibility (0.0/15 pts)")
        
    discrepancies["date_valid"] = date_valid

    # 4. Quantity Match (weight 20)
    quantity_score = 20.0
    if po is not None:
        if invoice.quantity is not None and po.quantity is not None:
            if invoice.quantity == po.quantity:
                reasons.append(
                    f"Quantities match: {invoice.quantity} units (20.0/20 pts)"
                )
            else:
                quantity_score = 0.0
                reasons.append(
                    f"Quantity mismatch: Invoice has {invoice.quantity} units but PO expects {po.quantity} units (0.0/20 pts)"
                )
        else:
            reasons.append("Quantity not specified on both invoice and PO; defaulting to match (20.0/20 pts)")
    else:
        reasons.append("No PO found for quantity match; defaulting to match (20.0/20 pts)")

    total_score = amount_score + vendor_score + date_score + quantity_score
    rounded_score = int(round(total_score))
    # Cap between 0 and 100
    final_score = max(0, min(100, rounded_score))
    
    return final_score, reasons, discrepancies

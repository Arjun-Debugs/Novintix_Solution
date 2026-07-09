import datetime
from typing import List, Dict, Any
from app.schema import MatchResult, NormalizedRecord
from app.tools.normalize import normalize_record, load_fx_rates
from app.tools.match import find_candidate_match
from app.tools.confidence import score_match
from app.tools.router import route_decision

def generate_summary(status: str, score: int, discrepancies: Dict[str, Any], po_id: str | None) -> str:
    """
    Generates a plain-English one-line summary of the routing decision and key factors.
    """
    amount_delta = discrepancies.get("amount_delta_pct", 100.0)
    vendor_score = discrepancies.get("vendor_match_score", 0.0)
    date_valid = discrepancies.get("date_valid", False)
    
    if status == "auto_approved":
        return f"Approved: Perfect match with PO {po_id} and receipt (Confidence: {score}%)."
        
    elif status == "needs_human_review":
        conditions = []
        if amount_delta > 0:
            conditions.append(f"amount off by {amount_delta}%")
        if vendor_score < 100.0:
            conditions.append(f"vendor name mismatch ({round(vendor_score, 1)}% similarity)")
        if not date_valid:
            conditions.append("invoice date before PO date")
            
        cond_str = " and ".join(conditions) if conditions else "minor discrepancies"
        return f"Flagged: {cond_str} — recommend manual check."
        
    else:  # escalated
        if po_id is None:
            return "Escalated: Critical matching check failed — no matching purchase order found."
        elif amount_delta > 10.0:
            return f"Escalated: High amount discrepancy of {amount_delta}% (exceeds 10% tolerance threshold)."
        else:
            return f"Escalated: Low confidence match ({score}%) due to multiple discrepancies."

def process_invoice(
    invoice_raw: Dict[str, Any],
    po_list_raw: List[Dict[str, Any]],
    receipt_list_raw: List[Dict[str, Any]],
    fx_rates: Dict[str, float] = None
) -> MatchResult:
    """
    Runs the full normalization, matching, confidence scoring, and routing pipeline for an invoice.
    """
    if fx_rates is None:
        fx_rates = load_fx_rates()
        
    # 1. Normalize
    invoice_norm = normalize_record(invoice_raw, fx_rates)
    po_norms = [normalize_record(po, fx_rates) for po in po_list_raw]
    receipt_norms = [normalize_record(rec, fx_rates) for rec in receipt_list_raw]
    
    # 2. Match
    po_match, receipt_match = find_candidate_match(invoice_norm, po_norms, receipt_norms)
    
    # 3. Confidence Scorer
    score, reasons, discrepancies = score_match(invoice_norm, po_match, receipt_match)
    
    # 4. Route Decision
    status = route_decision(score)
    
    # 5. Extract IDs
    po_id = po_match.record_id if po_match is not None else None
    receipt_id = receipt_match.record_id if receipt_match is not None else None
    
    # 6. Generate plain-English summary
    summary = generate_summary(status, score, discrepancies, po_id)
    
    # 7. Timestamp
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    return MatchResult(
        invoice_id=invoice_norm.record_id,
        po_id=po_id,
        receipt_id=receipt_id,
        status=status,
        confidence_score=score,
        normalized_amount=invoice_norm.amount_inr,
        normalized_amount_inr=invoice_norm.amount_inr,
        discrepancies=discrepancies,
        reasons=reasons,
        timestamp=timestamp,
        summary=summary
    )

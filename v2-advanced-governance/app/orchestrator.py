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
    fx_rates: Dict[str, float] = None,
    db_path: str = None
) -> MatchResult:
    """
    Runs the full reconciliation pipeline (normalization, matching, scoring, routing, and shadow ML prediction).
    """
    # 1. Normalize
    invoice_norm = normalize_record(invoice_raw, fx_rates, db_path=db_path)
    po_norms = [normalize_record(po, fx_rates, db_path=db_path) for po in po_list_raw]
    receipt_norms = [normalize_record(rec, fx_rates, db_path=db_path) for rec in receipt_list_raw]
    
    # 2. Match
    po_match, receipt_match = find_candidate_match(invoice_norm, po_norms, receipt_norms)
    
    # 3. Confidence Scorer
    score, reasons, discrepancies = score_match(invoice_norm, po_match, receipt_match)
    
    # 4. Route Decision
    status = route_decision(score, db_path)
    
    # 5. Extract IDs
    po_id = po_match.record_id if po_match is not None else None
    receipt_id = receipt_match.record_id if receipt_match is not None else None
    
    # 6. Generate plain-English summary
    summary = generate_summary(status, score, discrepancies, po_id)
    
    # 7. Timestamp
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    # 8. Call shadow ML prediction (no impact on routing/status)
    from app.tools.ml_scorer import shadow_predict
    if db_path:
        shadow_predict(invoice_norm.record_id, reasons, score, db_path=db_path)
    else:
        shadow_predict(invoice_norm.record_id, reasons, score)
    
    return MatchResult(
        invoice_id=invoice_norm.record_id,
        vendor_name=invoice_norm.vendor_name,
        invoice_date=invoice_norm.date,
        po_id=po_id,
        receipt_id=receipt_id,
        status=status,
        confidence_score=score,
        normalized_amount=invoice_norm.amount_inr,
        normalized_amount_inr=invoice_norm.amount_inr,
        discrepancies=discrepancies,
        reasons=reasons,
        timestamp=timestamp,
        summary=summary,
        explanation_text=None
    )

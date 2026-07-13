import os
from datetime import datetime
from typing import List, Dict, Any, Optional
from app.audit import init_db, DEFAULT_DB_PATH
from app.db import OverrideRepository
from app.schema import ReviewOverride

def init_review_db(db_path: str = DEFAULT_DB_PATH) -> None:
    init_db(db_path)

def validate_override(
    machine_status: str,
    human_decision: str,
    reviewer_note: str,
    is_admin: bool = False
) -> tuple[bool, str]:
    """
    Validates a human override request.
    Validation rules:
    - human_decision must be in {"approved", "rejected", "disputed"}
    - "disputed" requires a reviewer_note of at least 10 characters
    - auto_approved items: only "disputed" is valid
    - needs_human_review / escalated items: "disputed" is invalid; only "approved" or "rejected" are valid
    """
    decision = human_decision.strip().lower()
    
    if decision not in {"approved", "rejected", "disputed"}:
        return False, f"Invalid human decision: '{human_decision}'. Must be one of approved, rejected, or disputed."
        
    if decision == "disputed" and len(reviewer_note.strip()) < 10:
        return False, "Disputed overrides require a detailed reviewer note (min 10 characters)."
        
    m_status = machine_status.strip().lower()
    
    if m_status == "auto_approved":
        if decision != "disputed":
            return False, "Auto-approved items can only be disputed."
    else:  # needs_human_review or escalated
        if decision == "disputed":
            return False, "Dispute is invalid for reviewable or escalated items. Choose Approve or Reject."
            
    return True, "Validation successful."

def log_override(
    invoice_id: str,
    reviewer: str | int,
    machine_status: str,
    machine_score: int,
    human_decision: str,
    reviewer_note: str = "",
    db_path: str = DEFAULT_DB_PATH
) -> None:
    """
    Logs an override event to the review_overrides table using OverrideRepository.
    """
    init_review_db(db_path)
    repo = OverrideRepository(db_path)
    override = ReviewOverride(
        invoice_id=invoice_id,
        reviewer=str(reviewer).strip(),
        machine_status=machine_status,
        machine_score=machine_score,
        human_decision=human_decision.strip().lower(),
        reviewer_note=reviewer_note.strip(),
        timestamp=datetime.utcnow().isoformat()
    )
    repo.log(override)

def get_override(invoice_id: str, db_path: str = DEFAULT_DB_PATH) -> Optional[Dict[str, Any]]:
    """
    Retrieves the most recent override logged for a specific invoice.
    """
    init_review_db(db_path)
    repo = OverrideRepository(db_path)
    o = repo.get_latest(invoice_id)
    if o:
        return {
            "id": o.id,
            "invoice_id": o.invoice_id,
            "reviewer_name": o.reviewer,
            "reviewer_role": "admin",
            "machine_status": o.machine_status,
            "machine_score": o.machine_score,
            "human_decision": o.human_decision,
            "reviewer_note": o.reviewer_note,
            "timestamp": o.timestamp
        }
    return None

def get_all_overrides(db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """
    Retrieves all review overrides logged.
    """
    init_review_db(db_path)
    repo = OverrideRepository(db_path)
    rows = repo.get_all()
    return [
        {
            "id": o.id,
            "invoice_id": o.invoice_id,
            "reviewer_name": o.reviewer,
            "reviewer_role": "admin",
            "machine_status": o.machine_status,
            "machine_score": o.machine_score,
            "human_decision": o.human_decision,
            "reviewer_note": o.reviewer_note,
            "timestamp": o.timestamp
        }
        for o in rows
    ]

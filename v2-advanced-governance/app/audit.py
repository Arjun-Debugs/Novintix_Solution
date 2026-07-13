import os
from app.schema import MatchResult
from app.db_migrations import run_migrations
from app.db import DecisionRepository

DEFAULT_DB_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "data", "decisions.db")
)

def init_db(db_path: str = DEFAULT_DB_PATH):
    """
    Initializes the database schema using run_migrations.
    """
    run_migrations(db_path)

def log_decision(match_result: MatchResult, db_path: str = DEFAULT_DB_PATH):
    """
    Logs a decision to the database using DecisionRepository.
    """
    init_db(db_path)
    repo = DecisionRepository(db_path)
    repo.upsert(match_result)

def get_all_decisions(db_path: str = DEFAULT_DB_PATH) -> list:
    """
    Retrieves all non-archived decisions as dicts.
    """
    init_db(db_path)
    repo = DecisionRepository(db_path)
    results = repo.get_all(include_archived=False)
    decisions = []
    for r in results:
        decisions.append({
            "invoice_id": r.invoice_id,
            "status": r.status,
            "confidence_score": r.confidence_score,
            "reasons": r.reasons,
            "timestamp": r.timestamp,
            "vendor_name": r.vendor_name,
            "po_id": r.po_id,
            "receipt_id": r.receipt_id,
            "normalized_amount": r.normalized_amount,
            "normalized_amount_inr": r.normalized_amount_inr,
            "discrepancies": r.discrepancies,
            "summary": r.summary,
            "explanation_text": r.explanation_text
        })
    return decisions

def clear_decisions(db_path: str = DEFAULT_DB_PATH):
    """
    Soft-deletes (archives) all decisions.
    """
    init_db(db_path)
    repo = DecisionRepository(db_path)
    repo.archive_all()

# Safety-critical status routing bands (defaults)
DEFAULT_APPROVED_THRESHOLD = 95.0
DEFAULT_REVIEW_THRESHOLD = 80.0

def route_decision(score: int, db_path: str = None) -> str:
    """
    Routes an invoice to a status band based on its confidence score.
    Loads thresholds dynamically from ConfigRepository if database is available.
    - score >= approved_threshold -> "auto_approved"
    - review_threshold <= score < approved_threshold -> "needs_human_review"
    - score < review_threshold -> "escalated"
    """
    try:
        from app.db import ConfigRepository
        repo = ConfigRepository(db_path)
        approved_threshold = repo.get_value("approved_threshold", DEFAULT_APPROVED_THRESHOLD)
        review_threshold = repo.get_value("review_threshold", DEFAULT_REVIEW_THRESHOLD)
    except Exception:
        approved_threshold = DEFAULT_APPROVED_THRESHOLD
        review_threshold = DEFAULT_REVIEW_THRESHOLD

    if score >= approved_threshold:
        return "auto_approved"
    elif score >= review_threshold:
        return "needs_human_review"
    else:
        return "escalated"

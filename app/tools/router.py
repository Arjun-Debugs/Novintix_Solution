# Safety-critical status routing bands
APPROVED_THRESHOLD = 95
REVIEW_THRESHOLD = 80

def route_decision(score: int) -> str:
    """
    Routes an invoice to a status band based on its confidence score.
    - score >= APPROVED_THRESHOLD -> "auto_approved"
    - REVIEW_THRESHOLD <= score < APPROVED_THRESHOLD -> "needs_human_review"
    - score < REVIEW_THRESHOLD -> "escalated"
    """
    if score >= APPROVED_THRESHOLD:
        return "auto_approved"
    elif score >= REVIEW_THRESHOLD:
        return "needs_human_review"
    else:
        return "escalated"

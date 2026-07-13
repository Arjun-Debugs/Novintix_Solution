import os
import json
import logging
import google.generativeai as genai
from app.schema import MatchResult

logger = logging.getLogger(__name__)

def generate_local_explanation(result: MatchResult) -> str:
    """
    A fallback generator that builds a detailed, structured markdown breakdown
    of the matching criteria scores, weights, discrepancies, and triggered gates.
    """
    status_label = result.status.upper().replace("_", " ")
    
    # Analyze components from reasons/discrepancies
    amount_delta = result.discrepancies.get("amount_delta_pct", 100.0)
    vendor_score = result.discrepancies.get("vendor_match_score", 0.0)
    date_valid = result.discrepancies.get("date_valid", False)
    
    # Calculate approximate component scores
    # Amount (40 points)
    if result.po_id is None and result.receipt_id is None:
        amount_desc = "No matching document found to compare amount."
        amount_pts = 0.0
    elif amount_delta == 0.0:
        amount_desc = "Amount matches exactly after currency conversion."
        amount_pts = 40.0
    else:
        decay = max(0.0, 1.0 - (amount_delta / 15.0))
        amount_pts = round(40.0 * decay, 2)
        amount_desc = f"Amount differs by {amount_delta:.1f}% variance. Expected matching document amount, but invoice is {result.normalized_amount_inr:,.2f} INR."
        
    # Vendor (25 points)
    if result.po_id is None and result.receipt_id is None:
        vendor_desc = "No matching document found to compare vendor name."
        vendor_pts = 0.0
    else:
        vendor_pts = round(25.0 * (vendor_score / 100.0), 2)
        vendor_desc = f"Vendor name similarity score is {vendor_score:.1f}%."

    # Date (15 points)
    if result.po_id is None:
        date_desc = "No PO found to verify date plausibility."
        date_pts = 0.0
    elif date_valid:
        date_desc = "Invoice date is after or on the PO date (Plausible chronology)."
        date_pts = 15.0
    else:
        date_desc = f"Invoice date ({result.invoice_date}) is before the PO date (Chronology anomaly)."
        date_pts = 0.0

    # Quantity (20 points)
    qty_reasons = [r for r in result.reasons if "Quantities match" in r or "Quantity mismatch" in r or "Quantity not specified" in r]
    qty_desc = qty_reasons[0] if qty_reasons else "Quantity check default pass."
    qty_pts = 20.0 if not any("Quantity mismatch" in r for r in qty_reasons) else 0.0

    md = f"""### Deterministic Match Verdict Breakdown (Rule-Based Fallback)
The system reached the routing status **{status_label}** with a confidence score of **{result.confidence_score}/100** based on the following evaluation:

#### Field-Level Assessment:
1. **Invoice Amount Match** (*Weight: 40 pts*): **{amount_pts}/40 pts**
   - *Status*: {amount_desc}
2. **Vendor Name Alignment** (*Weight: 25 pts*): **{vendor_pts}/25 pts**
   - *Status*: {vendor_desc}
3. **Chronology & Date Validity** (*Weight: 15 pts*): **{date_pts}/15 pts**
   - *Status*: {date_desc}
4. **Quantity Reconciliation** (*Weight: 20 pts*): **{qty_pts}/20 pts**
   - *Status*: {qty_desc}

#### Triggered Gate Logic:
"""
    if result.status == "auto_approved":
        md += f"- **Approved Gate**: Score is `{result.confidence_score}`, which meets or exceeds the auto-approval threshold of `95`. No critical discrepancies were flagged."
    elif result.status == "needs_human_review":
        md += f"- **Review Gate**: Score is `{result.confidence_score}`, which is below the auto-approval threshold of `95` but is at or above the review threshold of `80`. Flagged for secondary human inspection to verify minor discrepancies (e.g. amount variance or name typography)."
    else: # escalated
        md += f"- **Escalation Gate**: Score is `{result.confidence_score}`, which falls below the review threshold of `80`. This represents a high-risk transaction due to major discrepancies (such as a missing PO, a price variance exceeding 10%, or chronology violation)."

    return md

def generate_decision_explanation(result: MatchResult) -> str:
    """
    Generates a rich explanation of the reconciliation status and confidence score.
    Uses the Groq API (llama3-70b-8192) with a fallback to a structured rule-based local explanation.
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return generate_local_explanation(result)

    try:
        import requests
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        # Prepare context for prompt
        prompt = f"""
You are an AI financial assistant explaining an automated invoice reconciliation status routing decision.
Your audience is a human finance reviewer. Keep the language plain, simple, and direct. Avoid dense auditor jargon.

Context:
- Invoice ID: {result.invoice_id}
- Vendor Name: {result.vendor_name}
- Invoice Date: {result.invoice_date}
- Normalized Amount: {result.normalized_amount_inr:,.2f} INR
- Matched PO ID: {result.po_id or "None (Missing)"}
- Matched Receipt ID: {result.receipt_id or "None (Missing)"}

Matching Outcome & Routing:
- Status Routing Decision: {result.status}
- Confidence Score: {result.confidence_score}/100

Discrepancies JSON:
{json.dumps(result.discrepancies, indent=2)}

Audit Trail / Reasons Evaluated:
{json.dumps(result.reasons, indent=2)}

Task Instructions:
Write a plain, simple explanation of the reconciliation outcome.
You MUST format your output exactly as three lines (no bullet points, hyphens, or list formatters):
Summary: A simple, one-sentence English statement explaining why the invoice got routed to '{result.status}' (mentioning the score {result.confidence_score} and relevant thresholds).
Likely cause: A simple explanation of what specific mismatch or missing document caused the score reduction (referencing the exact field differences, like vendor names, amount delta %, date chronology, or quantity mismatch).
Suggested action: A simple, practical next step for the human reviewer.

Do not use high-level auditor jargon. Keep the wording clear, friendly, and easy to read. Write under 120 words.
"""
        payload = {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": "You are a helpful Accounts Payable assistant. You write plain, simple, and direct explanations for invoice reconciliation matches. You format your output as exactly three plain lines starting with Summary:, Likely cause:, and Suggested action:."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2
        }
        
        response = requests.post(url, json=payload, headers=headers, timeout=12)
        if response.status_code == 200:
            text = response.json()["choices"][0]["message"]["content"].strip()
            if text:
                return text
        else:
            logger.error(f"Groq API error (status {response.status_code}): {response.text}")
    except Exception as e:
        logger.error(f"Error generating explanation from Groq: {e}")
        # Fall through to local fallback
    
    return generate_local_explanation(result)

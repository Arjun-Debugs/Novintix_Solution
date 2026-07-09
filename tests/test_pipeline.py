import sys
import os

# Add project root to Python search path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import json
import sqlite3
import pytest
from app.schema import MatchResult, NormalizedRecord
from app.tools.normalize import normalize_record, clean_amount_string, parse_date_to_iso, load_fx_rates
from app.tools.match import find_candidate_match
from app.tools.confidence import score_match
from app.tools.router import route_decision, APPROVED_THRESHOLD, REVIEW_THRESHOLD
from app.orchestrator import process_invoice, generate_summary
from app.audit import log_decision, get_all_decisions, init_db, clear_decisions

# Setup paths relative to test file location
TEST_DIR = os.path.dirname(__file__)
BASE_DIR = os.path.abspath(os.path.join(TEST_DIR, ".."))
INVOICES_PATH = os.path.join(BASE_DIR, "data", "erp_a_invoices.json")
POS_PATH = os.path.join(BASE_DIR, "data", "erp_b_purchase_orders.json")
RECEIPTS_PATH = os.path.join(BASE_DIR, "data", "erp_c_receipts.json")
FX_PATH = os.path.join(BASE_DIR, "data", "fx_rates.json")
TEST_DB_PATH = os.path.join(BASE_DIR, "data", "test_decisions.db")

# 1. Count checks
def test_data_counts():
    assert os.path.exists(INVOICES_PATH), "Invoices file missing"
    assert os.path.exists(POS_PATH), "POs file missing"
    assert os.path.exists(RECEIPTS_PATH), "Receipts file missing"
    assert os.path.exists(FX_PATH), "FX rates file missing"
    
    with open(INVOICES_PATH, "r") as f:
        invoices = json.load(f)
    with open(POS_PATH, "r") as f:
        pos = json.load(f)
    with open(RECEIPTS_PATH, "r") as f:
        receipts = json.load(f)
    with open(FX_PATH, "r") as f:
        fx = json.load(f)
        
    assert len(invoices) == 5, f"Expected 5 invoices, got {len(invoices)}"
    assert len(pos) == 5, f"Expected 5 POs, got {len(pos)}"
    assert len(receipts) == 5, f"Expected 5 receipts, got {len(receipts)}"
    assert len(fx) == 3, f"Expected 3 FX rates, got {len(fx)}"

# 2. Schema serialization
def test_schema_serialization():
    m = MatchResult(
        invoice_id="INV-TEST",
        po_id="PO-TEST",
        receipt_id="REC-TEST",
        status="auto_approved",
        confidence_score=100,
        normalized_amount=83500.0,
        normalized_amount_inr=83500.0,
        discrepancies={"amount_delta_pct": 0.0, "vendor_match_score": 100.0, "date_valid": True},
        reasons=["Perfect match test"],
        timestamp="2026-07-09T12:00:00Z",
        summary="Approved: Perfect match."
    )
    json_str = m.model_dump_json()
    assert isinstance(json_str, str)
    loaded = json.loads(json_str)
    assert loaded["invoice_id"] == "INV-TEST"
    assert loaded["confidence_score"] == 100

# 3. Normalization Tool
def test_normalization():
    # Load rates
    fx_rates = {"USD": 83.5, "EUR": 90.0, "INR": 1.0}
    
    # Test case from prompt
    raw_record = {"amount": "$1,200.00", "currency": "USD", "date": "07/09/2026", "vendor_name": " Acme Corp "}
    res = normalize_record(raw_record, fx_rates)
    
    assert res.amount_inr == 100200.0, f"Expected 100200.0, got {res.amount_inr}"
    assert res.date == "2026-07-09", f"Expected 2026-07-09, got {res.date}"
    assert res.vendor_name == "acme corp"
    
    # European format check
    raw_record_eu = {"amount": "€ 500,00", "currency": "EUR", "date": "2026-07-08", "vendor_name": "Globex"}
    res_eu = normalize_record(raw_record_eu, fx_rates)
    assert res_eu.amount_inr == 45000.0, f"Expected 45000.0, got {res_eu.amount_inr}"

# 4. Matching Tool
def test_fuzzy_matching_fallback():
    fx_rates = {"USD": 83.5, "EUR": 90.0, "INR": 1.0}
    
    invoice = normalize_record({
        "invoice_id": "INV-001",
        "vendor_name": "Acme Corp",
        "amount": "$1,200.00",
        "currency": "USD",
        "invoice_date": "2026-07-09"
    }, fx_rates)
    
    # PO has typo: "Acme Corporation"
    pos = [
        normalize_record({
            "po_number": "PO-101",
            "vendor_name": "Acme Corporation",
            "amount": "$1,200.00",
            "currency": "USD",
            "po_date": "2026-07-01"
        }, fx_rates)
    ]
    
    receipts = [
        normalize_record({
            "receipt_id": "REC-201",
            "po_number": "PO-101",
            "vendor_name": "Acme Corporation",
            "amount": "$1,200.00",
            "currency": "USD",
            "receipt_date": "2026-07-05"
        }, fx_rates)
    ]
    
    po_match, receipt_match = find_candidate_match(invoice, pos, receipts)
    assert po_match is not None, "Failed to match PO with typo'd vendor"
    assert po_match.po_number == "PO-101"
    assert receipt_match is not None
    assert receipt_match.record_id == "REC-201"

# 5. Confidence Scorer
def test_confidence_scorer():
    fx_rates = {"USD": 83.5, "EUR": 90.0, "INR": 1.0}
    
    # Perfect match scenario
    inv = normalize_record({"amount": "$1,000.00", "currency": "USD", "date": "2026-07-09", "vendor_name": "Acme", "quantity": 10}, fx_rates)
    po = normalize_record({"po_number": "PO-1", "amount": "$1,000.00", "currency": "USD", "date": "2026-07-01", "vendor_name": "Acme", "quantity": 10}, fx_rates)
    rec = normalize_record({"receipt_id": "REC-1", "po_number": "PO-1", "amount": "$1,000.00", "currency": "USD", "date": "2026-07-05", "vendor_name": "Acme", "quantity": 10}, fx_rates)
    
    score, reasons, discrepancies = score_match(inv, po, rec)
    assert score >= 95, f"Perfect match score should be >= 95, got {score}"
    
    # Amount mismatch of 15% scenario (linear decay to 0 points at 15% delta)
    inv_err = normalize_record({"amount": "$1,150.00", "currency": "USD", "date": "2026-07-09", "vendor_name": "Acme", "quantity": 10}, fx_rates)
    score_err, _, _ = score_match(inv_err, po, rec)
    # Vendor=25, Date=15, Qty=20 = 60. Amount=0 (since 15% discrepancy). Total=60.
    assert score_err <= 70, f"15% amount mismatch score should be <= 70, got {score_err}"

# 6. Threshold Router
def test_threshold_router():
    assert route_decision(96) == "auto_approved"
    assert route_decision(85) == "needs_human_review"
    assert route_decision(50) == "escalated"

# 7. Orchestrator
def test_orchestrator_pipeline():
    with open(INVOICES_PATH, "r") as f:
        invoices_raw = json.load(f)
    with open(POS_PATH, "r") as f:
        pos_raw = json.load(f)
    with open(RECEIPTS_PATH, "r") as f:
        receipts_raw = json.load(f)
        
    results = []
    statuses = set()
    for inv in invoices_raw:
        res = process_invoice(inv, pos_raw, receipts_raw)
        results.append(res)
        statuses.add(res.status)
        assert isinstance(res, MatchResult)
        assert len(res.reasons) > 0
        
    assert len(results) == 5
    # Seeded data should produce auto_approved, needs_human_review, and escalated
    assert "auto_approved" in statuses
    assert "needs_human_review" in statuses
    assert "escalated" in statuses

# 8. Audit Log
def test_audit_logging():
    # Initialize and clear DB
    init_db(TEST_DB_PATH)
    clear_decisions(TEST_DB_PATH)
    
    # Log 5 dummy decisions
    for i in range(1, 6):
        res = MatchResult(
            invoice_id=f"INV-DUMMY-{i}",
            po_id=f"PO-{i}",
            receipt_id=f"REC-{i}",
            status="auto_approved" if i % 2 == 0 else "needs_human_review",
            confidence_score=90,
            normalized_amount=100.0,
            normalized_amount_inr=100.0,
            discrepancies={"amount_delta_pct": 0.0, "vendor_match_score": 100.0, "date_valid": True},
            reasons=["Reconciled successfully"],
            timestamp="2026-07-09T13:00:00Z",
            summary="Approved"
        )
        log_decision(res, TEST_DB_PATH)
        
    decisions = get_all_decisions(TEST_DB_PATH)
    assert len(decisions) == 5, f"Expected 5 decisions logged, got {len(decisions)}"
    
    # Cleanup test DB
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)

# 10. Edge cases (missing PO, zero amount, unparseable date) and Summary Generator
def test_edge_cases():
    fx_rates = {"USD": 83.5, "EUR": 90.0, "INR": 1.0}
    
    # Missing PO / Receipt
    inv_missing = normalize_record({"amount": "$500.00", "currency": "USD", "date": "2026-07-09", "vendor_name": "Cyberdyne"}, fx_rates)
    score, reasons, discrepancies = score_match(inv_missing, None, None)
    assert score < 50, f"Expected low score for missing PO, got {score}"
    assert discrepancies["amount_delta_pct"] == 100.0
    
    # Zero amount
    inv_zero = normalize_record({"amount": "$0.00", "currency": "USD", "date": "2026-07-09", "vendor_name": "Acme"}, fx_rates)
    po_zero = normalize_record({"po_number": "PO-ZERO", "amount": "$0.00", "currency": "USD", "date": "2026-07-01", "vendor_name": "Acme"}, fx_rates)
    score_zero, _, discrepancies_zero = score_match(inv_zero, po_zero, None)
    assert discrepancies_zero["amount_delta_pct"] == 0.0
    assert score_zero >= 80, f"Zero amount matching should be supported and score reasonably, got {score_zero}"
    
    # Unparseable Date - fallback to current date (ISO format)
    inv_bad_date = normalize_record({"amount": "$500.00", "currency": "USD", "date": "not-a-date-string", "vendor_name": "Acme"}, fx_rates)
    # Check that it returns an ISO date (10 chars, YYYY-MM-DD)
    assert len(inv_bad_date.date) == 10
    assert inv_bad_date.date[4] == "-" and inv_bad_date.date[7] == "-"

def test_summary_generator():
    # Test that summaries are non-empty for all status bands
    s1 = generate_summary("auto_approved", 98, {"amount_delta_pct": 0.0, "vendor_match_score": 100.0, "date_valid": True}, "PO-1")
    s2 = generate_summary("needs_human_review", 88, {"amount_delta_pct": 4.2, "vendor_match_score": 90.0, "date_valid": True}, "PO-2")
    s3 = generate_summary("escalated", 50, {"amount_delta_pct": 25.0, "vendor_match_score": 60.0, "date_valid": False}, "PO-3")
    
    assert isinstance(s1, str) and len(s1) > 0
    assert isinstance(s2, str) and len(s2) > 0
    assert isinstance(s3, str) and len(s3) > 0

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
from app.tools.router import route_decision
from app.orchestrator import process_invoice, generate_summary
from app.audit import log_decision, get_all_decisions, init_db, clear_decisions

# Setup paths relative to test file location
TEST_DIR = os.path.dirname(__file__)
BASE_DIR = os.path.abspath(os.path.join(TEST_DIR, ".."))
INVOICES_PATH = os.path.join(BASE_DIR, "data", "legacy_small", "erp_a_invoices.json")
POS_PATH = os.path.join(BASE_DIR, "data", "legacy_small", "erp_b_purchase_orders.json")
RECEIPTS_PATH = os.path.join(BASE_DIR, "data", "legacy_small", "erp_c_receipts.json")
FX_PATH = os.path.join(BASE_DIR, "data", "legacy_small", "fx_rates.json")
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

# --- Feature A & D: Auth & Review Override validation Tests ---

def test_auth_reviewer_creation(tmp_path):
    # Auth is removed, return stub
    pass

def test_auth_role_permissions(tmp_path):
    # Auth role checking is removed
    pass

def test_override_validation():
    from app.review import validate_override
    
    # 1. auto_approved items: only disputed is valid (gating removed)
    ok, msg = validate_override("auto_approved", "approved", "note note note")
    assert ok is False
    assert "only be disputed" in msg
    
    ok, msg = validate_override("auto_approved", "disputed", "too short")
    assert ok is False
    assert "min 10 characters" in msg
    
    ok, msg = validate_override("auto_approved", "disputed", "valid dispute note explaining why")
    assert ok is True

    # 2. needs_human_review/escalated: disputed is invalid; approved/rejected only
    ok, msg = validate_override("needs_human_review", "disputed", "valid dispute note explaining why")
    assert ok is False
    assert "Choose Approve or Reject" in msg
    
    ok, msg = validate_override("needs_human_review", "approved", "")
    assert ok is True
    
    ok, msg = validate_override("escalated", "rejected", "")
    assert ok is True

def test_override_logging_with_reviewer(tmp_path):
    from app.review import log_override, get_override
    db = str(tmp_path / "test_logging.db")
    
    log_override("INV-999", "admin", "needs_human_review", 85, "approved", "Approved by reviewer", db)
    
    override = get_override("INV-999", db)
    assert override is not None
    assert override["invoice_id"] == "INV-999"
    assert override["reviewer_name"] == "admin"
    assert override["human_decision"] == "approved"
    assert override["reviewer_note"] == "Approved by reviewer"

def test_reprocess_preserves_overrides(tmp_path):
    from app.audit import clear_decisions
    from app.review import log_override, get_all_overrides
    db = str(tmp_path / "test_preserve.db")
    
    # Log an override
    log_override("INV-123", "admin", "needs_human_review", 85, "approved", "Reprocess test", db)
    assert len(get_all_overrides(db)) == 1
    
    # Clear decisions (represents reprocessing)
    clear_decisions(db)
    
    # Assert overrides are preserved
    assert len(get_all_overrides(db)) == 1

def test_reprocess_preserves_fx_cache(tmp_path):
    from app.audit import clear_decisions
    db = str(tmp_path / "test_preserve_fx.db")
    
    # Log an FX rate
    conn = sqlite3.connect(db)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fx_rate_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            currency_pair TEXT NOT NULL,
            rate REAL NOT NULL,
            source TEXT NOT NULL,
            fetched_at TEXT NOT NULL
        )
    """)
    cursor.execute("INSERT INTO fx_rate_cache (currency_pair, rate, source, fetched_at) VALUES ('USD_INR', 83.5, 'live_api', '2026-07-09T12:00:00Z')")
    conn.commit()
    conn.close()
    
    # Clear decisions
    clear_decisions(db)
    
    # Verify cache is preserved
    conn = sqlite3.connect(db)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM fx_rate_cache")
    count = cursor.fetchone()[0]
    conn.close()
    assert count == 1

# --- Feature C: Live FX Tests ---

def test_fx_fallback_on_api_failure(tmp_path, monkeypatch):
    from app.tools.fx import get_fx_rate
    db = str(tmp_path / "test_fx_fallback.db")
    
    # Mock requests.get to throw connection exception to simulate offline/failure
    def mock_get(*args, **kwargs):
        raise requests.exceptions.ConnectionError("Offline")
        
    import requests
    monkeypatch.setattr(requests, "get", mock_get)
    
    # Request FX rate. Should fall back to static fx_rates.json (USD = 83.5)
    rate, source = get_fx_rate("USD", "INR", db)
    assert rate == 83.5
    assert source == "static_fallback"

def test_fx_cache_reuse_within_window(tmp_path, monkeypatch):
    from app.tools.fx import get_fx_rate
    db = str(tmp_path / "test_fx_cache.db")
    
    calls = 0
    # Mock API call to return a specific rate and count invocations
    def mock_get(url, *args, **kwargs):
        nonlocal calls
        calls += 1
        class MockResponse:
            status_code = 200
            def json(self):
                return {"result": "success", "rates": {"INR": 95.0}}
        return MockResponse()
        
    import requests
    monkeypatch.setattr(requests, "get", mock_get)
    
    # First fetch (should trigger API)
    rate1, source1 = get_fx_rate("USD", "INR", db)
    assert rate1 == 95.0
    assert source1 == "live_api"
    assert calls == 1
    
    # Second fetch within 6 hours (should hit DB cache and not increment calls)
    rate2, source2 = get_fx_rate("USD", "INR", db)
    assert rate2 == 95.0
    assert source2 == "live_api"
    assert calls == 1

# --- Feature B: Dataset Generation Tests ---

def test_dataset_generation_counts(tmp_path):
    from data.generate_dataset import generate_data
    temp_dir = str(tmp_path)
    generate_data(temp_dir)
    
    # Check generated files in temp dir
    with open(os.path.join(temp_dir, "data", "erp_a_invoices.json"), "r") as f:
        invoices = json.load(f)
    with open(os.path.join(temp_dir, "data", "erp_b_purchase_orders.json"), "r") as f:
        pos = json.load(f)
    with open(os.path.join(temp_dir, "data", "erp_c_receipts.json"), "r") as f:
        receipts = json.load(f)
    with open(os.path.join(temp_dir, "data", "fx_rates.json"), "r") as f:
        fx = json.load(f)
        
    assert len(invoices) == 75
    assert len(pos) == 75
    assert len(receipts) == 75
    assert len(fx) == 4
    assert "GBP" in fx

def test_dataset_edge_case_coverage():
    # Spot-check rapidfuzz path: "Sundar Textiles Pvt Ltd" vs "SUNDAR TEXTILES"
    from rapidfuzz import fuzz
    score = fuzz.WRatio("Sundar Textiles Pvt Ltd".lower(), "SUNDAR TEXTILES".lower())
    assert score >= 80.0


# --- Feature F: XGBoost Shadow Scorer Tests ---

def test_shadow_model_insufficient_data(tmp_path):
    from app.tools.ml_scorer import train_shadow_model, MODEL_PATH
    db = str(tmp_path / "test_ml_insufficient.db")
    
    # Delete model file if it exists in system path (or since MODEL_PATH is absolute, we mock it)
    # Train with 0 labels, should return insufficient_data
    res = train_shadow_model(db, min_labels=30)
    assert res["status"] == "insufficient_data"
    assert res["labels_available"] == 0

def test_shadow_predict_never_alters_status(tmp_path):
    from app.orchestrator import process_invoice
    db = str(tmp_path / "test_ml_shadow.db")
    
    # Seed data
    inv_raw = {
        "invoice_id": "INV-TEST-ML",
        "po_number": "PO-TEST-ML",
        "vendor_name": "Test Vendor",
        "amount": "$1,000.00",
        "currency": "USD",
        "invoice_date": "2026-07-09",
        "quantity": 10
    }
    pos_raw = [{
        "po_number": "PO-TEST-ML",
        "vendor_name": "Test Vendor",
        "amount": "$1,000.00",
        "currency": "USD",
        "po_date": "2026-07-01",
        "quantity": 10
    }]
    receipts_raw = [{
        "receipt_id": "REC-TEST-ML",
        "po_number": "PO-TEST-ML",
        "vendor_name": "Test Vendor",
        "amount": "$1,000.00",
        "currency": "USD",
        "receipt_date": "2026-07-05",
        "quantity": 10
    }]
    
    # Run pipeline. Result should be auto_approved with score 100
    res1 = process_invoice(inv_raw, pos_raw, receipts_raw, db_path=db)
    assert res1.status == "auto_approved"
    
    # Shadow ML scorer prediction row should be created in model_predictions table
    conn = sqlite3.connect(db)
    cursor = conn.cursor()
    cursor.execute("SELECT deterministic_score, model_version FROM model_predictions WHERE invoice_id = 'INV-TEST-ML'")
    pred_row = cursor.fetchone()
    conn.close()
    
    assert pred_row is not None
    assert pred_row[0] == 100
    assert pred_row[1] == "insufficient_data"  # since model doesn't exist


def test_confidence_optional_not_double_wrapped():
    # Bug 1 regression test
    # Verify that the receipt parameter in score_match signature is not double-wrapped Optional
    import inspect
    from app.tools.confidence import score_match
    sig = inspect.signature(score_match)
    receipt_param = sig.parameters.get("receipt")
    assert receipt_param is not None
    # Check annotation as string to see if Optional[Optional[...]] is gone
    annotation_str = str(receipt_param.annotation)
    assert "Optional[Optional[" not in annotation_str

def test_ml_scorer_no_monkeypatch_needed_or_documented():
    # Bug 2 regression test
    # Verify that the monkeypatch block has been removed from ml_scorer.py
    import numpy as np
    from app.tools import ml_scorer
    # Verify numpy is compatible and monkeypatch np.obj2sctype doesn't exist
    assert hasattr(np, "obj2sctype"), "numpy==1.26.4 should naturally have obj2sctype"
    # Read ml_scorer.py file to ensure monkeypatch assignment code is removed
    src_path = ml_scorer.__file__
    with open(src_path, "r") as f:
        content = f.read()
    assert "np.obj2sctype = lambda" not in content

def test_ui_result_has_structured_vendor_field():
    # Bug 3 regression test
    # Assert MatchResult has vendor_name field
    from app.schema import MatchResult
    fields = MatchResult.model_fields
    assert "vendor_name" in fields
    assert fields["vendor_name"].annotation == str

def test_db_connection_falls_back_to_sqlite_without_turso_env(tmp_path):
    # Test connection fallback
    from app.db_connection import get_connection
    # Ensure env vars are temporarily removed
    import os
    orig_url = os.environ.pop("LIBSQL_URL", None)
    orig_token = os.environ.pop("LIBSQL_AUTH_TOKEN", None)
    try:
        db = str(tmp_path / "test_fallback.db")
        conn = get_connection(db)
        assert isinstance(conn, sqlite3.Connection)
        conn.close()
    finally:
        if orig_url:
            os.environ["LIBSQL_URL"] = orig_url
        if orig_token:
            os.environ["LIBSQL_AUTH_TOKEN"] = orig_token

def test_decision_repository_upsert_and_get_all(tmp_path):
    from app.db import DecisionRepository
    from app.schema import MatchResult
    from app.db_migrations import run_migrations
    db = str(tmp_path / "test_repo.db")
    run_migrations(db)
    
    repo = DecisionRepository(db)
    res = MatchResult(
        invoice_id="INV-REPO-1",
        vendor_name="Acme Corp",
        invoice_date="2026-07-09",
        po_id="PO-1",
        receipt_id="REC-1",
        status="auto_approved",
        confidence_score=100,
        normalized_amount=1000.0,
        normalized_amount_inr=1000.0,
        discrepancies={"amount_delta_pct": 0.0},
        reasons=["All match"],
        timestamp="2026-07-09T12:00:00Z",
        summary="Approved"
    )
    repo.upsert(res)
    
    results = repo.get_all()
    assert len(results) == 1
    assert results[0].invoice_id == "INV-REPO-1"
    assert results[0].vendor_name == "Acme Corp"

def test_decision_repository_archive_preserves_rows(tmp_path):
    from app.db import DecisionRepository
    from app.schema import MatchResult
    from app.db_migrations import run_migrations
    db = str(tmp_path / "test_archive.db")
    run_migrations(db)
    
    repo = DecisionRepository(db)
    res = MatchResult(
        invoice_id="INV-REPO-2",
        vendor_name="Global Corp",
        invoice_date="2026-07-09",
        status="escalated",
        confidence_score=50,
        normalized_amount=1000.0,
        normalized_amount_inr=1000.0,
        discrepancies={},
        reasons=[],
        timestamp="2026-07-09T12:00:00Z",
        summary="Escalated"
    )
    repo.upsert(res)
    
    # Archive
    repo.archive_all()
    
    # Non-archived should be empty
    assert len(repo.get_all(include_archived=False)) == 0
    # Archived should still contain it
    all_rows = repo.get_all(include_archived=True)
    assert len(all_rows) == 1
    assert all_rows[0].invoice_id == "INV-REPO-2"

def test_override_repository_log_and_get_latest(tmp_path):
    from app.db import OverrideRepository
    from app.schema import ReviewOverride
    from app.db_migrations import run_migrations
    db = str(tmp_path / "test_override.db")
    run_migrations(db)
    
    repo = OverrideRepository(db)
    o = ReviewOverride(
        invoice_id="INV-REPO-1",
        reviewer="admin",
        machine_status="needs_human_review",
        machine_score=85,
        human_decision="approved",
        reviewer_note="Looks valid",
        timestamp="2026-07-09T12:00:00Z"
    )
    repo.log(o)
    
    latest = repo.get_latest("INV-REPO-1")
    assert latest is not None
    assert latest.human_decision == "approved"
    assert latest.reviewer == "admin"
    
    all_overrides = repo.get_all()
    assert len(all_overrides) == 1

def test_fx_cache_repository_respects_max_age(tmp_path):
    from app.db import FxCacheRepository
    from app.db_migrations import run_migrations
    db = str(tmp_path / "test_fx.db")
    run_migrations(db)
    
    repo = FxCacheRepository(db)
    repo.store_rate("USD_INR", 83.5, "live_api")
    
    # Check active
    rate = repo.get_cached_rate("USD_INR", max_age_hours=6)
    assert rate == 83.5
    
    # Check expired (using 0 age limit)
    expired_rate = repo.get_cached_rate("USD_INR", max_age_hours=0)
    assert expired_rate is None

def test_override_actions_available_without_role_check():
    # Verify that validate_override behaves same without any role parameters
    from app.review import validate_override
    # auto_approved only valid decision is "disputed" (requires min 10 chars note)
    ok, _ = validate_override("auto_approved", "disputed", "Note that has at least ten chars")
    assert ok is True
    
    # needs_human_review / escalated cannot be disputed, only approved/rejected
    ok2, _ = validate_override("needs_human_review", "approved", "")
    assert ok2 is True

def test_analytics_data_matches_decision_counts(tmp_path):
    from app.db import DecisionRepository
    from app.schema import MatchResult
    from app.db_migrations import run_migrations
    db = str(tmp_path / "test_analytics.db")
    run_migrations(db)
    
    repo = DecisionRepository(db)
    res1 = MatchResult(
        invoice_id="INV-AN-1", vendor_name="A", invoice_date="2026-07-09",
        status="auto_approved", confidence_score=98, normalized_amount=100.0,
        normalized_amount_inr=100.0, discrepancies={}, reasons=[],
        timestamp="2026-07-09T12:00:00Z", summary=""
    )
    res2 = MatchResult(
        invoice_id="INV-AN-2", vendor_name="B", invoice_date="2026-07-09",
        status="needs_human_review", confidence_score=85, normalized_amount=100.0,
        normalized_amount_inr=100.0, discrepancies={}, reasons=[],
        timestamp="2026-07-09T12:00:00Z", summary=""
    )
    repo.upsert(res1)
    repo.upsert(res2)
    
    results = repo.get_all(include_archived=False)
    assert len(results) == 2
    approved_count = sum(1 for r in results if r.status == "auto_approved")
    assert approved_count == 1


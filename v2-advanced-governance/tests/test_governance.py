import sys
import os

# Add project root to Python search path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import sqlite3
import pytest
from app.db import DecisionRepository, UserRepository, OverrideRepository
from app.db_migrations import run_migrations
from app.schema import MatchResult, User
from app.review import log_override, get_override
from app.tools.explain import generate_local_explanation, generate_decision_explanation

@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_governance.db"
    run_migrations(str(db_file))
    return str(db_file)

def test_db_migration_columns_and_users(temp_db):
    # Connect and verify tables and schema columns
    conn = sqlite3.connect(temp_db)
    cursor = conn.cursor()
    
    # Check decisions table structure
    cursor.execute("PRAGMA table_info(decisions)")
    cols = [col[1] for col in cursor.fetchall()]
    assert "explanation_text" in cols
    
    # Check users table structure
    cursor.execute("PRAGMA table_info(users)")
    user_cols = [col[1] for col in cursor.fetchall()]
    assert "username" in user_cols
    assert "password_hash" in user_cols
    assert "role" in user_cols
    
    # Check default seeded users count (viewer removed, so admin + reviewer = 2)
    cursor.execute("SELECT COUNT(*) FROM users")
    count = cursor.fetchone()[0]
    assert count == 2
    conn.close()

def test_user_repository(temp_db):
    repo = UserRepository(temp_db)
    
    # Test retrieving admin
    admin_user = repo.get_user("admin")
    assert admin_user is not None
    assert admin_user["role"] == "admin"
    assert admin_user["name"] == "System Administrator"
    
    # Test retrieving reviewer
    reviewer_user = repo.get_user("reviewer")
    assert reviewer_user is not None
    assert reviewer_user["role"] == "reviewer"
    
    # Test retrieving non-existent user
    non_existent = repo.get_user("invalid_username")
    assert non_existent is None
    
    # Test retrieve all users
    all_users = repo.get_all_users()
    assert len(all_users) == 2
    usernames = {u["username"] for u in all_users}
    assert usernames == {"admin", "reviewer"}

def test_explanation_text_saving_and_lazy_update(temp_db):
    dec_repo = DecisionRepository(temp_db)
    
    result = MatchResult(
        invoice_id="INV-TEST-001",
        vendor_name="Test Vendor",
        invoice_date="2026-07-01",
        po_id="PO-TEST-001",
        receipt_id="REC-TEST-001",
        status="needs_human_review",
        confidence_score=85,
        normalized_amount=5000.0,
        normalized_amount_inr=5000.0,
        discrepancies={"amount_delta_pct": 2.5, "vendor_match_score": 100.0, "date_valid": True},
        reasons=["Amount differs by 2.5%", "Vendor matches exactly"],
        timestamp="2026-07-12T12:00:00Z",
        summary="Flagged for manual review",
        explanation_text="Initial explanation"
    )
    
    # Upsert with initial explanation
    dec_repo.upsert(result)
    
    saved = dec_repo.get_all(include_archived=False)
    assert len(saved) == 1
    assert saved[0].invoice_id == "INV-TEST-001"
    assert saved[0].explanation_text == "Initial explanation"
    
    # Update explanation lazily
    dec_repo.update_explanation("INV-TEST-001", "Updated explanation text via lazy load")
    
    saved_updated = dec_repo.get_all(include_archived=False)
    assert saved_updated[0].explanation_text == "Updated explanation text via lazy load"

def test_explainability_fallback(temp_db):
    result = MatchResult(
        invoice_id="INV-TEST-002",
        vendor_name="Acme Corp",
        invoice_date="2026-07-01",
        po_id="PO-TEST-002",
        receipt_id="REC-TEST-002",
        status="needs_human_review",
        confidence_score=84,
        normalized_amount=12000.0,
        normalized_amount_inr=12000.0,
        discrepancies={"amount_delta_pct": 3.0, "vendor_match_score": 100.0, "date_valid": True},
        reasons=["Amount differs by 3.0%", "Vendor similarity is 100%"],
        timestamp="2026-07-12T12:00:00Z",
        summary="Needs review",
        explanation_text=None
    )
    
    # Generate local explanation fallback
    local_exp = generate_local_explanation(result)
    assert "VERDICT BREAKDOWN" in local_exp.upper()
    assert "Needs Human Review".upper() in local_exp.upper()
    assert "84/100" in local_exp
    assert "12,000.00 INR" in local_exp or "12000" in local_exp
    
    # Verify generator falls back to local breakdown when request fails
    from unittest.mock import patch
    import requests
    with patch("requests.post", side_effect=requests.RequestException("API error")):
        gen_exp = generate_decision_explanation(result)
        assert gen_exp == local_exp

def test_log_override_with_custom_username(temp_db):
    # Log override as 'custom_user_reviewer' instead of default 'admin'
    log_override(
        invoice_id="INV-OVERRIDE-001",
        reviewer="custom_user_reviewer",
        machine_status="needs_human_review",
        machine_score=85,
        human_decision="approved",
        reviewer_note="Looks perfect under manual inspection",
        db_path=temp_db
    )
    
    # Retrieve latest override
    override = get_override("INV-OVERRIDE-001", temp_db)
    assert override is not None
    assert override["reviewer_name"] == "custom_user_reviewer"
    assert override["human_decision"] == "approved"
    assert override["reviewer_note"] == "Looks perfect under manual inspection"

def test_audit_logs_repository(temp_db):
    from app.db import AuditLogRepository
    repo = AuditLogRepository(temp_db)
    
    # Log some events
    repo.log_event("admin", "LOGIN", "System administrator logged in.")
    repo.log_event("reviewer", "OVERRIDE", "Approved invoice INV-123.")
    
    logs = repo.get_logs()
    assert len(logs) == 2
    assert logs[0]["username"] == "reviewer"
    assert logs[0]["action"] == "OVERRIDE"
    assert logs[0]["details"] == "Approved invoice INV-123."
    assert logs[1]["username"] == "admin"
    assert logs[1]["action"] == "LOGIN"

def test_config_repository(temp_db):
    from app.db import ConfigRepository
    repo = ConfigRepository(temp_db)
    
    # Get seeded values
    app_t = repo.get_value("approved_threshold", 95.0)
    rev_t = repo.get_value("review_threshold", 80.0)
    assert app_t == 95.0
    assert rev_t == 80.0
    
    # Update values
    repo.set_value("approved_threshold", 90.0)
    repo.set_value("review_threshold", 75.0)
    
    # Retrieve updated values
    assert repo.get_value("approved_threshold", 95.0) == 90.0
    assert repo.get_value("review_threshold", 80.0) == 75.0

def test_user_repository_creation_and_deactivation(temp_db):
    repo = UserRepository(temp_db)
    
    # Create user
    success = repo.create_user("new_user", "pw_hash", "New User Display", "new@reconciliation.local", "reviewer")
    assert success is True
    
    # Retrieve user
    user = repo.get_user("new_user")
    assert user is not None
    assert user["name"] == "New User Display"
    assert user["role"] == "reviewer"
    
    # Deactivate user
    repo.deactivate_user("new_user")
    assert repo.get_user("new_user") is None

def test_decision_repository_update_status(temp_db):
    from app.db import DecisionRepository
    dec_repo = DecisionRepository(temp_db)
    result = MatchResult(
        invoice_id="INV-STATUS-001",
        vendor_name="Status Vendor",
        invoice_date="2026-07-01",
        po_id="PO-STATUS-001",
        receipt_id="REC-STATUS-001",
        status="needs_human_review",
        confidence_score=85,
        normalized_amount=1000.0,
        normalized_amount_inr=1000.0,
        discrepancies={},
        reasons=[],
        timestamp="2026-07-12T12:00:00Z",
        summary="Awaiting status change",
        explanation_text=None
    )
    dec_repo.upsert(result)
    
    # Verify initial status
    saved = dec_repo.get_all(include_archived=False)
    assert len(saved) == 1
    assert saved[0].invoice_id == "INV-STATUS-001"
    assert saved[0].status == "needs_human_review"
    
    # Update status
    dec_repo.update_status("INV-STATUS-001", "approved")
    
    # Verify updated status
    saved_updated = dec_repo.get_all(include_archived=False)
    assert saved_updated[0].status == "approved"

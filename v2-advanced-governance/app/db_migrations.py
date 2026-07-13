import os
import bcrypt
from app.db_connection import get_connection

def run_migrations(db_path: str) -> None:
    """
    Consolidated database migrations. Creates all database tables if they do not exist.
    """
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = get_connection(db_path)
    cursor = conn.cursor()
    
    # 1. Decisions Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS decisions (
            invoice_id TEXT PRIMARY KEY,
            vendor_name TEXT NOT NULL DEFAULT '',
            invoice_date TEXT NOT NULL DEFAULT '',
            po_id TEXT,
            receipt_id TEXT,
            status TEXT NOT NULL,
            confidence_score INTEGER NOT NULL,
            normalized_amount REAL NOT NULL DEFAULT 0.0,
            normalized_amount_inr REAL NOT NULL DEFAULT 0.0,
            discrepancies_json TEXT NOT NULL DEFAULT '{}',
            reasons_json TEXT NOT NULL DEFAULT '[]',
            timestamp TEXT NOT NULL,
            summary TEXT,
            explanation_text TEXT,
            archived INTEGER NOT NULL DEFAULT 0
        )
    """)
    
    # Verify and add columns if they don't exist
    cursor.execute("PRAGMA table_info(decisions)")
    columns = [col[1] for col in cursor.fetchall()]
    if "vendor_name" not in columns:
        cursor.execute("ALTER TABLE decisions ADD COLUMN vendor_name TEXT NOT NULL DEFAULT ''")
    if "invoice_date" not in columns:
        cursor.execute("ALTER TABLE decisions ADD COLUMN invoice_date TEXT NOT NULL DEFAULT ''")
    if "po_id" not in columns:
        cursor.execute("ALTER TABLE decisions ADD COLUMN po_id TEXT")
    if "receipt_id" not in columns:
        cursor.execute("ALTER TABLE decisions ADD COLUMN receipt_id TEXT")
    if "normalized_amount" not in columns:
        cursor.execute("ALTER TABLE decisions ADD COLUMN normalized_amount REAL NOT NULL DEFAULT 0.0")
    if "normalized_amount_inr" not in columns:
        cursor.execute("ALTER TABLE decisions ADD COLUMN normalized_amount_inr REAL NOT NULL DEFAULT 0.0")
    if "discrepancies_json" not in columns:
        cursor.execute("ALTER TABLE decisions ADD COLUMN discrepancies_json TEXT NOT NULL DEFAULT '{}'")
    if "summary" not in columns:
        cursor.execute("ALTER TABLE decisions ADD COLUMN summary TEXT")
    if "explanation_text" not in columns:
        cursor.execute("ALTER TABLE decisions ADD COLUMN explanation_text TEXT")
    if "archived" not in columns:
        cursor.execute("ALTER TABLE decisions ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")
 
    # 2. Review Overrides Table (no foreign keys to reviewers)
    cursor.execute("PRAGMA table_info(review_overrides)")
    override_cols = [col[1] for col in cursor.fetchall()]
    if override_cols:
        # If the old schema table exists, drop it to migrate cleanly
        if "reviewer_id" in override_cols or "reviewer" not in override_cols:
            cursor.execute("DROP TABLE IF EXISTS review_overrides")
            
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS review_overrides (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id TEXT NOT NULL,
            reviewer TEXT NOT NULL DEFAULT 'admin',
            machine_status TEXT NOT NULL,
            machine_score INTEGER NOT NULL,
            human_decision TEXT NOT NULL,
            reviewer_note TEXT NOT NULL DEFAULT '',
            timestamp TEXT NOT NULL
        )
    """)
    
    # Drop reviewers table as it is not needed anymore
    cursor.execute("DROP TABLE IF EXISTS reviewers")

    # 3. FX Rate Cache Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fx_rate_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            currency_pair TEXT NOT NULL,
            rate REAL NOT NULL,
            source TEXT NOT NULL,
            fetched_at TEXT NOT NULL
        )
    """)

    # 4. Model Predictions Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS model_predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id TEXT NOT NULL,
            deterministic_score INTEGER NOT NULL,
            model_score REAL,
            model_version TEXT,
            shap_top_features TEXT,
            predicted_at TEXT NOT NULL
        )
    """)
    
    # 5. Users Table for Authentication & RBAC
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'reviewer'
        )
    """)
    
    # Seed default user roles if empty
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        default_users = [
            ("admin", "admin123", "System Administrator", "admin@reconciliation.local", "admin"),
            ("reviewer", "reviewer123", "Finance Reviewer", "reviewer@reconciliation.local", "reviewer")
        ]
        for u_name, plain_pwd, name, email, role in default_users:
            hashed_pw = bcrypt.hashpw(plain_pwd.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            cursor.execute(
                "INSERT INTO users (username, password_hash, name, email, role) VALUES (?, ?, ?, ?, ?)",
                (u_name, hashed_pw, name, email, role)
            )
            
    # 6. Audit Logs Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            username TEXT NOT NULL,
            action TEXT NOT NULL,
            details TEXT NOT NULL
        )
    """)

    # 7. System Config Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS system_config (
            key TEXT PRIMARY KEY,
            value REAL NOT NULL
        )
    """)

    # Seed default thresholds
    cursor.execute("SELECT COUNT(*) FROM system_config")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO system_config (key, value) VALUES ('approved_threshold', 95.0)")
        cursor.execute("INSERT INTO system_config (key, value) VALUES ('review_threshold', 80.0)")
            
    conn.commit()
    conn.close()

import os
import sqlite3
import json
from app.schema import MatchResult

DEFAULT_DB_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "data", "decisions.db")
)

def init_db(db_path: str = DEFAULT_DB_PATH):
    """
    Initializes the SQLite database and creates the decisions table if it doesn't exist.
    """
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS decisions (
            invoice_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            confidence_score INTEGER NOT NULL,
            reasons_json TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

def log_decision(match_result: MatchResult, db_path: str = DEFAULT_DB_PATH):
    """
    Logs a decision to the SQLite decisions table.
    """
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO decisions (invoice_id, status, confidence_score, reasons_json, timestamp)
        VALUES (?, ?, ?, ?, ?)
    """, (
        match_result.invoice_id,
        match_result.status,
        match_result.confidence_score,
        json.dumps(match_result.reasons),
        match_result.timestamp
    ))
    conn.commit()
    conn.close()

def get_all_decisions(db_path: str = DEFAULT_DB_PATH) -> list:
    """
    Retrieves all logged decisions from the database.
    """
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT invoice_id, status, confidence_score, reasons_json, timestamp FROM decisions")
    rows = cursor.fetchall()
    conn.close()
    
    decisions = []
    for row in rows:
        decisions.append({
            "invoice_id": row[0],
            "status": row[1],
            "confidence_score": row[2],
            "reasons": json.loads(row[3]),
            "timestamp": row[4]
        })
    return decisions

def clear_decisions(db_path: str = DEFAULT_DB_PATH):
    """
    Clears all logged decisions from the database.
    """
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM decisions")
    conn.commit()
    conn.close()

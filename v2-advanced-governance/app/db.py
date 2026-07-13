import json
import datetime
from typing import List, Optional, Dict, Any
from app.db_connection import get_connection
from app.schema import MatchResult, ReviewOverride

class DecisionRepository:
    def __init__(self, db_path: str = None):
        self.db_path = db_path

    def upsert(self, result: MatchResult) -> None:
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO decisions (
                invoice_id, vendor_name, invoice_date, po_id, receipt_id, status, confidence_score, 
                normalized_amount, normalized_amount_inr, discrepancies_json, reasons_json, 
                timestamp, summary, explanation_text, archived
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        """, (
            result.invoice_id,
            result.vendor_name,
            result.invoice_date,
            result.po_id,
            result.receipt_id,
            result.status,
            result.confidence_score,
            result.normalized_amount,
            result.normalized_amount_inr,
            json.dumps(result.discrepancies),
            json.dumps(result.reasons),
            result.timestamp,
            result.summary,
            result.explanation_text
        ))
        conn.commit()
        conn.close()

    def get_all(self, include_archived: bool = False) -> List[MatchResult]:
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        query = """
            SELECT invoice_id, vendor_name, invoice_date, po_id, receipt_id, status, confidence_score, 
                   normalized_amount, normalized_amount_inr, discrepancies_json, reasons_json, 
                   timestamp, summary, explanation_text, archived 
            FROM decisions
        """
        if not include_archived:
            query += " WHERE archived = 0"
            
        cursor.execute(query)
        rows = cursor.fetchall()
        conn.close()
        
        results = []
        for row in rows:
            try:
                results.append(MatchResult(
                    invoice_id=row[0],
                    vendor_name=row[1] if row[1] is not None else "",
                    invoice_date=row[2] if row[2] is not None else "",
                    po_id=row[3],
                    receipt_id=row[4],
                    status=row[5],
                    confidence_score=row[6],
                    normalized_amount=row[7] if row[7] is not None else 0.0,
                    normalized_amount_inr=row[8] if row[8] is not None else 0.0,
                    discrepancies=json.loads(row[9]) if row[9] else {},
                    reasons=json.loads(row[10]) if row[10] else [],
                    timestamp=row[11],
                    summary=row[12],
                    explanation_text=row[13]
                ))
            except Exception:
                continue
        return results

    def update_explanation(self, invoice_id: str, explanation_text: str) -> None:
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE decisions
            SET explanation_text = ?
            WHERE invoice_id = ?
        """, (explanation_text, invoice_id))
        conn.commit()
        conn.close()

    def update_status(self, invoice_id: str, status: str) -> None:
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE decisions
            SET status = ?
            WHERE invoice_id = ?
        """, (status, invoice_id))
        conn.commit()
        conn.close()

    def archive_all(self) -> None:
        """
        Soft-delete by setting archived = 1 on all current active decisions.
        """
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("UPDATE decisions SET archived = 1")
        conn.commit()
        conn.close()

class UserRepository:
    def __init__(self, db_path: str = None):
        self.db_path = db_path

    def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT username, password_hash, name, email, role
            FROM users
            WHERE username = ?
        """, (username,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        return {
            "username": row[0],
            "password": row[1],
            "name": row[2],
            "email": row[3],
            "role": row[4]
        }

    def get_all_users(self) -> List[Dict[str, Any]]:
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT username, password_hash, name, email, role
            FROM users
        """)
        rows = cursor.fetchall()
        conn.close()
        
        users = []
        for r in rows:
            users.append({
                "username": r[0],
                "password": r[1],
                "name": r[2],
                "email": r[3],
                "role": r[4]
            })
        return users

    def create_user(self, username: str, password_hash: str, name: str, email: str, role: str) -> bool:
        try:
            conn = get_connection(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO users (username, password_hash, name, email, role)
                VALUES (?, ?, ?, ?, ?)
            """, (username.strip(), password_hash, name.strip(), email.strip(), role.strip()))
            conn.commit()
            conn.close()
            return True
        except Exception:
            return False

    def deactivate_user(self, username: str) -> None:
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE username = ?", (username,))
        conn.commit()
        conn.close()

class OverrideRepository:
    def __init__(self, db_path: str = None):
        self.db_path = db_path

    def log(self, override: ReviewOverride) -> None:
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO review_overrides (
                invoice_id, reviewer, machine_status, machine_score, 
                human_decision, reviewer_note, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            override.invoice_id,
            override.reviewer,
            override.machine_status,
            override.machine_score,
            override.human_decision,
            override.reviewer_note,
            override.timestamp
        ))
        conn.commit()
        conn.close()

    def get_latest(self, invoice_id: str) -> Optional[ReviewOverride]:
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, invoice_id, reviewer, machine_status, machine_score, 
                   human_decision, reviewer_note, timestamp 
            FROM review_overrides 
            WHERE invoice_id = ? 
            ORDER BY id DESC LIMIT 1
        """, (invoice_id,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
            
        return ReviewOverride(
            id=row[0],
            invoice_id=row[1],
            reviewer=row[2],
            machine_status=row[3],
            machine_score=row[4],
            human_decision=row[5],
            reviewer_note=row[6],
            timestamp=row[7]
        )

    def get_all(self) -> List[ReviewOverride]:
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, invoice_id, reviewer, machine_status, machine_score, 
                   human_decision, reviewer_note, timestamp 
            FROM review_overrides
            ORDER BY id DESC
        """)
        rows = cursor.fetchall()
        conn.close()
        
        overrides = []
        for r in rows:
            overrides.append(ReviewOverride(
                id=r[0],
                invoice_id=r[1],
                reviewer=r[2],
                machine_status=r[3],
                machine_score=r[4],
                human_decision=r[5],
                reviewer_note=r[6],
                timestamp=r[7]
            ))
        return overrides

class FxCacheRepository:
    def __init__(self, db_path: str = None):
        self.db_path = db_path

    def get_cached_rate(self, currency_pair: str, max_age_hours: int = 6) -> Optional[float]:
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT rate, fetched_at 
            FROM fx_rate_cache 
            WHERE currency_pair = ? 
            ORDER BY id DESC LIMIT 1
        """, (currency_pair,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
            
        rate, fetched_at_str = row
        try:
            fetched_at = datetime.datetime.fromisoformat(fetched_at_str)
            # Remove tzinfo if present to compare offset-naive
            if fetched_at.tzinfo is not None:
                fetched_at = fetched_at.replace(tzinfo=None)
            now = datetime.datetime.utcnow()
            if now - fetched_at < datetime.timedelta(hours=max_age_hours):
                return float(rate)
        except Exception:
            pass
        return None

    def store_rate(self, currency_pair: str, rate: float, source: str) -> None:
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        now_str = datetime.datetime.utcnow().isoformat()
        cursor.execute("""
            INSERT INTO fx_rate_cache (currency_pair, rate, source, fetched_at)
            VALUES (?, ?, ?, ?)
        """, (currency_pair, rate, source, now_str))
        conn.commit()
        conn.close()

class ModelPredictionRepository:
    def __init__(self, db_path: str = None):
        self.db_path = db_path

    def log_prediction(self, invoice_id: str, deterministic_score: int,
                       model_score: Optional[float], model_version: str,
                       shap_top_features: Optional[str]) -> None:
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        now_str = datetime.datetime.utcnow().isoformat()
        cursor.execute("""
            INSERT INTO model_predictions (
                invoice_id, deterministic_score, model_score, model_version, 
                shap_top_features, predicted_at
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (invoice_id, deterministic_score, model_score, model_version, shap_top_features, now_str))
        conn.commit()
        conn.close()

    def get_all(self) -> List[dict]:
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT invoice_id, deterministic_score, model_score, model_version, 
                   shap_top_features, predicted_at 
            FROM model_predictions
            ORDER BY id DESC
        """)
        rows = cursor.fetchall()
        conn.close()
        
        predictions = []
        for r in rows:
            predictions.append({
                "invoice_id": r[0],
                "deterministic_score": r[1],
                "model_score": r[2],
                "model_version": r[3],
                "shap_top_features": json.loads(r[4]) if r[4] else None,
                "predicted_at": r[5]
            })
        return predictions

class AuditLogRepository:
    def __init__(self, db_path: str = None):
        self.db_path = db_path

    def log_event(self, username: str, action: str, details: str) -> None:
        import datetime
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()
        cursor.execute("""
            INSERT INTO audit_logs (timestamp, username, action, details)
            VALUES (?, ?, ?, ?)
        """, (now_str, username, action, details))
        conn.commit()
        conn.close()

    def get_logs(self) -> List[dict]:
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, timestamp, username, action, details
            FROM audit_logs
            ORDER BY id DESC
        """)
        rows = cursor.fetchall()
        conn.close()
        
        logs = []
        for r in rows:
            logs.append({
                "id": r[0],
                "timestamp": r[1],
                "username": r[2],
                "action": r[3],
                "details": r[4]
            })
        return logs

class ConfigRepository:
    def __init__(self, db_path: str = None):
        self.db_path = db_path

    def get_value(self, key: str, default: float) -> float:
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT value FROM system_config WHERE key = ?", (key,))
            row = cursor.fetchone()
            conn.close()
            if row is not None:
                return float(row[0])
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
        return default

    def set_value(self, key: str, value: float) -> None:
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO system_config (key, value)
            VALUES (?, ?)
        """, (key, value))
        conn.commit()
        conn.close()

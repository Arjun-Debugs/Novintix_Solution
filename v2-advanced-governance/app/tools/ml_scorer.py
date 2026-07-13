import os
# Configure OpenMP thread limit to prevent binary thread initialization crashes in containerized servers
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

import json
import sqlite3
import re
import numpy as np

from datetime import datetime
from typing import Dict, Any, List, Optional

SHAP_AVAILABLE = False
try:
    if not np.__version__.startswith("2."):
        import shap
        SHAP_AVAILABLE = True
except (ImportError, AttributeError, Exception, BaseException):
    pass
from app.audit import DEFAULT_DB_PATH, init_db
from app.db import ModelPredictionRepository
from app.db_connection import get_connection

MODEL_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "models")
)
MODEL_PATH = os.path.join(MODEL_DIR, "xgb_scorer.joblib")

FEATURE_NAMES = ["amount_delta", "vendor_similarity", "date_plausibility", "quantity_match"]

def parse_features_from_reasons(reasons: List[str]) -> List[float]:
    """
    Parses numeric model features from deterministic audit reasons.
    Features: [amount_delta, vendor_similarity, date_plausibility, quantity_match]
    """
    amount_delta = 100.0
    vendor_similarity = 0.0
    date_plausibility = 0.0
    quantity_match = 1.0  # default to match (1.0)
    
    for r in reasons:
        if "Amount matches exactly" in r:
            amount_delta = 0.0
        elif "Amount differs by" in r:
            m = re.search(r"Amount differs by ([\d\.]+)\%", r)
            if m:
                amount_delta = float(m.group(1))
                
        if "Vendor similarity is" in r:
            m = re.search(r"Vendor similarity is ([\d\.]+)\%", r)
            if m:
                vendor_similarity = float(m.group(1))
                
        if "Date plausibility verified" in r:
            date_plausibility = 1.0
            
        if "Quantity mismatch" in r:
            quantity_match = 0.0
            
    return [amount_delta, vendor_similarity, date_plausibility, quantity_match]

def train_shadow_model(db_path: str = DEFAULT_DB_PATH, min_labels: int = 30) -> Dict[str, Any]:
    """
    Pulls review overrides and matching decisions to train the XGBoost shadow classifier.
    Saves the trained model to app/models/xgb_scorer.joblib.
    """
    init_db(db_path)
    
    # Fetch overrides joined with decisions
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT o.invoice_id, o.human_decision, d.reasons_json
        FROM review_overrides o
        JOIN decisions d ON o.invoice_id = d.invoice_id
    """)
    rows = cursor.fetchall()
    conn.close()
    
    n_samples = len(rows)
    if n_samples < min_labels:
        return {
            "status": "insufficient_data",
            "labels_available": n_samples,
            "labels_needed": min_labels
        }
        
    # Prepare training data
    X_list = []
    y_list = []
    
    for row in rows:
        invoice_id, human_decision, reasons_json = row
        try:
            reasons = json.loads(reasons_json)
        except Exception:
            continue
            
        features = parse_features_from_reasons(reasons)
        X_list.append(features)
        
        # Label = 1 if human_decision is approved, else 0 (rejected/disputed)
        label = 1 if human_decision.strip().lower() == "approved" else 0
        y_list.append(label)
        
    X = np.array(X_list, dtype=np.float32)
    y = np.array(y_list, dtype=np.int32)
    
    # Train XGBoost classifier
    import xgboost as xgb
    import joblib

    model = xgb.XGBClassifier(
        n_estimators=50,
        max_depth=3,
        learning_rate=0.1,
        random_state=42,
        eval_metric="logloss"
    )
    model.fit(X, y)
    
    # Save model file
    os.makedirs(MODEL_DIR, exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    return {
        "status": "trained",
        "model_version": f"xgb_v{timestamp}",
        "n_samples": n_samples
    }

def shadow_predict(
    invoice_id: str,
    reasons: List[str],
    deterministic_score: int,
    db_path: str = DEFAULT_DB_PATH
) -> None:
    """
    Generates a shadow ML prediction for the invoice and logs it.
    Does not affect the pipeline status or routing logic.
    """
    init_db(db_path)
    features = parse_features_from_reasons(reasons)
    
    model_score = None
    model_version = "insufficient_data"
    shap_top_features = None
    
    if os.path.exists(MODEL_PATH):
        try:
            import xgboost as xgb
            import joblib
            # 1. Load model and predict probability
            model = joblib.load(MODEL_PATH)
            X = np.array([features], dtype=np.float32)
            # Predict probability of class 1 (approved)
            pred_prob = model.predict_proba(X)[0][1]
            model_score = float(round(pred_prob * 100, 1))
            model_version = f"xgb_v{int(os.path.getmtime(MODEL_PATH))}"
            
            # 2. Compute SHAP feature importances for this prediction
            if SHAP_AVAILABLE:
                explainer = shap.TreeExplainer(model)
                shap_values = explainer.shap_values(X)[0]
                
                # Pair feature names with their local shap values
                feature_shaps = []
                for name, val in zip(FEATURE_NAMES, shap_values):
                    feature_shaps.append({
                        "feature": name,
                        "shap_value": float(round(val, 4))
                    })
                    
                # Sort by absolute SHAP value descending
                feature_shaps.sort(key=lambda item: abs(item["shap_value"]), reverse=True)
                shap_top_features = json.dumps(feature_shaps[:3])
        except Exception:
            pass
            
    # 3. Log the prediction using ModelPredictionRepository
    repo = ModelPredictionRepository(db_path)
    repo.log_prediction(invoice_id, deterministic_score, model_score, model_version, shap_top_features)

def get_predictions_history(db_path: str = DEFAULT_DB_PATH) -> List[Dict[str, Any]]:
    """
    Helper to fetch prediction logs for display in the UI.
    """
    init_db(db_path)
    repo = ModelPredictionRepository(db_path)
    return repo.get_all()

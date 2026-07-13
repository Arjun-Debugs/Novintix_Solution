from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

class Invoice(BaseModel):
    invoice_id: str
    po_number: Optional[str] = None
    vendor_name: str
    amount: str
    currency: str
    invoice_date: str
    quantity: Optional[float] = None

class PurchaseOrder(BaseModel):
    po_number: str
    vendor_name: str
    amount: str
    currency: str
    po_date: str
    quantity: Optional[float] = None

class Receipt(BaseModel):
    receipt_id: str
    po_number: str
    vendor_name: str
    amount: str
    currency: str
    receipt_date: str
    quantity: Optional[float] = None

class NormalizedRecord(BaseModel):
    record_id: Optional[str] = None  # Holds invoice_id, po_number, or receipt_id
    po_number: Optional[str] = None
    vendor_name: str
    amount_inr: float
    date: str  # YYYY-MM-DD format
    quantity: Optional[float] = None
    raw_amount: Optional[str] = None
    raw_currency: Optional[str] = None
    raw_date: Optional[str] = None
    rate_source: Optional[str] = None

class MatchResult(BaseModel):
    invoice_id: str
    vendor_name: str = ""
    invoice_date: str = ""
    po_id: Optional[str] = None
    receipt_id: Optional[str] = None
    status: str  # auto_approved | needs_human_review | escalated
    confidence_score: int  # 0 to 100
    normalized_amount: float  # For task description compliance
    normalized_amount_inr: float  # For contract output compliance
    discrepancies: Dict[str, Any] = Field(default_factory=dict)
    reasons: List[str] = Field(default_factory=list)
    timestamp: str
    summary: Optional[str] = None  # Plain English one-line summary (from final task)
    explanation_text: Optional[str] = None

class User(BaseModel):
    username: str
    password_hash: str
    name: str
    email: str
    role: str = "viewer"

class Reviewer(BaseModel):
    id: Optional[int] = None
    display_name: str
    role: str = "reviewer"

class FxRateCache(BaseModel):
    id: Optional[int] = None
    currency_pair: str
    rate: float
    source: str
    fetched_at: str

class ReviewOverride(BaseModel):
    id: Optional[int] = None
    invoice_id: str
    reviewer: str = "admin"
    machine_status: str
    machine_score: int
    human_decision: str  # approved | rejected | disputed
    reviewer_note: str = ""
    timestamp: str


class ModelPrediction(BaseModel):
    model_config = {"protected_namespaces": ()}
    id: Optional[int] = None
    invoice_id: str
    deterministic_score: int
    model_score: Optional[float] = None
    model_version: Optional[str] = None
    shap_top_features: Optional[str] = None  # JSON string
    predicted_at: str


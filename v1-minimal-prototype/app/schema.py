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

class MatchResult(BaseModel):
    invoice_id: str
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

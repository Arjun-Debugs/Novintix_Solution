import os
import json
import re
from datetime import datetime
import pandas as pd
from app.schema import NormalizedRecord

# Default FX rates path
DEFAULT_FX_RATES_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "fx_rates.json")
)

def load_fx_rates(path: str = DEFAULT_FX_RATES_PATH) -> dict:
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return {"USD": 83.5, "EUR": 90.0, "INR": 1.0}

def clean_amount_string(amount_str: str) -> float:
    # Remove any characters except digits, commas, dots, and negative sign
    cleaned = re.sub(r"[^\d,\.\-]", "", amount_str)
    
    # If both comma and dot are present: e.g., 1,200.00 or 1.200,00
    if "," in cleaned and "." in cleaned:
        # Determine which one comes last to identify the decimal separator
        comma_idx = cleaned.rfind(",")
        dot_idx = cleaned.rfind(".")
        if comma_idx > dot_idx:
            # Comma is decimal separator (e.g., 1.200,50)
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            # Dot is decimal separator (e.g., 1,200.50)
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        # Only comma is present: e.g., 500,00 or 1,200
        comma_idx = cleaned.rfind(",")
        # If comma is followed by exactly 2 digits, it is likely a decimal separator
        if len(cleaned) - 1 - comma_idx == 2:
            cleaned = cleaned.replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    
    try:
        return float(cleaned)
    except ValueError:
        return 0.0

def parse_date_to_iso(date_str: str) -> str:
    # Clean the input date string
    cleaned_date = date_str.strip()
    
    # Common formats to try in order
    formats = [
        "%Y-%m-%d",      # 2026-07-08
        "%m/%d/%Y",      # 07/09/2026
        "%d-%m-%Y",      # 06-07-2026
        "%B %d, %Y",     # July 7, 2026
        "%b %d, %Y",     # Jul 7, 2026
        "%Y/%m/%d",      # 2026/07/05
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(cleaned_date, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
            
    # Fallback to pandas date parsing if standard formats fail
    try:
        dt = pd.to_datetime(cleaned_date)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        # If all else fails, return original or default to today's date in ISO
        return datetime.utcnow().strftime("%Y-%m-%d")

from app.tools.fx import get_fx_rate

def normalize_record(record: dict, fx_rates: dict = None, db_path: str = None) -> NormalizedRecord:
    # Get record identification
    record_id = record.get("invoice_id") or record.get("receipt_id") or record.get("po_number")
    po_number = record.get("po_number")
    
    # Normalize vendor name
    vendor_name = record.get("vendor_name", "").strip().lower()
    
    # Normalize amount
    raw_amount = record.get("amount", "0.0")
    amount_val = clean_amount_string(raw_amount)
    
    # Normalize currency and convert to INR
    raw_currency = record.get("currency", "INR").strip().upper()
    currency = re.sub(r"[^A-Z]", "", raw_currency)
    
    # Resolve FX rate and rate source
    if fx_rates is not None:
        rate = fx_rates.get(currency, 1.0)
        source = "static_fallback"
    else:
        rate, source = get_fx_rate(currency, "INR", db_path=db_path) if db_path else get_fx_rate(currency, "INR")
        
    amount_inr = round(amount_val * rate, 2)
    
    # Normalize date
    raw_date = record.get("invoice_date") or record.get("po_date") or record.get("receipt_date") or record.get("date") or ""
    normalized_date = parse_date_to_iso(raw_date)
    
    # Quantity
    quantity = record.get("quantity")
    if quantity is not None:
        try:
            quantity = float(quantity)
        except ValueError:
            quantity = None
            
    return NormalizedRecord(
        record_id=record_id,
        po_number=po_number,
        vendor_name=vendor_name,
        amount_inr=amount_inr,
        date=normalized_date,
        quantity=quantity,
        raw_amount=str(raw_amount),
        raw_currency=str(raw_currency),
        raw_date=str(raw_date),
        rate_source=source
    )

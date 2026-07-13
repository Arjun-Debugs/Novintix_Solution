import sys
import os

# Add project root to Python search path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import streamlit as st
import json
import sqlite3
import pandas as pd
from app.orchestrator import process_invoice
from app.audit import log_decision, get_all_decisions, clear_decisions
from app.tools.normalize import load_fx_rates

# Setup paths relative to workspace
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
INVOICES_PATH = os.path.join(BASE_DIR, "data", "erp_a_invoices.json")
POS_PATH = os.path.join(BASE_DIR, "data", "erp_b_purchase_orders.json")
RECEIPTS_PATH = os.path.join(BASE_DIR, "data", "erp_c_receipts.json")

# Set Page Configuration
st.set_page_config(
    page_title="Invoice Matching Agent Dashboard",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom premium styling
st.markdown("""
<style>
    /* Main body background styling */
    .stApp {
        background-color: #0f111a;
        color: #e2e8f0;
    }
    
    /* Title and headers */
    h1, h2, h3 {
        color: #ffffff !important;
        font-family: 'Outfit', 'Inter', sans-serif;
        font-weight: 700;
    }
    
    /* Card style */
    .metric-card {
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
        border: 1px solid #334155;
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
        text-align: center;
    }
    
    .metric-val {
        font-size: 2.2rem;
        font-weight: 800;
        margin: 5px 0;
        font-family: 'Outfit', sans-serif;
    }
    
    .metric-title {
        color: #94a3b8;
        font-size: 0.9rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    
    /* Table styling */
    .status-badge {
        display: inline-block;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.85rem;
        font-weight: 600;
        text-align: center;
    }
    
    .badge-approved {
        background-color: rgba(16, 185, 129, 0.15);
        color: #10b981;
        border: 1px solid rgba(16, 185, 129, 0.3);
    }
    
    .badge-review {
        background-color: rgba(245, 158, 11, 0.15);
        color: #f59e0b;
        border: 1px solid rgba(245, 158, 11, 0.3);
    }
    
    .badge-escalated {
        background-color: rgba(239, 68, 68, 0.15);
        color: #ef4444;
        border: 1px solid rgba(239, 68, 68, 0.3);
    }
    
    /* Code styling */
    code {
        color: #38bdf8 !important;
        background-color: #1e293b !important;
    }
</style>
""", unsafe_allow_html=True)

def run_pipeline() -> list:
    """
    Loads raw data, processes each invoice, logs the decision to SQLite, and returns results.
    """
    # Load files
    with open(INVOICES_PATH, "r") as f:
        invoices_raw = json.load(f)
    with open(POS_PATH, "r") as f:
        pos_raw = json.load(f)
    with open(RECEIPTS_PATH, "r") as f:
        receipts_raw = json.load(f)
        
    fx_rates = load_fx_rates()
    
    clear_decisions()
    
    results = []
    for inv in invoices_raw:
        res = process_invoice(inv, pos_raw, receipts_raw, fx_rates)
        log_decision(res)
        results.append(res)
        
    return results

def get_original_invoice(invoice_id: str) -> dict:
    """
    Retrieves the original raw invoice fields.
    """
    with open(INVOICES_PATH, "r") as f:
        invoices = json.load(f)
    for inv in invoices:
        if inv.get("invoice_id") == invoice_id:
            return inv
    return {}

# --- Header ---
st.title("💼 Invoice Matching Agent Dashboard")
st.markdown("An audit-focused finance tool utilizing a deterministic matching and scoring engine to reconcile invoices, purchase orders, and receipts.")

# Run pipeline on first load if db is empty
db_decisions = get_all_decisions()
if not db_decisions:
    results = run_pipeline()
    db_decisions = get_all_decisions()
else:
    # Retrieve existing decisions and reconstruct match results
    # To display correctly, we can just run the pipeline or map details.
    # Re-running the pipeline is fast and ensures we have the memory structure.
    with open(INVOICES_PATH, "r") as f:
        invoices_raw = json.load(f)
    with open(POS_PATH, "r") as f:
        pos_raw = json.load(f)
    with open(RECEIPTS_PATH, "r") as f:
        receipts_raw = json.load(f)
    results = [process_invoice(inv, pos_raw, receipts_raw) for inv in invoices_raw]

# --- Sidebar Actions & Config ---
with st.sidebar:
    st.header("⚙️ Control Panel")
    st.markdown("Trigger a live run of the reconciliation pipeline. This will clear the audit log, re-ingest all files, and update the routing decisions.")
    
    if st.button("🔄 Reprocess Pipeline", type="primary", use_container_width=True):
        with st.spinner("Processing ERP data..."):
            results = run_pipeline()
            db_decisions = get_all_decisions()
            st.success("Pipeline reprocessed successfully!")
            st.toast("Reconciliation completed!", icon="✅")
            
    st.markdown("---")
    st.markdown("### System Context")
    st.info(
        "**Agent Design**:\n"
        "This agent operates as a **deterministic tool-orchestration pipeline** (no live LLM is invoked). "
        "This architectural choice guarantees reproducibility, auditability, and speed, which are essential for finance automation.\n\n"
        "**Offline-Capable**:\n"
        "Static exchange rates are loaded from `fx_rates.json`."
    )
    
    st.markdown("### Exchange Rates (INR Base)")
    fx = load_fx_rates()
    for currency, rate in fx.items():
        st.write(f"- **{currency}**: {rate} INR")

# --- KPI Dashboard ---
total_count = len(results)
approved_count = sum(1 for r in results if r.status == "auto_approved")
review_count = sum(1 for r in results if r.status == "needs_human_review")
escalated_count = sum(1 for r in results if r.status == "escalated")
avg_confidence = int(round(sum(r.confidence_score for r in results) / total_count)) if total_count > 0 else 0

kpi_cols = st.columns(5)

with kpi_cols[0]:
    st.markdown(
        f'<div class="metric-card">'
        f'<div class="metric-title">Total Invoices</div>'
        f'<div class="metric-val" style="color: #38bdf8;">{total_count}</div>'
        f'</div>',
        unsafe_allow_html=True
    )
with kpi_cols[1]:
    st.markdown(
        f'<div class="metric-card">'
        f'<div class="metric-title">Auto-Approved</div>'
        f'<div class="metric-val" style="color: #10b981;">{approved_count}</div>'
        f'</div>',
        unsafe_allow_html=True
    )
with kpi_cols[2]:
    st.markdown(
        f'<div class="metric-card">'
        f'<div class="metric-title">Needs Review</div>'
        f'<div class="metric-val" style="color: #f59e0b;">{review_count}</div>'
        f'</div>',
        unsafe_allow_html=True
    )
with kpi_cols[3]:
    st.markdown(
        f'<div class="metric-card">'
        f'<div class="metric-title">Escalated</div>'
        f'<div class="metric-val" style="color: #ef4444;">{escalated_count}</div>'
        f'</div>',
        unsafe_allow_html=True
    )
with kpi_cols[4]:
    # Determine color for avg confidence
    conf_color = "#10b981" if avg_confidence >= 95 else ("#f59e0b" if avg_confidence >= 80 else "#ef4444")
    st.markdown(
        f'<div class="metric-card">'
        f'<div class="metric-title">Avg Confidence</div>'
        f'<div class="metric-val" style="color: {conf_color};">{avg_confidence}%</div>'
        f'</div>',
        unsafe_allow_html=True
    )

st.markdown("<br>", unsafe_allow_html=True)

# --- Invoices List Section ---
st.subheader("📋 Reconciliation Ledger")

for r in results:
    # Get status badge design
    if r.status == "auto_approved":
        status_label = "🟢 Approved"
        border_color = "#10b981"
        badge_style = "badge-approved"
    elif r.status == "needs_human_review":
        status_label = "🟡 Needs Review"
        border_color = "#f59e0b"
        badge_style = "badge-review"
    else:
        status_label = "🔴 Escalated"
        border_color = "#ef4444"
        badge_style = "badge-escalated"
        
    expander_title = f"{status_label} | {r.invoice_id} — Vendor: {r.summary.split(' — ')[0].split(': ')[1] if '—' in r.summary else r.invoice_id} | Confidence: {r.confidence_score}%"
    
    # Render st.expander with the customized label
    with st.expander(expander_title):
        # Header banner containing the summary
        st.markdown(f"**Reconciliation Summary:** `{r.summary}`")
        
        # Core details side-by-side columns
        col1, col2, col3 = st.columns(3)
        
        # Raw inputs comparison
        raw_inv = get_original_invoice(r.invoice_id)
        with col1:
            st.markdown("### 📥 Raw Invoice (ERP A)")
            st.markdown(f"- **Invoice ID**: `{raw_inv.get('invoice_id', 'N/A')}`")
            st.markdown(f"- **Vendor**: `{raw_inv.get('vendor_name', 'N/A')}`")
            st.markdown(f"- **Amount**: `{raw_inv.get('amount', 'N/A')}` (`{raw_inv.get('currency', 'N/A')}`)")
            st.markdown(f"- **Date**: `{raw_inv.get('invoice_date', 'N/A')}`")
            st.markdown(f"- **Quantity**: `{raw_inv.get('quantity') if raw_inv.get('quantity') is not None else 'N/A'}`")
            
        with col2:
            st.markdown("### ⚙️ Normalized Values (Base)")
            st.markdown(f"- **Vendor (Cleaned)**: `{r.summary.split(' — ')[0].split(': ')[1] if '—' in r.summary else raw_inv.get('vendor_name', '').lower()}`")
            st.markdown(f"- **Amount (INR)**: `{r.normalized_amount_inr:,.2f} INR`")
            st.markdown(f"- **Date (ISO)**: `{r.discrepancies.get('date_valid') and r.timestamp[:10] or 'Parsed'}`") # date format placeholder or raw
            # Let's read normalized record details from results
            st.markdown(f"- **Associated PO**: `{r.po_id or 'None'}`")
            st.markdown(f"- **Associated Receipt**: `{r.receipt_id or 'None'}`")
            
        with col3:
            st.markdown("### 📊 Matching Discrepancies")
            # Amount delta
            delta = r.discrepancies.get("amount_delta_pct", 0.0)
            st.markdown(f"- **Amount Discrepancy**: `{delta}%`")
            
            # Vendor score
            v_score = r.discrepancies.get("vendor_match_score", 0.0)
            st.markdown(f"- **Vendor Match Score**: `{v_score}%`")
            
            # Date valid
            d_valid = r.discrepancies.get("date_valid", False)
            date_status = "✅ Valid (Invoice after PO)" if d_valid else "❌ Invalid / Missing PO"
            st.markdown(f"- **Date Sequence**: {date_status}")
            
        st.markdown("### 🧾 Audit Log & Reasoning Trail")
        for reason in r.reasons:
            if "100.0/100" in reason or "40.0/40" in reason or "25.0/25" in reason or "15.0/15" in reason or "20.0/20" in reason or "matches exactly" in reason or "plausibility verified" in reason or "Quantities match" in reason:
                st.markdown(f"- ✅ {reason}")
            else:
                st.markdown(f"- ⚠️ {reason}")
                
        st.caption(f"Logged at (UTC): {r.timestamp}")

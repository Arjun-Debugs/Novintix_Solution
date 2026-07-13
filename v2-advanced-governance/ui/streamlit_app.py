import os
# Configure OpenMP, BLAS, MKL, and NumExpr thread limits at the absolute entry point
# to prevent binary thread initialization crashes and memory segmentation faults in containerized environments.
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

# Force PyArrow to use the standard system memory allocator (malloc/free)
# to avoid jemalloc-related memory allocation segmentation faults on Linux container hosts.
os.environ["ARROW_DEFAULT_MEMORY_POOL"] = "system"

import faulthandler
faulthandler.enable()

print("[Reconciliation App] App process started. Loading standard libraries...", flush=True)
import sys
import datetime
import json
print("[Reconciliation App] Loading pandas...", flush=True)
import pandas as pd
print("[Reconciliation App] Loading streamlit...", flush=True)
import streamlit as st
print("[Reconciliation App] Loading plotly...", flush=True)
import plotly.express as px
from io import BytesIO

# Add project root to Python search path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

print("[Reconciliation App] Loading internal application modules...", flush=True)
from app.orchestrator import process_invoice
from app.audit import DEFAULT_DB_PATH
from app.db import DecisionRepository, OverrideRepository, FxCacheRepository, ModelPredictionRepository, UserRepository, AuditLogRepository, ConfigRepository
from app.schema import ReviewOverride
from app.db_connection import get_connection
import streamlit_authenticator as stauth

print("[Reconciliation App] Running DB migrations...", flush=True)
# Bootstrap database tables
from app.db_migrations import run_migrations
run_migrations(DEFAULT_DB_PATH)

print("[Reconciliation App] Loading reportlab components (deferred to runtime)...", flush=True)

# Setup paths relative to workspace
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
INVOICES_PATH = os.path.join(BASE_DIR, "data", "erp_a_invoices.json")
POS_PATH = os.path.join(BASE_DIR, "data", "erp_b_purchase_orders.json")
RECEIPTS_PATH = os.path.join(BASE_DIR, "data", "erp_c_receipts.json")

# Set Page Configuration
st.set_page_config(
    page_title="Invoice Reconciliation Ledger",
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
    h1, h2, h3, h4 {
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
        transition: transform 0.2s;
    }
    .metric-card:hover {
        transform: translateY(-2px);
    }
    
    .metric-val {
        font-size: 2.2rem;
        font-weight: 800;
        margin: 5px 0;
        font-family: 'Outfit', sans-serif;
    }
    
    .metric-title {
        color: #94a3b8;
        font-size: 0.8rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    
    /* Box details */
    .detail-box {
        background-color: #1a2035;
        border: 1px solid #2e3856;
        border-radius: 8px;
        padding: 15px;
        margin: 5px 0;
        min-height: 190px;
    }
    
    .detail-box h4 {
        margin-top: 0px !important;
        margin-bottom: 12px !important;
        font-size: 1.1rem;
        font-weight: 600;
    }
    
    /* Status badges */
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
</style>
""", unsafe_allow_html=True)

# --- User Authentication & RBAC ---
user_repo = UserRepository(DEFAULT_DB_PATH)
try:
    db_users = user_repo.get_all_users()
except Exception as e:
    db_users = []

credentials = {"usernames": {}}
for u in db_users:
    credentials["usernames"][u["username"]] = {
        "email": u["email"],
        "name": u["name"],
        "password": u["password"]
    }

authenticator = stauth.Authenticate(
    credentials,
    "reconciliation_cookie",
    os.environ.get("AUTH_COOKIE_KEY", "reconciliation_key_2026"),
    30
)

# Render the login form on the main page
# We use the standard stauth login form
name, authentication_status, username = authenticator.login("main")

if st.session_state.get("authentication_status") is False:
    st.error("Invalid username or password. Please try again.")
    st.stop()
elif st.session_state.get("authentication_status") is None:
    st.warning("Please enter your credentials to access the dashboard.")
    st.stop()

# Set user role in session state
current_username = st.session_state["username"]
user_details = user_repo.get_user(current_username)
user_role = user_details["role"] if user_details else "reviewer"
st.session_state["role"] = user_role

# Log successful login to Audit Logs (once per session)
if st.session_state.get("authentication_status") is True:
    if "logged_login_event" not in st.session_state:
        audit_repo = AuditLogRepository(DEFAULT_DB_PATH)
        audit_repo.log_event(current_username, "LOGIN", "Successfully logged into the reconciliation portal.")
        st.session_state["logged_login_event"] = True

# Helper function to format timestamps into IST timezone
def format_professional_timestamp(iso_str: str) -> str:
    if not iso_str:
        return "N/A"
    try:
        clean_str = iso_str.replace("Z", "+00:00")
        if "." in clean_str:
            base, fraction_offset = clean_str.split(".")
            if "+" in fraction_offset:
                offset = "+" + fraction_offset.split("+")[1]
            elif "-" in fraction_offset:
                offset = "-" + fraction_offset.split("-")[1]
            else:
                offset = ""
            dt = datetime.datetime.fromisoformat(base + offset)
        else:
            dt = datetime.datetime.fromisoformat(clean_str)
            
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        utc_dt = dt.astimezone(datetime.timezone.utc)
        ist_dt = utc_dt + datetime.timedelta(hours=5, minutes=30)
        return ist_dt.strftime("%b %d, %Y at %I:%M %p (IST)")
    except Exception:
        return iso_str

# PDF generator helper
def generate_pdf_report(start_date, end_date) -> bytes:
    # Deferred reportlab imports to prevent startup binary conflicts
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors

    decision_repo = DecisionRepository(DEFAULT_DB_PATH)
    override_repo = OverrideRepository(DEFAULT_DB_PATH)
    
    results = decision_repo.get_all(include_archived=False)
    overrides = override_repo.get_all()
    
    start_str = start_date.isoformat()
    end_str = end_date.isoformat()
    
    filtered_results = [r for r in results if start_str <= r.timestamp[:10] <= end_str]
    
    # Filter overrides
    filtered_overrides = []
    for o in overrides:
        if start_str <= o.timestamp[:10] <= end_str:
            filtered_overrides.append(o)
            
    total_processed = len(filtered_results)
    status_counts = {"auto_approved": 0, "needs_human_review": 0, "escalated": 0}
    for r in filtered_results:
        status_counts[r.status] = status_counts.get(r.status, 0) + 1
        
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    story = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'DocTitle', parent=styles['Heading1'], fontSize=18, textColor=colors.HexColor('#0f172a'), spaceAfter=15
    )
    section_style = ParagraphStyle(
        'SectionHeader', parent=styles['Heading2'], fontSize=13, textColor=colors.HexColor('#1e293b'), spaceBefore=12, spaceAfter=6
    )
    body_style = styles['BodyText']
    
    story.append(Paragraph("Invoice Reconciliation Compliance Audit Report", title_style))
    now_ist = format_professional_timestamp(datetime.datetime.utcnow().isoformat())
    story.append(Paragraph(f"<b>Generation Timestamp (IST):</b> {now_ist}", body_style))
    story.append(Paragraph(f"<b>Audit Date Range:</b> {start_str} to {end_str}", body_style))
    story.append(Spacer(1, 15))
    
    story.append(Paragraph("Execution Summary Metrics", section_style))
    stats_data = [
        ["Metric", "Count"],
        ["Total Invoices Processed", str(total_processed)],
        ["Auto-Approved", str(status_counts["auto_approved"])],
        ["Needs Human Review", str(status_counts["needs_human_review"])],
        ["Escalated", str(status_counts["escalated"])],
        ["Manual Overrides Logged", str(len(filtered_overrides))]
    ]
    t_stats = Table(stats_data, colWidths=[220, 100])
    t_stats.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#334155')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
        ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#f8fafc')),
    ]))
    story.append(t_stats)
    story.append(Spacer(1, 15))
    
    story.append(Paragraph("Manual Governance Override Log", section_style))
    if not filtered_overrides:
        story.append(Paragraph("No manual overrides logged in this date range.", body_style))
    else:
        log_data = [["Invoice ID", "Reviewer", "Decision", "Note", "Timestamp"]]
        for o in filtered_overrides:
            time_str = format_professional_timestamp(o.timestamp)[:22]
            log_data.append([
                o.invoice_id,
                o.reviewer,
                o.human_decision.upper(),
                o.reviewer_note[:30] + "..." if len(o.reviewer_note) > 30 else o.reviewer_note,
                time_str
            ])
        t_log = Table(log_data, colWidths=[90, 80, 80, 150, 100])
        t_log.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1e293b')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('FONTSIZE', (0,0), (-1,-1), 8),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
            ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#f8fafc')),
        ]))
        story.append(t_log)
        
    doc.build(story)
    return buffer.getvalue()

# CSV generator helper
def generate_csv_report(results_list) -> str:
    import io
    import csv
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Invoice ID", "Vendor Name", "Invoice Date", "PO ID", "Receipt ID", 
        "Machine Status", "Confidence Score", "Amount INR", "Reasons"
    ])
    for r in results_list:
        writer.writerow([
            r.invoice_id,
            r.vendor_name,
            r.invoice_date,
            r.po_id,
            r.receipt_id,
            r.status,
            r.confidence_score,
            r.normalized_amount_inr,
            "; ".join(r.reasons)
        ])
    return output.getvalue()

# 1. Caching data processing logic
@st.cache_data
def load_and_process_data() -> list:
    with open(INVOICES_PATH, "r") as f:
        invoices_raw = json.load(f)
    with open(POS_PATH, "r") as f:
        pos_raw = json.load(f)
    with open(RECEIPTS_PATH, "r") as f:
        receipts_raw = json.load(f)
        
    results = []
    for inv in invoices_raw:
        res = process_invoice(inv, pos_raw, receipts_raw, db_path=DEFAULT_DB_PATH)
        results.append(res)
    return results

def get_original_invoice(invoice_id: str) -> dict:
    with open(INVOICES_PATH, "r") as f:
        invoices = json.load(f)
    for inv in invoices:
        if inv.get("invoice_id") == invoice_id:
            return inv
    return {}

def get_purchase_order(po_number: str) -> dict:
    if not po_number:
        return {}
    with open(POS_PATH, "r") as f:
        pos = json.load(f)
    for po in pos:
        if po.get("po_number") == po_number:
            return po
    return {}

# Instantiate Repositories
decision_repo = DecisionRepository(DEFAULT_DB_PATH)
override_repo = OverrideRepository(DEFAULT_DB_PATH)
model_repo = ModelPredictionRepository(DEFAULT_DB_PATH)

# --- Direct DB Load Optimization ---
results = decision_repo.get_all(include_archived=False)
if not results:
    with st.spinner("Initializing accounts payable matching engine..."):
        results = load_and_process_data()
        for res in results:
            decision_repo.upsert(res)

# Sidebar control panel
with st.sidebar:
    st.markdown(f"### Logged in: **{st.session_state['name']}**")
    st.markdown(f"Role: `{st.session_state['role'].upper()}`")
    authenticator.logout("Logout from Portal", "sidebar")
    st.markdown("---")
    
    st.header("Control Panel")
    is_admin = st.session_state.get("role") == "admin"
    if is_admin:
        if st.button("Reprocess Data Pipeline", type="primary", use_container_width=True):
            with st.spinner("Processing ERP data..."):
                st.cache_data.clear()
                decision_repo.archive_all()
                results = load_and_process_data()
                for res in results:
                    decision_repo.upsert(res)
                # Log reprocessing event
                audit_repo = AuditLogRepository(DEFAULT_DB_PATH)
                audit_repo.log_event(current_username, "REPROCESS_PIPELINE", "Triggered full reprocessing of the Accounts Payable data pipeline.")
                st.success("Pipeline reprocessed successfully!")
                st.toast("Reconciliation completed!")
                st.rerun()
    else:
        st.button("Reprocess Data Pipeline", type="primary", use_container_width=True, disabled=True, help="Only administrators can reprocess the pipeline.")
            
    st.markdown("---")
    st.markdown("### FX Conversion Status")
    live_rate_count = sum(1 for r in results if any("live rate" in rs for rs in r.reasons))
    fallback_rate_count = sum(1 for r in results if any("static fallback rate" in rs for rs in r.reasons))
    if live_rate_count > 0:
        st.success(f"FX API: Online\n({live_rate_count} live rates cached)")
    else:
        st.warning(f"FX API: Offline\n({fallback_rate_count} static fallbacks used)")
        
# Calculate counts for KPI dashboard
total_count = len(results)
approved_count = sum(1 for r in results if r.status == "auto_approved")
review_count = sum(1 for r in results if r.status == "needs_human_review")
escalated_count = sum(1 for r in results if r.status == "escalated")
avg_confidence = int(round(sum(r.confidence_score for r in results) / total_count)) if total_count > 0 else 0
overrides_count = len(override_repo.get_all())

# Render Queue Count in Sidebar
unactioned_count = sum(1 for r in results if r.status in {"needs_human_review", "escalated"} and override_repo.get_latest(r.invoice_id) is None)
st.sidebar.markdown("---")
st.sidebar.markdown(f"### Review Queue Status")
if unactioned_count > 0:
    st.sidebar.warning(f"{unactioned_count} Unactioned Overrides")
else:
    st.sidebar.success("Review Queue Clear")

# Main Header
st.title("Invoice Reconciliation Dashboard")
st.markdown("An audit-focused finance tool utilizing a deterministic matching and scoring engine to reconcile invoices, purchase orders, and receipts.")

# --- KPI Dashboard ---
kpi_cols = st.columns(6)
with kpi_cols[0]:
    st.markdown(f'<div class="metric-card"><div class="metric-title">Total Invoices</div><div class="metric-val" style="color: #38bdf8;">{total_count}</div></div>', unsafe_allow_html=True)
with kpi_cols[1]:
    st.markdown(f'<div class="metric-card"><div class="metric-title">Auto-Approved</div><div class="metric-val" style="color: #10b981;">{approved_count}</div></div>', unsafe_allow_html=True)
with kpi_cols[2]:
    st.markdown(f'<div class="metric-card"><div class="metric-title">Needs Review</div><div class="metric-val" style="color: #f59e0b;">{review_count}</div></div>', unsafe_allow_html=True)
with kpi_cols[3]:
    st.markdown(f'<div class="metric-card"><div class="metric-title">Escalated</div><div class="metric-val" style="color: #ef4444;">{escalated_count}</div></div>', unsafe_allow_html=True)
with kpi_cols[4]:
    conf_color = "#10b981" if avg_confidence >= 95 else ("#f59e0b" if avg_confidence >= 80 else "#ef4444")
    st.markdown(f'<div class="metric-card"><div class="metric-title">Avg Confidence</div><div class="metric-val" style="color: {conf_color};">{avg_confidence}%</div></div>', unsafe_allow_html=True)
with kpi_cols[5]:
    st.markdown(f'<div class="metric-card"><div class="metric-title">Human Overrides</div><div class="metric-val" style="color: #c084fc;">{overrides_count}</div></div>', unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# Create layout tabs dynamically based on role
is_admin = (st.session_state.get("role") == "admin")
if is_admin:
    tab_queue, tab_analytics, tab_insights, tab_admin = st.tabs([
        "Reconciliation Ledger", 
        "Financial Analytics", 
        "Machine Learning Insights",
        "🛠️ Administrator Control Center"
    ])
else:
    tab_queue, tab_analytics, tab_insights = st.tabs([
        "Reconciliation Ledger", 
        "Financial Analytics", 
        "Machine Learning Insights"
    ])

with tab_queue:
    st.subheader("Reconciliation Ledger")
    
    # Filter tools
    status_filter = st.selectbox("Filter by Machine Routing:", ["All", "auto_approved", "needs_human_review", "escalated"])
    
    for r in results:
        if status_filter != "All" and r.status != status_filter:
            continue
            
        # Get status badge design
        override = override_repo.get_latest(r.invoice_id)
        if override:
            status_label = f"🟣 HUMAN OVERRIDE: {override.human_decision.upper()}"
            status_color = "#c084fc"
        elif r.status == "auto_approved":
            status_label = "🟢 APPROVED"
            status_color = "#10b981"
        elif r.status == "needs_human_review":
            status_label = "🟡 UNDER REVIEW"
            status_color = "#f59e0b"
        else:
            status_label = "🔴 ESCALATED"
            status_color = "#ef4444"
            
        # BUG 3 FIX: Read r.vendor_name directly instead of parsing summary
        expander_title = f"{status_label}  |  {r.invoice_id}  —  Vendor: {r.vendor_name}  |  Confidence: {r.confidence_score}%"
        
        # Keep expanded after st.rerun if they clicked explain button
        should_expand = (st.session_state.get("expanded_invoice_id") == r.invoice_id)
        with st.expander(expander_title, expanded=should_expand):
            st.markdown(f"**Reconciliation Summary:** `{r.summary}`")
            
            # Core details side-by-side columns (Overhauled visual card details - Question 2)
            col1, col2, col3 = st.columns(3)
            raw_inv = get_original_invoice(r.invoice_id)
            
            with col1:
                st.markdown(f"""
                <div class="detail-box">
                    <h4 style="color:#38bdf8;">Invoice details (ERP A)</h4>
                    <p style="margin:2px 0;"><b>Invoice ID:</b> <code>{raw_inv.get('invoice_id', 'N/A')}</code></p>
                    <p style="margin:2px 0;"><b>Vendor:</b> {raw_inv.get('vendor_name', 'N/A')}</p>
                    <p style="margin:2px 0;"><b>Amount (Raw):</b> {raw_inv.get('amount', 'N/A')} {raw_inv.get('currency', 'INR')}</p>
                    <p style="margin:2px 0;"><b>Amount (INR):</b> {r.normalized_amount_inr:,.2f} INR</p>
                    <p style="margin:2px 0;"><b>Date:</b> {raw_inv.get('invoice_date') or raw_inv.get('date', 'N/A')}</p>
                    <p style="margin:2px 0;"><b>Quantity:</b> {raw_inv.get('quantity') if raw_inv.get('quantity') is not None else 'N/A'}</p>
                </div>
                """, unsafe_allow_html=True)
                
            with col2:
                if r.po_id:
                    po = get_purchase_order(r.po_id)
                    st.markdown(f"""
                    <div class="detail-box">
                        <h4 style="color:#10b981;">Purchase Order (ERP B)</h4>
                        <p style="margin:2px 0;"><b>PO Number:</b> <code>{po.get('po_number', 'N/A')}</code></p>
                        <p style="margin:2px 0;"><b>PO Vendor:</b> {po.get('vendor_name', 'N/A')}</p>
                        <p style="margin:2px 0;"><b>Expected Amount:</b> {po.get('amount', 'N/A')} {po.get('currency', 'INR')}</p>
                        <p style="margin:2px 0;"><b>PO Date:</b> {po.get('po_date', 'N/A')}</p>
                        <p style="margin:2px 0;"><b>PO Quantity:</b> {po.get('quantity') if po.get('quantity') is not None else 'N/A'}</p>
                        <p style="margin:2px 0;"><b>Associated Receipt:</b> <code>{r.receipt_id or 'None'}</code></p>
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    st.markdown(f"""
                    <div class="detail-box">
                        <h4 style="color:#ef4444;">Purchase Order (ERP B)</h4>
                        <p style="margin-top:20px; font-weight:bold; text-align:center; color:#ef4444;">No Associated Purchase Order Found</p>
                    </div>
                    """, unsafe_allow_html=True)
                
            with col3:
                # Dynamic visual check variables
                date_valid = r.discrepancies.get('date_valid')
                if date_valid:
                    date_html = '<span style="color:#10b981; font-weight:bold;">✓ Valid Chronology</span>'
                else:
                    date_html = '<span style="color:#ef4444; font-weight:bold;">✗ Chronology Mismatch</span>'
                
                amt_delta = r.discrepancies.get('amount_delta_pct', 0.0)
                if amt_delta == 0.0:
                    amt_html = '<span style="color:#10b981; font-weight:bold;">0.0% (Exact Match)</span>'
                else:
                    amt_html = f'<span style="color:#f59e0b; font-weight:bold;">{amt_delta}% Variance</span>'
                    
                v_score = r.discrepancies.get('vendor_match_score', 0.0)
                if v_score == 100.0:
                    v_html = '<span style="color:#10b981; font-weight:bold;">100% Match</span>'
                else:
                    v_html = f'<span style="color:#f59e0b; font-weight:bold;">{v_score}% Match</span>'
                    
                score_color = "#10b981" if r.confidence_score >= 95 else ("#f59e0b" if r.confidence_score >= 80 else "#ef4444")
                score_html = f'<span style="color:{score_color}; font-weight:800;">{r.confidence_score}/100</span>'

                st.markdown(f"""
                <div class="detail-box">
                    <h4 style="color:#f59e0b;">Reconciliation Verification</h4>
                    <p style="margin:2px 0;"><b>Amount Delta:</b> {amt_html}</p>
                    <p style="margin:2px 0;"><b>Vendor Score:</b> {v_html}</p>
                    <p style="margin:2px 0;"><b>Date Plausibility:</b> {date_html}</p>
                    <p style="margin:2px 0;"><b>Deterministic Score:</b> {score_html}</p>
                </div>
                """, unsafe_allow_html=True)
                
            st.markdown("### Audit Trail & Rules Evaluation")
            for reason in r.reasons:
                if any(x in reason for x in ["100.0/100", "40.0/40", "25.0/25", "15.0/15", "20.0/20", "matches exactly", "plausibility verified", "Quantities match"]):
                    st.markdown(f"""
                    <div style="background-color: rgba(16, 185, 129, 0.05); border: 1px solid rgba(16, 185, 129, 0.2); padding: 8px 12px; border-radius: 6px; margin: 4px 0; font-size: 0.9rem;">
                        <span style="color:#10b981; font-weight:bold; margin-right:8px;">✓ PASS</span> {reason}
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    st.markdown(f"""
                    <div style="background-color: rgba(245, 158, 11, 0.05); border: 1px solid rgba(245, 158, 11, 0.2); padding: 8px 12px; border-radius: 6px; margin: 4px 0; font-size: 0.9rem;">
                        <span style="color:#f59e0b; font-weight:bold; margin-right:8px;">⚠ WARNING</span> {reason}
                    </div>
                    """, unsafe_allow_html=True)
            
            # --- AI Explainability Report (Placed above controls) ---
            has_ai_explanation = r.explanation_text and not r.explanation_text.startswith("### Deterministic Match")
            if has_ai_explanation:
                # Format to place Summary, Likely Cause, and Suggested Action on newlines with spacing
                lines = [line.strip() for line in r.explanation_text.split("\n") if line.strip()]
                formatted_text = "\n\n".join(lines)
                st.info(formatted_text)
            else:
                if st.button("Explain with AI (Groq)", key=f"btn_explain_{r.invoice_id}", use_container_width=True):
                    with st.spinner("Analyzing match criteria with Groq AI..."):
                        # Save the current invoice_id to state so it stays expanded after st.rerun
                        st.session_state["expanded_invoice_id"] = r.invoice_id
                        from app.tools.explain import generate_decision_explanation
                        explanation = generate_decision_explanation(r)
                        r.explanation_text = explanation
                        decision_repo.update_explanation(r.invoice_id, explanation)
                        st.rerun()

            # Human Override Section
            st.markdown("---")
            st.markdown("### Governance Override Controls")
            
            if override:
                st.markdown(f"**Override Status**: `LOGGED`")
                st.success(
                    f"**Human Decision**: `{override.human_decision.upper()}`\n\n"
                    f"**Logged By**: `{override.reviewer}`\n\n"
                    f"**Note**: {override.reviewer_note or 'None'}\n\n"
                    f"**Timestamp**: {format_professional_timestamp(override.timestamp)}"
                )
            else:
                user_role = st.session_state.get("role", "viewer")
                can_override = user_role in {"admin", "reviewer"}
                if not can_override:
                    st.info("🔒 Read-only access: Your user role cannot submit governance overrides.")
                else:
                    from app.review import validate_override, log_override
                    if r.status == "auto_approved":
                        st.markdown("Auto-approved items can only be **Disputed**.")
                        with st.form(key=f"dispute_form_{r.invoice_id}"):
                            note = st.text_input("Reviewer note (Explain details, min 10 chars):", key=f"note_txt_{r.invoice_id}", placeholder="Explain reason for dispute...")
                            submit = st.form_submit_button("Dispute Auto-Approval", use_container_width=True)
                            if submit:
                                ok, msg = validate_override(r.status, "disputed", note)
                                if ok:
                                    log_override(r.invoice_id, current_username, r.status, r.confidence_score, "disputed", note, DEFAULT_DB_PATH)
                                    decision_repo.update_status(r.invoice_id, "disputed")
                                    audit_repo = AuditLogRepository(DEFAULT_DB_PATH)
                                    audit_repo.log_event(current_username, "OVERRIDE_DISPUTE", f"Disputed auto-approval for invoice {r.invoice_id}. Note: {note}")
                                    st.success("Override decision logged successfully!")
                                    st.rerun()
                                else:
                                    st.error(msg)
                    else:  # needs_human_review or escalated
                        st.markdown("Apply human override action below:")
                        with st.form(key=f"review_form_{r.invoice_id}"):
                            note = st.text_input("Reviewer note (Optional):", key=f"note_txt_{r.invoice_id}", placeholder="Provide reasoning for override...")
                            col_app, col_rej = st.columns(2)
                            with col_app:
                                approve_submit = st.form_submit_button("Approve", use_container_width=True)
                            with col_rej:
                                reject_submit = st.form_submit_button("Reject", type="secondary", use_container_width=True)
                            
                            if approve_submit or reject_submit:
                                decision = "approved" if approve_submit else "rejected"
                                ok, msg = validate_override(r.status, decision, note)
                                if ok:
                                    log_override(r.invoice_id, current_username, r.status, r.confidence_score, decision, note, DEFAULT_DB_PATH)
                                    decision_repo.update_status(r.invoice_id, decision)
                                    audit_repo = AuditLogRepository(DEFAULT_DB_PATH)
                                    audit_repo.log_event(current_username, f"OVERRIDE_{decision.upper()}", f"Manually {decision} invoice {r.invoice_id}. Note: {note}")
                                    st.success("Override decision logged successfully!")
                                    st.rerun()
                                else:
                                    st.error(msg)
                                
            st.caption(f"Reconciled at: {format_professional_timestamp(r.timestamp)}")

with tab_analytics:
    st.subheader("📊 Accounts Payable (AP) Reconciliation Intelligence")
    st.markdown("Interactive dashboards and risk profiling for internal audit controls and vendor compliance metrics.")
    
    if results:
        # Build pandas DataFrame for calculations
        df_res = pd.DataFrame([{
            "status": r.status,
            "score": r.confidence_score,
            "vendor": r.vendor_name,
            "amount": r.normalized_amount_inr,
            "variance_pct": r.discrepancies.get("amount_delta_pct", 0.0),
            "vendor_match_score": r.discrepancies.get("vendor_match_score", 100.0),
            "date_valid": 1 if r.discrepancies.get("date_valid", True) else 0,
            "quantity_mismatch": 1 if any("Quantity mismatch" in reason for reason in r.reasons) else 0
        } for r in results])

        # --- Financial Metrics Grid ---
        total_audited_val = df_res["amount"].sum()
        flagged_df = df_res[df_res["status"].isin(["needs_human_review", "escalated"])]
        total_exposure_val = flagged_df["amount"].sum()
        flagged_rate = (len(flagged_df) / len(df_res)) * 100 if len(df_res) > 0 else 0.0
        avg_confidence_val = df_res["score"].mean()
        
        st.markdown("---")
        st.markdown("### 💰 Financial Exposure Metrics")
        m_cols = st.columns(4)
        m_cols[0].metric(
            label="Total Value Audited",
            value=f"₹{total_audited_val:,.2f}"
        )
        m_cols[1].metric(
            label="AP Financial Exposure (At Risk)",
            value=f"₹{total_exposure_val:,.2f}",
            delta=f"{(total_exposure_val / total_audited_val * 100):.1f}% of total" if total_audited_val > 0 else "0.0%"
        )
        m_cols[2].metric(
            label="Invoice Flag Rate",
            value=f"{flagged_rate:.1f}%",
            delta=f"{len(flagged_df)} / {len(df_res)} invoices"
        )
        m_cols[3].metric(
            label="Audit Match Integrity",
            value=f"{avg_confidence_val:.1f}%",
            delta="Avg confidence score"
        )
        
        st.markdown("---")
        
        # --- Plotly Visualizations Grid ---
        col_chart1, col_chart2 = st.columns(2)
        
        with col_chart1:
            st.markdown("#### Status & Routing Distribution")
            fig_pie = px.pie(
                df_res, 
                names="status", 
                hole=0.4, 
                color="status",
                color_discrete_map={
                    "auto_approved": "#10b981", 
                    "needs_human_review": "#f59e0b", 
                    "escalated": "#ef4444"
                }
            )
            fig_pie.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color="#e2e8f0")
            st.plotly_chart(fig_pie, use_container_width=True)
            
        with col_chart2:
            # Calculate discrepancy category counts
            amount_disc_count = sum(df_res["variance_pct"] > 0.0)
            vendor_disc_count = sum(df_res["vendor_match_score"] < 100.0)
            date_disc_count = sum(df_res["date_valid"] == 0)
            quantity_disc_count = sum(df_res["quantity_mismatch"] == 1)
            
            df_exceptions = pd.DataFrame({
                "Exception Type": [
                    "Value Variance (>0%)", 
                    "Vendor Name Typo/Mismatch", 
                    "Date Chronology Exception", 
                    "Quantity Mismatch"
                ],
                "Occurrence Count": [
                    amount_disc_count, 
                    vendor_disc_count, 
                    date_disc_count, 
                    quantity_disc_count
                ]
            }).sort_values(by="Occurrence Count", ascending=True)
            
            st.markdown("#### Discrepancies by Exception Category")
            fig_exceptions = px.bar(
                df_exceptions, 
                y="Exception Type", 
                x="Occurrence Count", 
                orientation="h",
                color="Occurrence Count",
                color_continuous_scale="Viridis"
            )
            fig_exceptions.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color="#e2e8f0")
            st.plotly_chart(fig_exceptions, use_container_width=True)
            
        col_chart3, col_chart4 = st.columns(2)
        
        with col_chart3:
            st.markdown("#### Confidence Score Histogram")
            fig_hist = px.histogram(
                df_res, 
                x="score", 
                nbins=15, 
                color="status",
                color_discrete_map={
                    "auto_approved": "#10b981", 
                    "needs_human_review": "#f59e0b", 
                    "escalated": "#ef4444"
                }
            )
            fig_hist.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color="#e2e8f0")
            st.plotly_chart(fig_hist, use_container_width=True)
            
        with col_chart4:
            st.markdown("#### Exposure Value by Vendor (At Risk)")
            # Calculate exposure per vendor
            df_vendor_exp = df_res.groupby("vendor")["amount"].apply(
                lambda x: x[df_res.loc[x.index, "status"].isin(["needs_human_review", "escalated"])].sum()
            ).reset_index(name="exposure_amount").sort_values(by="exposure_amount", ascending=False)
            
            fig_vend = px.bar(
                df_vendor_exp, 
                x="vendor", 
                y="exposure_amount", 
                color="exposure_amount",
                color_continuous_scale="Reds",
                labels={"exposure_amount": "Exposure Amount (INR)", "vendor": "Vendor"}
            )
            fig_vend.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color="#e2e8f0")
            st.plotly_chart(fig_vend, use_container_width=True)
            
        # --- Improvised Vendor Risk Profiler Table ---
        st.markdown("---")
        st.markdown("### 📋 Vendor Audit Risk Summary Ledger")
        st.markdown("Sort and profile vendors based on Risk Classification, total exposure, flagged rate, and variance statistics.")
        
        unique_vendors = sorted(df_res["vendor"].unique().tolist())
        vendor_summary_rows = []
        for v in unique_vendors:
            v_df = df_res[df_res["vendor"] == v]
            if v_df.empty:
                continue
            v_total_invoices = len(v_df)
            v_flagged_invoices = len(v_df[v_df["status"].isin(["needs_human_review", "escalated"])])
            v_flag_rate = (v_flagged_invoices / v_total_invoices) * 100
            v_total_amount = v_df["amount"].sum()
            v_exposure_amount = v_df[v_df["status"].isin(["needs_human_review", "escalated"])]["amount"].sum()
            v_avg_var = v_df["variance_pct"].mean()
            
            # Dynamic Risk Classification Metric
            if v_flag_rate > 35.0 or v_exposure_amount > 100000.0:
                risk_class = "High Risk"
            elif v_flag_rate > 10.0 or v_exposure_amount > 20000.0:
                risk_class = "Medium Risk"
            else:
                risk_class = "Low Risk"
                
            vendor_summary_rows.append({
                "Vendor Name": v,
                "Risk Class": risk_class,
                "Total Invoices": v_total_invoices,
                "Flagged Invoices": v_flagged_invoices,
                "Flag Rate (%)": round(v_flag_rate, 1),
                "Total Value (INR)": round(v_total_amount, 2),
                "Financial Exposure (INR)": round(v_exposure_amount, 2),
                "Avg Value Variance (%)": round(v_avg_var, 2)
            })
            
        if vendor_summary_rows:
            df_vendor_summary = pd.DataFrame(vendor_summary_rows).sort_values(by="Financial Exposure (INR)", ascending=False)
            st.dataframe(
                df_vendor_summary,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Total Value (INR)": st.column_config.NumberColumn(format="₹%,.2f"),
                    "Financial Exposure (INR)": st.column_config.NumberColumn(format="₹%,.2f"),
                    "Flag Rate (%)": st.column_config.ProgressColumn(min_value=0.0, max_value=100.0, format="%.1f%%"),
                    "Avg Value Variance (%)": st.column_config.NumberColumn(format="%.2f%%")
                }
            )
            
    # Export Section
    st.markdown("---")
    st.markdown("### Compliance Data Exporters")
    
    col_csv, col_pdf = st.columns(2)
    
    with col_csv:
        st.markdown("#### Export Reconciliation Ledger to CSV")
        csv_data = generate_csv_report(results)
        st.download_button(
            label="Download Reconciliation Ledger (CSV)",
            data=csv_data,
            file_name=f"reconciliation_ledger_{datetime.date.today().isoformat()}.csv",
            mime="text/csv",
            use_container_width=True
        )
        
    with col_pdf:
        st.markdown("#### Compile PDF Audit Report")
        today = datetime.date.today()
        start_date = st.date_input("Report Start Date:", value=today - datetime.timedelta(days=30))
        end_date = st.date_input("Report End Date:", value=today)
        
        if st.button("Generate Compliance PDF Report", use_container_width=True):
            pdf_bytes = generate_pdf_report(start_date, end_date)
            st.download_button(
                label="Download Generated PDF Report",
                data=pdf_bytes,
                file_name=f"compliance_audit_report_{start_date.isoformat()}_to_{end_date.isoformat()}.pdf",
                mime="application/pdf",
                use_container_width=True
            )

with tab_insights:
    st.subheader("Shadow ML Scorer (XGBoost)")
    st.markdown(
        "> **Notice on Shadow Mode**: The XGBoost shadow model operates in standard shadow-prediction mode. "
        "It trains exclusively on logged human overrides and writes model scores strictly to parallel columns. "
        "It **never** alters the deterministic pipeline routing defined in `router.py`."
    )
    
    from app.tools.ml_scorer import train_shadow_model, MODEL_PATH, get_predictions_history
    
    overrides = override_repo.get_all()
    n_overrides = len(overrides)
    min_labels = 30
    
    if not os.path.exists(MODEL_PATH):
        st.warning(f"Shadow model not yet trained — {n_overrides}/{min_labels} labeled overrides collected.")
        st.progress(min(1.0, n_overrides / min_labels))
        
        is_admin = st.session_state.get("role") == "admin"
        if not is_admin:
            st.button("Attempt Manual Training", disabled=True, type="primary", help="Only administrators can trigger shadow model training.")
        else:
            if st.button("Attempt Manual Training", disabled=(n_overrides < min_labels), type="primary"):
                res = train_shadow_model(DEFAULT_DB_PATH, min_labels=min_labels)
                st.success(f"Model training status: {res}")
                st.rerun()
    else:
        st.success("Shadow XGBoost model is fully trained and running.")
        
        # Display charts if history exists
        history = get_predictions_history(DEFAULT_DB_PATH)
        if history:
            plot_data = []
            for h in history:
                if h["model_score"] is not None:
                    plot_data.append({
                        "Invoice ID": h["invoice_id"],
                        "Deterministic Score": h["deterministic_score"],
                        "Model Shadow Score": h["model_score"]
                    })
            if plot_data:
                df = pd.DataFrame(plot_data)
                
                # Render charts side-by-side
                col_chart, col_shap = st.columns(2)
                with col_chart:
                    st.markdown("#### Deterministic vs. Shadow Model Prediction")
                    st.scatter_chart(df, x="Deterministic Score", y="Model Shadow Score")
                    
                with col_shap:
                    st.markdown("#### Recent Model Explanations (SHAP values)")
                    for h in history[:5]:
                        if h["shap_top_features"]:
                            st.write(f"**Invoice {h['invoice_id']}** (Model Score: {h['model_score']}%):")
                            feat_strs = []
                            for f in h["shap_top_features"]:
                                feat_strs.append(f"`{f['feature']}`: {f['shap_value']}")
                            st.markdown(" | ".join(feat_strs))
            else:
                st.info("No predictions logged with scores yet. Process some invoices after training.")
        
        st.markdown("---")
        is_admin = st.session_state.get("role") == "admin"
        if not is_admin:
            st.button("Retrain Model Manually", disabled=True, help="Only administrators can retrain the shadow model.")
        else:
            if st.button("Retrain Model Manually"):
                res = train_shadow_model(DEFAULT_DB_PATH, min_labels=min_labels)
                st.success(f"Model retrained: {res}")
                st.rerun()

# --- Administrator Console ---
if is_admin:
    with tab_admin:
        st.subheader("🛠️ Administrator Control Center")
        
        admin_tabs = st.tabs(["Immutable Audit Trail Log", "User Directory & Creator", "System Threshold Configurations"])
        
        with admin_tabs[0]:
            st.markdown("### Immutable System Audit Trail")
            st.markdown("A compliance-focused read-only history of all portal activities and administrative overrides.")
            audit_repo = AuditLogRepository(DEFAULT_DB_PATH)
            logs = audit_repo.get_logs()
            if logs:
                df_logs = pd.DataFrame(logs)
                df_logs["timestamp"] = df_logs["timestamp"].apply(format_professional_timestamp)
                st.dataframe(df_logs, use_container_width=True, hide_index=True)
            else:
                st.info("No system audit events logged yet.")
                
        with admin_tabs[1]:
            st.markdown("### User Management Directory")
            col_form, col_dir = st.columns([1, 1])
            with col_form:
                st.markdown("#### Create New Portal User")
                with st.form(key="create_user_form", clear_on_submit=True):
                    new_user = st.text_input("Username:")
                    new_name = st.text_input("Display Name:")
                    new_email = st.text_input("Email Address:")
                    new_password = st.text_input("Password:", type="password")
                    new_role = st.selectbox("Assign System Role:", ["reviewer", "admin"])
                    submit_user = st.form_submit_button("Register User")
                    if submit_user:
                        if not new_user or not new_name or not new_email or not new_password:
                            st.error("All registration fields are required.")
                        elif " " in new_user:
                            st.error("Username cannot contain spaces.")
                        elif len(new_user) < 3:
                            st.error("Username must be at least 3 characters long.")
                        else:
                            import bcrypt
                            clean_user = new_user.lower().strip()
                            pwd_hash = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                            success = user_repo.create_user(clean_user, pwd_hash, new_name, new_email, new_role)
                            if success:
                                st.success(f"User '{clean_user}' registered successfully!")
                                audit_repo = AuditLogRepository(DEFAULT_DB_PATH)
                                audit_repo.log_event(current_username, "CREATE_USER", f"Created new user '{clean_user}' with role '{new_role}'.")
                                st.rerun()
                            else:
                                st.error("Registration failed. Username may already exist.")
                                 
            with col_dir:
                st.markdown("#### Registered Users Directory")
                all_users = user_repo.get_all_users()
                users_display = []
                for u in all_users:
                    users_display.append({
                        "Username": u["username"],
                        "Name": u["name"],
                        "Email": u["email"],
                        "Role": u["role"].upper()
                    })
                df_users_display = pd.DataFrame(users_display)
                st.dataframe(df_users_display, use_container_width=True, hide_index=True)
                
                st.markdown("#### Deactivate User Portal Access")
                with st.form(key="deactivate_user_form", clear_on_submit=True):
                    deact_username = st.selectbox("Select User to Remove:", [u["username"] for u in all_users if u["username"] != current_username])
                    submit_deact = st.form_submit_button("Revoke Access", type="secondary")
                    if submit_deact:
                        user_repo.deactivate_user(deact_username)
                        st.success(f"Access revoked for user '{deact_username}'.")
                        audit_repo = AuditLogRepository(DEFAULT_DB_PATH)
                        audit_repo.log_event(current_username, "DEACTIVATE_USER", f"Revoked portal access for user '{deact_username}'.")
                        st.rerun()

        with admin_tabs[2]:
            st.markdown("### Deterministic Match Threshold Configurations")
            st.markdown("Adjust routing bands dynamically. Changing these parameters immediately alters machine decision status routing for future calculations.")
            config_repo = ConfigRepository(DEFAULT_DB_PATH)
            
            current_approved = config_repo.get_value("approved_threshold", 95.0)
            current_review = config_repo.get_value("review_threshold", 80.0)
            
            with st.form(key="config_form"):
                approved_val = st.slider("Auto-Approve Threshold (Score >= ):", min_value=50.0, max_value=100.0, value=current_approved, step=1.0)
                review_val = st.slider("Under-Review Threshold (Score >= ):", min_value=30.0, max_value=99.0, value=current_review, step=1.0)
                
                if review_val >= approved_val:
                    st.warning("Warning: Under-Review threshold must be less than the Auto-Approve threshold.")
                    
                save_config = st.form_submit_button("Apply Configuration Changes")
                if save_config:
                    if review_val >= approved_val:
                        st.error("Configuration error: Under-Review threshold must be strictly less than the Auto-Approve threshold.")
                    else:
                        config_repo.set_value("approved_threshold", approved_val)
                        config_repo.set_value("review_threshold", review_val)
                        st.success("Reconciliation gate thresholds updated successfully!")
                        audit_repo = AuditLogRepository(DEFAULT_DB_PATH)
                        audit_repo.log_event(current_username, "UPDATE_CONFIG", f"Updated approved_threshold to {approved_val} and review_threshold to {review_val}.")
                        st.rerun()

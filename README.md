# 💼 Automated Invoice Matching Agent Prototype

An offline-capable Python prototype of an invoice-matching agent designed to reconcile finance records across disparate ERP systems. This system ingests invoices, purchase orders (POs), and receipts containing currency, quantity, and formatting inconsistencies, normalizes them into a unified base, runs a weighted matching/confidence scoring model, routes them to distinct approval states, and logs results in an auditable SQLite database.

> [!NOTE]
> **Deterministic Audit Trail Design**: To ensure strict compliance and auditability required in corporate finance, this system uses a deterministic, rule-based matching and orchestration engine (no external LLM API calls are required or executed).

---

## 🛠️ Installation & Setup

Ensure you have **Python 3.11** installed.

1. **Clone the repository** (or navigate to the directory):
   ```bash
   cd invoice-agent
   ```

2. **Create and activate a virtual environment** (recommended):
   ```bash
   # Windows (PowerShell)
   python -m venv venv
   .\venv\Scripts\Activate.ps1

   # macOS / Linux
   python -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

---

## 🧪 Running Automated Tests

A comprehensive unit test suite is provided in `tests/test_pipeline.py` to verify normalization rules, fuzzy logic thresholds, scoring limits, safety bands, and database interactions.

Run the test suite using `pytest`:
```bash
python -m pytest tests/test_pipeline.py
```

---

## 🖥️ Running the Streamlit Dashboard

To launch the interactive ledger dashboard and visual audit logs:
```bash
streamlit run ui/streamlit_app.py
```
This starts the local web server and opens the dashboard in your default browser (typically at `http://localhost:8501`).

---

## 🏗️ Architecture & Component Logic

### 1. Ingestion & Schemas (`app/schema.py`)
Type safety and validation are enforced using **Pydantic v2** models:
* `Invoice` / `PurchaseOrder` / `Receipt`: Raw record validation models.
* `NormalizedRecord`: The uniform record output format after cleaning.
* `MatchResult`: The final audit log object.

### 2. Normalization Engine (`app/tools/normalize.py`)
* Cleans and strips currency symbols (`$`, `€`, `INR`).
* Standardizes numeric representations (e.g. converting European decimal comma `500,00` to `500.00`).
* Standardizes dates into ISO formats (`YYYY-MM-DD`).
* Converts all non-base currencies (USD, EUR) to **INR** using static exchange rates configured in `data/fx_rates.json`.

### 3. Matching Fallback (`app/tools/match.py`)
* First attempts an exact match using the PO reference number.
* Falls back to a fuzzy vendor-name comparison using **RapidFuzz** (`fuzz.WRatio`) with a matching threshold of **80%** to find the closest candidate.

### 4. Confidence Scorer (`app/tools/confidence.py`)
Matches are scored out of **100 points** using weighted heuristics:
1. **Amount Delta** (Weight: 40%): Deducts points linearly based on discrepancy. A difference greater than 15% drops the amount score component to 0.
2. **Vendor Name Similarity** (Weight: 25%): Fuzzy matching ratio.
3. **Date Plausibility** (Weight: 15%): Validates that the invoice date is on or after the purchase order date.
4. **Quantity Match** (Weight: 20%): Exact match if quantity is present; defaults to match if quantity is omitted in either system.

### 5. Threshold Router (`app/tools/router.py`)
Decisions are routed dynamically into three bands using constants defined at the top of the file:
* **`auto_approved`** (Confidence $\ge$ 95)
* **`needs_human_review`** ($80 \le$ Confidence $<$ 95)
* **`escalated`** (Confidence $<$ 80)

### 6. Audit Logging (`app/audit.py`)
Every decision run is saved to a local SQLite database (`data/decisions.db`). The ledger displays historic records and updates live when the "Reprocess Pipeline" button is clicked.

---

## 📊 Seeded Data Scenarios

The synthetic dataset (`data/`) contains 5 test scenarios:
1. **INV-001** (Exact Match): Reconciled perfectly, leading to `auto_approved` status.
2. **INV-002** (Clean Match - EUR): Exact match after currency conversion, resulting in `auto_approved` status.
3. **INV-003** (Currency Format & Minor Amount Mismatch): Integrates format discrepancies (`1,250.00 USD` vs `$1,200.00` on the PO) causing a 4.17% discrepancy, routing to `needs_human_review`.
4. **INV-004** (Amount Mismatch > 10%): High discrepancy (1,500 EUR vs 800 EUR), routing to `escalated`.
5. **INV-005** (Missing PO): No purchase order reference found, routing to `escalated`.

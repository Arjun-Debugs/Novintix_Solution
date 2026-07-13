# 💼 AI-Powered Invoice Matching & Reconciliation System

🔗 **Live Hosted URL**: [https://invoice-reconciliation-ledger-dbpb.onrender.com](https://invoice-reconciliation-ledger-dbpb.onrender.com)

Welcome to the Invoice Matching & Reconciliation repository. This project showcases two distinct evolutions of an automated financial reconciliation platform designed to match invoices with purchase orders (POs) and receipts across disparate ERP systems.

This repository contains:
1.  **V1 Minimal Prototype** (`v1-minimal-prototype/`): A lightweight, rule-based matching engine with a basic offline Streamlit ledger.
2.  **V2 Advanced Enterprise Governance Portal** (`v2-advanced-governance/`): A production-ready web portal featuring multi-role access controls, persistent relational databases, a hybrid machine learning scoring model (XGBoost), human override dispute workflows, and plain-English narrative explainability powered by Groq Llama 3 AI.

---

## ⚖️ Platform Feature Comparison

| Feature | V1 Minimal Prototype (`v1-minimal-prototype`) | V2 Advanced Governance (`v2-advanced-governance`) |
| :--- | :--- | :--- |
| **Logic Engine** | Purely deterministic rules & heuristics | Hybrid: Rules + Machine Learning (XGBoost) |
| **Database Persistence** | Stateless (re-read & reset on reload) | SQLite & Turso (LibSQL) Cloud Persistent Repositories |
| **Human Governance** | Basic status labels | Form-based manual overrides, audits, and disputes |
| **User Access Control** | None (public dashboard) | Secure login system with Admin, Reviewer, and Guest roles |
| **Admin Control Center** | None | Separate tab to register new users, revoke access, and view audit trail logs |
| **AI Explainability** | None | Simple, plain-English matching reports via Groq AI |
| **Cloud-Native Deployment** | Local Streamlit only | Containerized (Dockerfile & Docker Compose) and Render-ready |

---

## 📂 Directory Layout

```text
Novintix_Solution-main/
├── v1-minimal-prototype/        # Offline rule-based prototype
│   ├── app/                    # Matching and normalization engines
│   ├── data/                   # Seed JSON files
│   ├── tests/                  # Pytest unit tests
│   └── ui/                     # Local Streamlit ledger UI
│
├── v2-advanced-governance/      # Production-ready persistent portal
│   ├── app/                    # Models, repositories, router, and Groq integration
│   ├── data/                   # Relational database and seed data
│   ├── tests/                  # End-to-end integration and pipeline tests
│   ├── ui/                     # Enterprise multi-role portal UI
│   ├── Dockerfile              # Docker container definition
│   ├── docker-compose.yml      # Multi-service run config
│   └── render.yaml             # Render.com blueprint deployment config
│
└── render.yaml                 # Monorepo auto-detection deployment file
```

---

## 🛠️ V1 Minimal Prototype: Local Run

### 1. Installation
Navigate to the V1 folder and set up a virtual environment:
```bash
cd v1-minimal-prototype
python -m venv venv
# On Windows:
.\venv\Scripts\Activate.ps1
# On macOS/Linux:
source venv/bin/activate
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Run V1 Dashboard
```bash
streamlit run ui/streamlit_app.py
```
View the dashboard at `http://localhost:8501`.

---

## 🛡️ V2 Advanced Governance Portal: Local Run

### 1. Installation & Environment Configuration
Navigate to the V2 folder:
```bash
cd v2-advanced-governance
python -m venv venv
# On Windows:
.\venv\Scripts\Activate.ps1
# On macOS/Linux:
source venv/bin/activate
```
Install the full library requirements:
```bash
pip install -r requirements.txt
```

Create a `.env` file inside the `v2-advanced-governance/` directory and configure the environment variables:
```env
# Groq API Configuration for AI Explainability
GROQ_API_KEY=gsk_yourGroqApiKeyGoesHere

# JWT Signature Secret (Choose a secure random string)
JWT_SECRET=supersecretjwtsigningkey12345!

# Optional: Cloud DB Connection details (Leave unset to use local SQLite data/decisions.db file)
# LIBSQL_URL=libsql://your-turso-database-url
# LIBSQL_AUTH_TOKEN=your-turso-auth-token
```

### 2. Launching V2 Portal
```bash
streamlit run ui/streamlit_app.py
```
Open `http://localhost:8501` to view the portal. 

### 3. User Login Credentials
To test different access roles, log in using the following credentials:
*   **Administrator**:
    *   Username: `admin` | Password: `admin123`
    *   *Access*: Register new users, revoke user access, view admin logs, and run shadow machine learning training.
*   **Reviewer (Auditor)**:
    *   Username: `reviewer` | Password: `reviewer123`
    *   *Access*: Submit human override approvals, reprocess matching, dispute auto-approvals, and run AI explanations.
*   **Guest (Viewer)**:
    *   Username: `viewer` | Password: `viewer123`
    *   *Access*: Read-only access to ledger and analytics.

---

## 🧪 Testing the Platforms

Each project includes a separate test suite. To run the automated validation tests, navigate to either `v1-minimal-prototype` or `v2-advanced-governance` and execute:
```bash
pytest
```

---

## ☁️ Deploying V2 to the Cloud

The V2 platform is designed to be hosted online with zero manual server configuration.

### Deployment Option A: Render.com
1. Connect your GitHub repository to Render.
2. Render will automatically detect the root-level `render.yaml` blueprint, compile the lightweight **Docker** container, expose port `8501`, and spin up the web app.
3. Configure your `GROQ_API_KEY` and `JWT_SECRET` variables inside your Render service dashboard.

### Deployment Option B: Streamlit Community Cloud
1. Create a new Streamlit Cloud application pointing to your repository.
2. Set the main file path to `v2-advanced-governance/ui/streamlit_app.py`.
3. In Streamlit Cloud's **Advanced settings**, set your secrets configuration matching your `.env` values.

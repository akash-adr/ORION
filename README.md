# Next-Generation Autonomous D2C Advertising Intelligence & Decision Engine

**Hackathon:** DataQuest 3.0  
**Project:** Autonomous D2C Advertising Intelligence & Decision Engine

An AI-native system that ingests ad spend (Meta, Google, Amazon, TikTok), sales, inventory, and SKU margin data, detects anomalies, diagnoses root causes, recommends budget reallocations, and learns from outcomes.

---

## 4 Core System Modules

1. **Ingest & Reconcile (`/ingest`):** Unified schema across ad platforms (Meta, Google, Amazon, TikTok), sales, inventory, and SKU margins.
2. **Diagnose & Reason (`/diagnose`):** Anomaly detection + root-cause reasoning across traffic, conversion, and unit economics.
3. **Decide (`/decide`):** Prioritized budget and campaign recommendations with confidence scores.
4. **Execute & Learn (`/learn`):** Simulated action execution + closed-loop outcome feedback.

---

## Tech Stack

- **Frontend:** Next.js (App Router, Turbopack), TypeScript, Tailwind CSS, shadcn/ui, framer-motion, recharts, @tanstack/react-query, lucide-react, axios.
- **Backend:** Python 3.11+ (FastAPI, Uvicorn, Pydantic, SQLAlchemy with SQLite, Pandas, NumPy, Scikit-learn, Statsmodels, SciPy, Faker, google-genai, Pytest).
- **Orchestration:** Root `npm run dev` running both frontend and backend concurrently.

---

## Folder Structure

```
d2c-ad-engine/
├── frontend/
│   ├── app/                  # Next.js App router (layout.tsx, page.tsx with API status check)
│   ├── components/ui/        # shadcn/ui components (button, card, badge, table, tabs, dialog, skeleton, tooltip)
│   ├── lib/                  # api.ts (Axios client using NEXT_PUBLIC_API_URL), utils.ts
│   └── .env.local            # NEXT_PUBLIC_API_URL=http://localhost:8000
├── backend/
│   ├── app/
│   │   ├── main.py           # FastAPI app, CORS for localhost:3000, GET /health
│   │   ├── core/config.py    # pydantic-settings reading .env
│   │   ├── db/               # database.py (SQLAlchemy engine & session), models.py (Base model)
│   │   ├── api/routes/       # Module routers: ingest.py, diagnose.py, decide.py, learn.py
│   │   ├── services/         # Service packages: ingestion/, diagnosis/, decision/, learning/
│   │   └── schemas/          # Pydantic schemas package
│   ├── data/                 # raw/ and processed/ directories
│   ├── scripts/              # generate_mock_data.py (synthetic data generation placeholder)
│   ├── tests/test_health.py  # Pytest for GET /health
│   ├── .env                  # Local backend environment
│   └── .env.example          # Environment variable template
├── package.json              # Concurrently dev script
└── README.md                 # Setup instructions & documentation
```

---

## Setup & Running

### 1. Prerequisites
- Node.js 18+ and npm
- Python 3.11+
- Git

### 2. Quick Start
From the project root:

```bash
# Start both frontend (port 3000) and backend (port 8000) concurrently
npm run dev
```

### 3. Service URLs
- **Frontend Web UI:** [http://localhost:3000](http://localhost:3000)
- **Backend API Docs (Swagger):** [http://localhost:8000/docs](http://localhost:8000/docs)
- **Backend API Alternative (ReDoc):** [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **Health Check Endpoint:** [http://localhost:8000/health](http://localhost:8000/health)

### 4. Running Backend Tests
From the `backend/` directory:
```bash
./.venv/bin/pytest
```

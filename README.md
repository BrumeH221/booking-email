# Booking Email NLP

Email automation with a real **NLP pipeline** (intent → extract → sentiment →
embedding → similarity → summary → status → manager review → final email).

Built to run **for free** on:
- Google Gemini 2.0 Flash / Groq Llama 3.3 (free tier)
- Google Cloud Run, Cloud Scheduler, Supabase, Google Sheets
- Streamlit Community Cloud (free hosting)

---

## Folder layout

```
Booking email NLP/
├── main.py                  ← worker entry (local + Cloud Run)
├── cloud_worker.py          ← Flask wrapper for Cloud Run
├── manager_app.py           ← Streamlit dashboard
├── analytics_app.py         ← LDA / PCA analytics dashboard
├── config.py                ← env loader + constants
├── README.md
├── .env.example, .env.gemini, .env.groq, .gitignore
├── credentials.json, token.json   (Gmail OAuth — gitignored)
├── data/                    ← SQLite local data
│
├── backend/                 ← all business logic
│   ├── __init__.py
│   ├── nlp_pipeline.py      ← 8 spec functions
│   ├── llm_client.py        ← Gemini / Groq REST wrappers
│   ├── text_cleaner.py      ← HTML / signature / quote stripper
│   ├── gmail_service.py     ← Gmail API
│   ├── auth_service.py      ← OAuth (disk for local, env for cloud)
│   ├── email_templates.py   ← outbound bodies
│   ├── email_parser.py      ← regex fallback parser
│   ├── database.py          ← unified DB facade
│   ├── db_sqlite.py         ← SQLite backend
│   ├── db_supabase.py       ← Supabase backend
│   └── sheets_mirror.py     ← optional Sheets sync
│
├── deploy/                  ← deployment artifacts
│   ├── Dockerfile
│   ├── .dockerignore
│   ├── requirements.txt          (local dev)
│   ├── requirements-cloud.txt    (slim Cloud Run image)
│   ├── requirements-nlp.txt      (heavy HF models, optional)
│   ├── supabase_schema.sql
│   └── deploy_cloud_run.sh
│
└── scripts/                 ← helper PowerShell wrappers
    ├── use-gemini.ps1
    ├── use-groq.ps1
    └── cleanup.ps1
```

---

## Quick start (local, SQLite, FREE)

Run all commands from project root.

```powershell
cd "E:\project\Booking email NLP"
python -m venv .venv
.venv\Scripts\Activate.ps1

# Install deps (requirements files now live under deploy/)
pip install -r deploy\requirements.txt
```

Grab a free Gemini key at https://aistudio.google.com/app/apikey and paste it
into `.env.gemini`:

```
GEMINI_API_KEY=AIzaSy...
```

Make sure `credentials.json` (Gmail OAuth) is at project root, then:

```powershell
# Process unread inbox once
.\scripts\use-gemini.ps1 python main.py

# Manager dashboard
.\scripts\use-gemini.ps1 streamlit run manager_app.py

# Analytics (LDA topics + PCA clusters)
.\scripts\use-gemini.ps1 streamlit run analytics_app.py
```

To use Groq instead: paste `GROQ_API_KEY` into `.env.groq` and swap
`use-gemini.ps1` → `use-groq.ps1`.

## Cleanup helper

```powershell
.\scripts\cleanup.ps1          # dry-run preview
.\scripts\cleanup.ps1 -Force   # actually delete __pycache__, *.pyc, etc.
```

## Cloud deploy

```powershell
# 1) Supabase: create project → run deploy\supabase_schema.sql in SQL editor

# 2) Store secrets in Google Secret Manager:
echo -n "your-gemini-key"     | gcloud secrets create GEMINI_API_KEY     --data-file=-
echo -n "https://xxxx.supabase.co" | gcloud secrets create SUPABASE_URL  --data-file=-
echo -n "your-service-role-key"    | gcloud secrets create SUPABASE_KEY  --data-file=-
cat token.json                | gcloud secrets create GMAIL_TOKEN_JSON   --data-file=-

# 3) Deploy from project root
bash deploy\deploy_cloud_run.sh

# 4) (Manual build alternative)
docker build -f deploy\Dockerfile -t booking-nlp .
```

Cloud Scheduler: hit `https://<service-url>/run` every 5 min with header
`x-worker-secret: <secret>`.

---

## Pipeline order (every email, in this order)

1. Gmail read → 2. `text_cleaner.clean_email_text` → 3. `classify_intent`
→ 4. (not_relevant → mark read, drop) → 5. `extract_booking_info`
→ 6. `classify_sentiment` → 7. `create_embedding` → 8. `find_similar_bookings`
(block duplicates from same sender) → 9. `summarise_email` → 10. status
decision (Need More Info / Pending) → 11. save to DB → 12. Sheets mirror
auto → 13. send ack email → 14–17. manager dashboard does the final action.

## Status values

`Pending` · `Need More Info` · `Not Relevant` · `Confirmed` · `Cancelled` ·
`Unavailable` · `Completed`

## Intent labels

`new_booking` · `reschedule_booking` · `cancel_booking` · `price_enquiry` ·
`complaint` · `general_question` · `not_relevant`

## Booking detection rules

- **No subject filter** — AI judges intent from body alone.
- Only `preferred_date` AND `preferred_time` are required. `customer_email`
  is auto-filled from sender. `full_name`, `phone_number`, `service`,
  `location`, `symptom` are optional.
- If date or time missing → status `Need More Info`, customer gets a polite
  reply asking for those specifically.
- Newsletters / marketing / verification codes / cold-outreach are caught by
  a pre-LLM keyword rule list AND a strict LLM prompt. Such emails are
  **never** saved to DB and **never** auto-replied — only marked as read.
- Duplicate detection: cosine ≥ 0.92 from the same sender → save blocked.

## Security checklist

- `.gitignore` blocks `.env*`, `credentials.json`, `token.json`,
  `service_account.json`, `data/`, `__pycache__/`, `.venv/`.
- Cloud Run worker requires `x-worker-secret` header.
- All keys live in env / Secret Manager — never hard-coded.
- RLS enabled on Supabase tables; only the server-side `service_role` key
  bypasses it.

-- Run in Supabase SQL Editor once before deploying with DB_BACKEND=supabase.

-- Optional: enable pgvector for faster similarity search.
-- CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS bookings (
    id BIGSERIAL PRIMARY KEY,

    -- NLP outputs
    intent TEXT,
    intent_confidence DOUBLE PRECISION DEFAULT 0,
    sentiment TEXT,
    sentiment_confidence DOUBLE PRECISION DEFAULT 0,
    summary TEXT DEFAULT '',
    embedding JSONB,
    -- Or if pgvector enabled:
    -- embedding vector(768),

    -- Extracted booking fields
    full_name TEXT,
    phone_number TEXT,
    preferred_date TEXT,
    preferred_time TEXT,
    service TEXT,
    location TEXT,
    symptom TEXT,
    customer_email TEXT,
    additional_notes TEXT DEFAULT '',

    -- Workflow
    status TEXT NOT NULL DEFAULT 'Pending'
        CHECK (status IN ('Pending','Need More Info','Not Relevant',
                          'Confirmed','Cancelled','Unavailable','Completed')),
    manager_note TEXT DEFAULT '',

    -- Audit
    gmail_message_id TEXT UNIQUE,
    cleaned_body TEXT,
    created_at TEXT,
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_bookings_status ON bookings(status);
CREATE INDEX IF NOT EXISTS idx_bookings_intent ON bookings(intent);
CREATE INDEX IF NOT EXISTS idx_bookings_sentiment ON bookings(sentiment);
CREATE INDEX IF NOT EXISTS idx_bookings_customer_email ON bookings(customer_email);

CREATE TABLE IF NOT EXISTS processed_emails (
    gmail_message_id TEXT PRIMARY KEY,
    intent TEXT,
    sender_email TEXT,
    processed_at TEXT
);

ALTER TABLE bookings ENABLE ROW LEVEL SECURITY;
ALTER TABLE processed_emails ENABLE ROW LEVEL SECURITY;

# db_sqlite.py
import json
import os
import sqlite3
from datetime import datetime, timezone

import config
from backend.nlp_pipeline import _cosine


def _conn():
    os.makedirs(os.path.dirname(config.SQLITE_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(config.SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = _conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            intent TEXT,
            intent_confidence REAL,
            sentiment TEXT,
            sentiment_confidence REAL,
            summary TEXT,
            embedding_json TEXT,
            full_name TEXT,
            phone_number TEXT,
            preferred_date TEXT,
            preferred_time TEXT,
            service TEXT,
            location TEXT,
            symptom TEXT,
            customer_email TEXT,
            additional_notes TEXT,
            status TEXT,
            manager_note TEXT,
            gmail_message_id TEXT UNIQUE,
            cleaned_body TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS processed_emails (
            gmail_message_id TEXT PRIMARY KEY,
            intent TEXT,
            sender_email TEXT,
            processed_at TEXT
        )
    """)

    cur.execute("DROP VIEW IF EXISTS bookings_manager")

    cur.execute("""
        CREATE VIEW bookings_manager AS
        SELECT
            id, status, intent, sentiment,
            full_name AS customer_name,
            customer_email, phone_number,
            preferred_date, preferred_time,
            service, location, symptom,
            summary, manager_note,
            created_at, updated_at
        FROM bookings
        ORDER BY id DESC
    """)

    conn.commit()
    conn.close()


def save_booking(booking, gmail_message_id):
    now = _now()
    conn = _conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO bookings (
            intent, intent_confidence, sentiment, sentiment_confidence,
            summary, embedding_json,
            full_name, phone_number, preferred_date, preferred_time,
            service, location, symptom,
            customer_email, additional_notes,
            status, manager_note, gmail_message_id,
            cleaned_body, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        booking.get("intent"),
        booking.get("intent_confidence", 0.0),
        booking.get("sentiment"),
        booking.get("sentiment_confidence", 0.0),
        booking.get("summary") or "",
        json.dumps(booking.get("embedding") or []),
        booking.get("full_name"),
        booking.get("phone_number"),
        booking.get("preferred_date"),
        booking.get("preferred_time"),
        booking.get("service"),
        booking.get("location"),
        booking.get("symptom"),
        booking.get("customer_email"),
        booking.get("additional_notes") or "",
        booking.get("status") or config.STATUS_PENDING,
        "",
        gmail_message_id,
        booking.get("cleaned_body") or "",
        now, now,
    ))
    bid = cur.lastrowid
    conn.commit()
    conn.close()
    return bid


def update_booking_status(booking_id, status, manager_note=""):
    if status not in config.ALL_STATUSES:
        raise ValueError(f"Invalid status: {status}")
    conn = _conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE bookings SET status = ?, manager_note = ?, updated_at = ?
        WHERE id = ?
    """, (status, manager_note, _now(), booking_id))
    conn.commit()
    conn.close()


# Whitelist of columns that follow-up merges and other in-place patches
# are allowed to touch. Keeps the door closed to accidentally rewriting
# audit fields (id, created_at, embedding_json, gmail_message_id).
_PATCHABLE_FIELDS = {
    "status", "manager_note",
    "full_name", "phone_number",
    "preferred_date", "preferred_time",
    "service", "location", "symptom",
    "summary", "additional_notes", "customer_email",
    "sentiment", "intent",
}


def update_booking_fields(booking_id, fields):
    """
    Generic patch - used by the follow-up flow (main.py) to merge a
    customer's reply back into the original 'Need More Info' row instead
    of inserting a duplicate.
    """
    if not fields:
        return
    if "status" in fields and fields["status"] not in config.ALL_STATUSES:
        raise ValueError(f"Invalid status: {fields['status']}")
    sets, args = [], []
    for k, v in fields.items():
        if k not in _PATCHABLE_FIELDS:
            continue
        sets.append(f"{k} = ?")
        args.append(v)
    if not sets:
        return
    sets.append("updated_at = ?")
    args.append(_now())
    args.append(booking_id)
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        f"UPDATE bookings SET {', '.join(sets)} WHERE id = ?",
        args,
    )
    conn.commit()
    conn.close()


def find_open_need_info_booking(customer_email):
    """
    Return the most recent 'Need More Info' booking for this sender,
    or None. Used by the follow-up merge flow.
    """
    if not customer_email:
        return None
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM bookings "
        "WHERE LOWER(customer_email) = LOWER(?) AND status = ? "
        "ORDER BY id DESC LIMIT 1",
        (customer_email, config.STATUS_NEED_MORE_INFO),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_booking(booking_id):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_bookings_by_status(status):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM bookings WHERE status = ? ORDER BY id DESC", (status,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_all_bookings():
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM bookings ORDER BY id DESC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def is_email_processed(gmail_message_id):
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM processed_emails WHERE gmail_message_id = ?",
        (gmail_message_id,),
    )
    row = cur.fetchone()
    conn.close()
    return row is not None


def mark_email_processed(gmail_message_id, intent, sender_email):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT OR IGNORE INTO processed_emails (
            gmail_message_id, intent, sender_email, processed_at
        ) VALUES (?, ?, ?, ?)
    """, (gmail_message_id, intent, sender_email, _now()))
    conn.commit()
    conn.close()


def find_similar_bookings(embedding, threshold=None, limit=5):
    """Brute-force cosine search across stored embeddings."""
    if not embedding:
        return []
    if threshold is None:
        threshold = config.DUPLICATE_SIMILARITY_THRESHOLD
    conn = _conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, customer_email, intent, summary, embedding_json
        FROM bookings WHERE embedding_json IS NOT NULL AND embedding_json != '[]'
        ORDER BY id DESC LIMIT 500
    """)
    out = []
    for r in cur.fetchall():
        try:
            other = json.loads(r["embedding_json"])
        except Exception:
            continue
        score = _cosine(embedding, other)
        if score >= threshold:
            out.append({
                "id": r["id"],
                "customer_email": r["customer_email"],
                "intent": r["intent"],
                "summary": r["summary"],
                "score": score,
            })
    conn.close()
    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:limit]


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

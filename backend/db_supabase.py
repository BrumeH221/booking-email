# db_supabase.py
import json
from datetime import datetime, timezone

import config
from backend.nlp_pipeline import _cosine


_client = None


def _get():
    global _client
    if _client is not None:
        return _client
    try:
        from supabase import create_client
    except ImportError as e:
        raise RuntimeError("pip install supabase") from e
    if not config.SUPABASE_URL or not config.SUPABASE_KEY:
        raise RuntimeError("SUPABASE_URL / SUPABASE_KEY required")
    _client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
    return _client


def init_db():
    _get().table(config.SUPABASE_BOOKINGS_TABLE).select("id").limit(1).execute()


def save_booking(booking, gmail_message_id):
    now = _now()
    row = {
        # 1. Core booking info
        "status": booking.get("status") or config.STATUS_PENDING,
        "intent": booking.get("intent"),
        "customer_email": booking.get("customer_email"),
        "full_name": booking.get("full_name"),
        "phone_number": booking.get("phone_number"),

        # 2. Appointment details
        "preferred_date": booking.get("preferred_date"),
        "preferred_time": booking.get("preferred_time"),
        "service": booking.get("service"),
        "location": booking.get("location"),
        "symptom": booking.get("symptom"),

        # 3. AI summary / notes
        "summary": booking.get("summary") or "",
        "additional_notes": booking.get("additional_notes") or "",
        "manager_note": "",

        # 4. AI classification info
        "sentiment": booking.get("sentiment"),
        "sentiment_confidence": booking.get("sentiment_confidence", 0.0),
        "intent_confidence": booking.get("intent_confidence", 0.0),

        # 5. Source email data
        "gmail_message_id": gmail_message_id,
        "cleaned_body": booking.get("cleaned_body") or "",

        # 7. Timestamps
        "created_at": now,
        "updated_at": now,
    }
    resp = _get().table(config.SUPABASE_BOOKINGS_TABLE).insert(row).execute()
    if resp.data:
        return resp.data[0].get("id")
    return None


def update_booking_status(booking_id, status, manager_note=""):
    if status not in config.ALL_STATUSES:
        raise ValueError(f"Invalid status: {status}")
    _get().table(config.SUPABASE_BOOKINGS_TABLE).update({
        "status": status, "manager_note": manager_note, "updated_at": _now(),
    }).eq("id", booking_id).execute()


# Whitelist of columns that follow-up merges and other in-place patches
# are allowed to touch. Keeps the door closed to accidentally rewriting
# audit fields (id, created_at, gmail_message_id, embedding).
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
    of inserting a duplicate. Mirrors the SQLite implementation.
    """
    if not fields:
        return
    if "status" in fields and fields["status"] not in config.ALL_STATUSES:
        raise ValueError(f"Invalid status: {fields['status']}")
    payload = {k: v for k, v in fields.items() if k in _PATCHABLE_FIELDS}
    if not payload:
        return
    payload["updated_at"] = _now()
    _get().table(config.SUPABASE_BOOKINGS_TABLE).update(payload).eq(
        "id", booking_id
    ).execute()


def find_open_need_info_booking(customer_email):
    """
    Return the most recent 'Need More Info' booking for this sender,
    or None. Used by the follow-up merge flow.
    """
    if not customer_email:
        return None
    resp = (
        _get()
        .table(config.SUPABASE_BOOKINGS_TABLE)
        .select("*")
        .ilike("customer_email", customer_email)
        .eq("status", config.STATUS_NEED_MORE_INFO)
        .order("id", desc=True)
        .limit(1)
        .execute()
    )
    return resp.data[0] if resp.data else None


def get_booking(booking_id):
    resp = _get().table(config.SUPABASE_BOOKINGS_TABLE).select("*").eq(
        "id", booking_id
    ).limit(1).execute()
    return resp.data[0] if resp.data else None


def get_bookings_by_status(status):
    resp = _get().table(config.SUPABASE_BOOKINGS_TABLE).select("*").eq(
        "status", status
    ).order("id", desc=True).execute()
    return resp.data or []


def get_all_bookings():
    resp = _get().table(config.SUPABASE_BOOKINGS_TABLE).select("*").order(
        "id", desc=True
    ).execute()
    return resp.data or []


def is_email_processed(gmail_message_id):
    resp = _get().table(config.SUPABASE_PROCESSED_TABLE).select(
        "gmail_message_id"
    ).eq("gmail_message_id", gmail_message_id).limit(1).execute()
    return bool(resp.data)


def mark_email_processed(gmail_message_id, intent, sender_email):
    try:
        _get().table(config.SUPABASE_PROCESSED_TABLE).insert({
            "gmail_message_id": gmail_message_id,
            "intent": intent,
            "sender_email": sender_email,
            "processed_at": _now(),
        }).execute()
    except Exception as e:
        print(f"[db_supabase] mark_email_processed: {e}")


def find_similar_bookings(embedding, threshold=None, limit=5):
    """
    Supabase pgvector is ideal here but requires extension setup. Brute-force
    fallback works for small tables (< few thousand rows).
    """
    if not embedding:
        return []
    if threshold is None:
        threshold = config.DUPLICATE_SIMILARITY_THRESHOLD
    resp = _get().table(config.SUPABASE_BOOKINGS_TABLE).select(
        "id, customer_email, intent, summary, embedding"
    ).order("id", desc=True).limit(500).execute()
    out = []
    for r in resp.data or []:
        other = r.get("embedding") or []
        if not other:
            continue
        score = _cosine(embedding, other)
        if score >= threshold:
            out.append({**r, "score": score})
    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:limit]


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

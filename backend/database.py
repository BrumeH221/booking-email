# database.py
#
# Unified DB facade. SQLite for local, Supabase for cloud.
# Same interface so the rest of the app stays backend-agnostic.

import config


def _backend():
    if config.DB_BACKEND == "supabase":
        from backend.db_supabase import (
            init_db, save_booking, update_booking_status,
            update_booking_fields, find_open_need_info_booking,
            get_booking, get_bookings_by_status, get_all_bookings,
            is_email_processed, mark_email_processed,
            find_similar_bookings,
        )
    else:
        from backend.db_sqlite import (
            init_db, save_booking, update_booking_status,
            update_booking_fields, find_open_need_info_booking,
            get_booking, get_bookings_by_status, get_all_bookings,
            is_email_processed, mark_email_processed,
            find_similar_bookings,
        )
    return locals()


def _mirror_sheets(_action, _booking_id=None):
    if not config.SHEETS_ENABLED:
        return
    try:
        from backend.sheets_mirror import sync_all_bookings
        sync_all_bookings(get_all_bookings())
    except Exception as e:
        print(f"[db] Sheets mirror failed: {e}")


def init_db():
    _backend()["init_db"]()


def save_booking(booking, gmail_message_id):
    bid = _backend()["save_booking"](booking, gmail_message_id)
    _mirror_sheets("save", bid)
    return bid


def update_booking_status(booking_id, status, manager_note=""):
    _backend()["update_booking_status"](booking_id, status, manager_note)
    _mirror_sheets("update", booking_id)


def update_booking_fields(booking_id, fields):
    """Patch arbitrary booking fields (used by follow-up merge flow)."""
    _backend()["update_booking_fields"](booking_id, fields)
    _mirror_sheets("update", booking_id)


def find_open_need_info_booking(customer_email):
    """Most recent Need More Info row for this sender, or None."""
    return _backend()["find_open_need_info_booking"](customer_email)


def get_booking(booking_id):
    return _backend()["get_booking"](booking_id)


def get_bookings_by_status(status):
    return _backend()["get_bookings_by_status"](status)


def get_all_bookings():
    return _backend()["get_all_bookings"]()


def is_email_processed(gmail_message_id):
    return _backend()["is_email_processed"](gmail_message_id)


def mark_email_processed(gmail_message_id, intent, sender_email):
    _backend()["mark_email_processed"](gmail_message_id, intent, sender_email)


def find_similar_bookings(embedding, threshold=None, limit=5):
    """Return list of bookings whose embedding is similar to the given one."""
    return _backend()["find_similar_bookings"](embedding, threshold, limit)

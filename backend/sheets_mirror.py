# sheets_mirror.py
import json
import os
import config

_gc = None


def _client():
    global _gc
    if _gc is not None:
        return _gc
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError as e:
        raise RuntimeError("pip install gspread google-auth") from e

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    sa_json = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if sa_json:
        creds = Credentials.from_service_account_info(json.loads(sa_json), scopes=scopes)
    else:
        sa_path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_PATH", "service_account.json")
        if not os.path.exists(sa_path):
            raise RuntimeError(f"Service account JSON not found: {sa_path}")
        creds = Credentials.from_service_account_file(sa_path, scopes=scopes)
    _gc = gspread.authorize(creds)
    return _gc


COLUMNS = [
    "id",
    "status",
    "intent",
    "sentiment",
    "full_name",
    "customer_email",
    "phone_number",
    "preferred_date",
    "preferred_time",
    "service",
    "location",
    "symptom",
    "summary",
    "manager_note",
    "created_at",
    "updated_at",
]


def sync_all_bookings(bookings):
    if not config.SHEETS_ENABLED:
        return
    gc = _client()
    sh = gc.open_by_key(config.SHEETS_SPREADSHEET_ID)
    try:
        ws = sh.worksheet(config.SHEETS_WORKSHEET_NAME)
    except Exception:
        ws = sh.add_worksheet(
            title=config.SHEETS_WORKSHEET_NAME,
            rows=max(100, len(bookings) + 10),
            cols=len(COLUMNS),
        )
    rows = [COLUMNS]
    for b in bookings:
        rows.append([str(b.get(c) if b.get(c) is not None else "") for c in COLUMNS])
    ws.clear()
    ws.update(values=rows, range_name="A1")

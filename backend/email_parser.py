# email_parser.py — kept for backward compat. Production path is
# backend/nlp_pipeline.py extract_booking_info().

import re


def extract_field(text, name):
    m = re.search(rf"{name}:\s*(.+)", text, re.IGNORECASE)
    return m.group(1).strip() if m else None


def parse_booking_email(body):
    booking = {
        "full_name": extract_field(body, "Full name"),
        "preferred_date": extract_field(body, "Preferred date"),
        "preferred_time": extract_field(body, "Preferred time"),
        "phone_number": extract_field(body, "Phone number"),
        "customer_email": extract_field(body, "Email"),
        "service": extract_field(body, "Service"),
        "additional_notes": extract_field(body, "Additional notes"),
    }
    required = ["preferred_date", "preferred_time"]
    missing = [k for k in required if not booking.get(k)]
    booking["missing_fields"] = missing
    booking["is_valid"] = not missing
    return booking

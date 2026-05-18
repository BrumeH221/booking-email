# email_templates.py
#
# Outbound email bodies. Tone is adjusted by sentiment when relevant
# (angry/urgent → more apologetic / urgent tone).

import config


def _signature():
    return f"Kind regards,\n{config.BUSINESS_NAME}"


def _name(b):
    return b.get("full_name") or "there"


def _details(b):
    parts = []
    if b.get("service"):        parts.append(f"Service: {b['service']}")
    if b.get("preferred_date"): parts.append(f"Date: {b['preferred_date']}")
    if b.get("preferred_time"): parts.append(f"Time: {b['preferred_time']}")
    if b.get("phone_number"):   parts.append(f"Phone: {b['phone_number']}")
    if b.get("location"):       parts.append(f"Location: {b['location']}")
    return "\n".join(parts) or "(no details captured)"


def _opener(sentiment):
    if sentiment == config.SENTIMENT_ANGRY:
        return "We're sorry for any frustration you're experiencing."
    if sentiment == config.SENTIMENT_URGENT:
        return "Thanks for your urgent message — we're prioritising your request."
    return "Thanks for getting in touch."


# ----- New booking flow -----

def received(booking):
    subject = "Booking request received"
    body = (
        f"Hi {_name(booking)},\n\n"
        f"{_opener(booking.get('sentiment'))} "
        "We've received your booking request and our team will review it shortly.\n\n"
        f"What we captured:\n\n{_details(booking)}\n\n"
        "We'll email you again once your booking has been confirmed.\n\n"
        f"{_signature()}\n"
    )
    return subject, body


def need_more_info(booking, missing_fields):
    subject = "We need a few details to confirm your booking"
    missing_text = "\n".join(f"- {f.replace('_',' ').title()}" for f in missing_fields)
    body = (
        f"Hi {_name(booking)},\n\n"
        f"{_opener(booking.get('sentiment'))} "
        "We started processing your booking but need a little more information "
        "before we can confirm:\n\n"
        f"{missing_text}\n\n"
        "Just reply to this email with those details and we'll take it from there.\n\n"
        f"{_signature()}\n"
    )
    return subject, body


def confirmed(booking):
    subject = "Booking confirmed"
    body = (
        f"Hi {_name(booking)},\n\n"
        "Good news — your booking has been confirmed.\n\n"
        f"{_details(booking)}\n\n"
        "We look forward to seeing you.\n\n"
        f"{_signature()}\n"
    )
    return subject, body


def cancelled(booking, manager_note=""):
    reason = manager_note or "The requested appointment could not be confirmed."
    subject = "Booking cancelled"
    body = (
        f"Hi {_name(booking)},\n\n"
        "Unfortunately, we are unable to proceed with this booking.\n\n"
        f"{_details(booking)}\n\n"
        f"Reason:\n{reason}\n\n"
        "Please reply with another preferred date and time if you'd like to "
        "try again.\n\n"
        f"{_signature()}\n"
    )
    return subject, body


def unavailable(booking, manager_note=""):
    reason = manager_note or "That slot is unavailable."
    subject = "Slot unavailable"
    body = (
        f"Hi {_name(booking)},\n\n"
        "The slot you requested is currently unavailable.\n\n"
        f"{_details(booking)}\n\n"
        f"Note:\n{reason}\n\n"
        "Please reply with another preferred date and time.\n\n"
        f"{_signature()}\n"
    )
    return subject, body


def completed(booking):
    subject = "Thanks for visiting"
    body = (
        f"Hi {_name(booking)},\n\n"
        "Thanks for choosing us. Your appointment has been marked as completed:\n\n"
        f"{_details(booking)}\n\n"
        "If you have a moment, just reply with feedback — we'd love to hear it.\n\n"
        f"{_signature()}\n"
    )
    return subject, body


# ----- Other intents -----

def cancel_acknowledged():
    return ("Cancellation request received",
            "Hi,\n\nWe've received your cancellation request and a team "
            "member will get back to you shortly.\n\n" + _signature() + "\n")


def reschedule_acknowledged():
    return ("Reschedule request received",
            "Hi,\n\nWe've received your reschedule request and a team "
            "member will be in touch with new slot options.\n\n" + _signature() + "\n")


def question_acknowledged():
    return ("We received your message",
            "Hi,\n\nThanks for getting in touch. A team member will reply "
            "as soon as possible.\n\n" + _signature() + "\n")


def price_acknowledged():
    return ("We received your enquiry",
            "Hi,\n\nThanks for asking about our pricing. A team member "
            "will follow up with details shortly.\n\n" + _signature() + "\n")


def complaint_acknowledged():
    return ("We're sorry — your feedback has been received",
            "Hi,\n\nThank you for letting us know. We take your feedback "
            "seriously and a senior team member will be in touch shortly "
            "to resolve this with you.\n\n" + _signature() + "\n")


# ----- Status-change router -----

def for_status_change(status, booking, manager_note=""):
    if status == config.STATUS_CONFIRMED:   return confirmed(booking)
    if status == config.STATUS_CANCELLED:   return cancelled(booking, manager_note)
    if status == config.STATUS_UNAVAILABLE: return unavailable(booking, manager_note)
    if status == config.STATUS_COMPLETED:   return completed(booking)
    if status == config.STATUS_NEED_MORE_INFO:
        missing = booking.get("missing_fields") or []
        if not missing:
            missing = [
                f for f in config.REQUIRED_BOOKING_FIELDS
                if not booking.get(f)
            ]
        return need_more_info(booking, missing)
    return None

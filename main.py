# main.py
#
# Worker entrypoint. Implements the 17-step pipeline from the spec:
#
#   1. Gmail API reads new emails
#   2. Clean email text
#   2b. FOLLOW-UP MERGE: if the sender already has a "Need More Info"
#       booking, patch that row instead of inserting a new one.
#   3. Intent classification         -> not_relevant?  - save & stop
#   4. (skip)
#   5. Information extraction        <- booking intents only
#   6. Sentiment analysis
#   7. Embedding / vectorisation
#   8. Similarity / duplicate check
#   9. Summary
#  10. Booking status decision (Need More Info / Pending / Not Relevant)
#  11. Save to Supabase / SQLite
#  12. (Google Sheets mirror is auto-triggered by save_booking / update)
#  13. Send acknowledgement email
#  14-17. Manager dashboard (handled by manager_app.py)
#
# Anti-duplicate via processed_emails table.
# No subject filter - AI judges intent from body.

import traceback

import config
from backend import database as db
from backend.gmail_service import (
    search_unread_booking_emails,
    get_email_detail,
    send_email,
    mark_email_as_read,
)
from backend.text_cleaner import clean_email_text
from backend.nlp_pipeline import (
    classify_intent,
    extract_booking_info,
    classify_sentiment,
    create_embedding,
    summarise_email,
)
from backend import email_templates as templates


def process_booking_emails():
    db.init_db()

    emails = search_unread_booking_emails()
    if not emails:
        print("No new unread emails.")
        return {"found": 0, "processed": 0, "followup_merged": 0,
                "skipped_duplicate": 0, "not_relevant": 0, "errors": 0}

    print(f"Found {len(emails)} unread email(s).")
    summary = {"found": len(emails), "processed": 0, "followup_merged": 0,
               "skipped_duplicate": 0, "not_relevant": 0, "errors": 0}

    for email in emails:
        mid = email["id"]
        if db.is_email_processed(mid):
            print(f"[skip] already processed: {mid}")
            try: mark_email_as_read(mid)
            except Exception: pass
            summary["skipped_duplicate"] += 1
            continue

        try:
            result = _process_one_email(mid)
            if result == "not_relevant":
                summary["not_relevant"] += 1
            elif result == "skipped_duplicate":
                summary["skipped_duplicate"] += 1
            elif result == "followup_merged":
                summary["followup_merged"] += 1
            else:
                summary["processed"] += 1
        except Exception as e:
            print(f"[error] {mid}: {e}")
            traceback.print_exc()
            summary["errors"] += 1

    print(f"Summary: {summary}")
    return summary


def _process_one_email(message_id):
    # ---- 1) Read email ----
    detail = get_email_detail(message_id)
    print("=" * 70)
    print(f"From: {detail['sender_email']}  Subject: {detail['subject']!r}")

    # ---- 2) Clean text ----
    cleaned = clean_email_text(detail["body"])
    print(f"[2] cleaned text: {len(cleaned)} chars")

    # ---- 2b) FOLLOW-UP MERGE ----
    # If this sender already has a 'Need More Info' booking sitting in the
    # DB, treat this email as the customer supplying the missing piece(s).
    # We patch the existing row in-place (SQLite/Supabase) and the sheets
    # mirror is re-synced from inside db.update_booking_fields - so the
    # manager dashboard, Google Sheet and Supabase all stay in lockstep
    # without ever creating a duplicate row.
    open_booking = db.find_open_need_info_booking(detail["sender_email"])
    if open_booking:
        merged = _try_merge_followup(message_id, detail, cleaned, open_booking)
        if merged:
            return "followup_merged"
        # else: nothing useful in this reply - fall through to the normal
        # pipeline so it can still be classified / saved as a fresh email.

    # ---- 3) Intent classification ----
    intent_result = classify_intent(cleaned)
    intent = intent_result["intent"]
    print(f"[3] intent: {intent} (conf={intent_result['confidence']:.2f})")
    print(f"    reasoning: {intent_result.get('reasoning', '')}")

    # ---- 4) Not relevant short-circuit ----
    if intent == config.INTENT_NOT_RELEVANT:
        mark_email_as_read(message_id)
        print("    -> not relevant: marked as read, no DB write, no reply.")
        return "not_relevant"

    # ---- 5) Information extraction ----
    info = extract_booking_info(cleaned, sender_email=detail["sender_email"])
    print(f"[5] extracted: date={info.get('preferred_date')} "
          f"time={info.get('preferred_time')} "
          f"missing={info.get('missing_fields')}")

    # ---- 6) Sentiment ----
    sent = classify_sentiment(cleaned)
    print(f"[6] sentiment: {sent['sentiment']} (conf={sent['confidence']:.2f})")

    # ---- 7) Embedding ----
    embedding = create_embedding(cleaned[:4000])
    print(f"[7] embedding dim: {len(embedding)}")

    # ---- 8) Similarity / duplicate check ----
    similar = db.find_similar_bookings(embedding) if embedding else []
    if similar and similar[0]["score"] >= config.DUPLICATE_BLOCK_THRESHOLD:
        dup = similar[0]
        same_sender = (dup.get("customer_email") or "").lower() == \
                       (detail["sender_email"] or "").lower()
        if same_sender:
            mark_email_as_read(message_id)
            print(f"[8] DUPLICATE BLOCKED - matches booking #{dup['id']} "
                  f"from same sender (score={dup['score']:.3f}). "
                  f"No DB write, no reply.")
            return "skipped_duplicate"
        print(f"[8] near-duplicate of #{dup['id']} (different sender, "
              f"score={dup['score']:.3f}) - still processing")
    elif similar:
        print(f"[8] {len(similar)} similar prior booking(s); "
              f"top score={similar[0]['score']:.3f}")
    else:
        print("[8] no similar prior bookings")

    # ---- 9) Summary ----
    summary_text = summarise_email(cleaned)
    print(f"[9] summary: {summary_text}")

    # ---- 10) Status decision ----
    status = _decide_status(intent, info)
    print(f"[10] status decision: {status}")

    # ---- 11) Build booking record & save ----
    record = {
        "intent": intent,
        "intent_confidence": intent_result["confidence"],
        "sentiment": sent["sentiment"],
        "sentiment_confidence": sent["confidence"],
        "summary": summary_text,
        "embedding": embedding,
        "full_name": info.get("full_name"),
        "phone_number": info.get("phone_number"),
        "preferred_date": info.get("preferred_date"),
        "preferred_time": info.get("preferred_time"),
        "service": info.get("service"),
        "location": info.get("location"),
        "symptom": info.get("symptom"),
        "customer_email": info.get("customer_email") or detail["sender_email"],
        "additional_notes": "",
        "missing_fields": info.get("missing_fields") or [],
        "cleaned_body": cleaned,
        "status": status,
    }
    bid = db.save_booking(record, gmail_message_id=message_id)
    print(f"[11] saved booking id={bid} status={status}")

    # ---- 13) Send acknowledgement email ----
    _send_ack_email(detail, record)

    db.mark_email_processed(message_id, intent, detail["sender_email"])
    mark_email_as_read(message_id)
    _notify_manager(record, detail)
    return "processed"


def _try_merge_followup(message_id, detail, cleaned, open_booking):
    """
    The sender has an existing 'Need More Info' booking. Try to extract
    the missing piece(s) from this reply and patch the original row.

    Returns True if the merge happened. Returns False if the reply
    contained nothing useful - caller should fall back to normal pipeline.
    """
    info = extract_booking_info(cleaned, sender_email=detail["sender_email"])

    # Only fill fields that were null on the original row - never
    # overwrite something the customer already gave us.
    patchable = ("preferred_date", "preferred_time", "full_name",
                 "phone_number", "service", "location", "symptom")
    patches = {}
    for f in patchable:
        if not open_booking.get(f) and info.get(f):
            patches[f] = info[f]

    if not patches:
        print(f"[merge] booking #{open_booking['id']} - reply had nothing new "
              f"to patch; falling through to normal flow")
        return False

    merged = {**open_booking, **patches}
    still_missing = [f for f in config.REQUIRED_BOOKING_FIELDS
                     if not merged.get(f)]
    new_status = (config.STATUS_PENDING if not still_missing
                  else config.STATUS_NEED_MORE_INFO)

    # Single write - flips status to Pending only when date+time are both
    # present. Anything else stays in Need More Info so we keep asking.
    db.update_booking_fields(
        open_booking["id"], {**patches, "status": new_status}
    )
    merged["status"] = new_status
    merged["missing_fields"] = still_missing
    print(f"[merge] booking #{open_booking['id']} patched "
          f"{list(patches.keys())} -> status={new_status}")

    # Send the right follow-up email
    customer = merged.get("customer_email") or detail["sender_email"]
    thread = detail.get("thread_id")
    if still_missing:
        subj, body = templates.need_more_info(merged, still_missing)
    else:
        subj, body = templates.followup_complete(merged)
    try:
        send_email(to=customer, subject=subj, body=body, thread_id=thread)
        print(f"[merge] follow-up email sent -> {customer}")
    except Exception as e:
        print(f"[merge] send_email failed: {e}")

    db.mark_email_processed(message_id, "follow_up", detail["sender_email"])
    mark_email_as_read(message_id)
    _notify_manager_followup(merged, detail, patches)
    return True


def _decide_status(intent, info):
    if intent == config.INTENT_NOT_RELEVANT:
        return config.STATUS_NOT_RELEVANT
    if intent in config.BOOKING_INTENTS:
        if info.get("missing_fields"):
            return config.STATUS_NEED_MORE_INFO
        return config.STATUS_PENDING
    return config.STATUS_PENDING


def _send_ack_email(detail, record):
    intent = record["intent"]
    customer = record["customer_email"]
    thread = detail.get("thread_id")

    if record["status"] == config.STATUS_NEED_MORE_INFO:
        subj, body = templates.need_more_info(record, record["missing_fields"])
    elif intent == config.INTENT_NEW_BOOKING:
        subj, body = templates.received(record)
    elif intent == config.INTENT_RESCHEDULE:
        subj, body = templates.reschedule_acknowledged()
    elif intent == config.INTENT_CANCEL:
        subj, body = templates.cancel_acknowledged()
    elif intent == config.INTENT_PRICE_ENQUIRY:
        subj, body = templates.price_acknowledged()
    elif intent == config.INTENT_COMPLAINT:
        subj, body = templates.complaint_acknowledged()
    elif intent == config.INTENT_GENERAL_QUESTION:
        subj, body = templates.question_acknowledged()
    else:
        return

    send_email(to=customer, subject=subj, body=body, thread_id=thread)
    print(f"[13] ack email sent -> {customer}")


def _notify_manager_followup(record, detail, patches):
    """Lightweight ping so the manager sees a 'Need Info -> Pending' flip."""
    if not config.MANAGER_NOTIFY_EMAIL:
        return
    try:
        send_email(
            to=config.MANAGER_NOTIFY_EMAIL,
            subject=f"[Booking System] Follow-up #{record['id']} -> {record['status']}",
            body=(
                f"Customer reply patched booking #{record['id']}.\n"
                f"New status: {record['status']}\n"
                f"From: {detail['sender_email']}\n\n"
                f"Newly supplied fields: {patches}\n\n"
                f"Date: {record.get('preferred_date')}\n"
                f"Time: {record.get('preferred_time')}\n"
                f"Service: {record.get('service')}\n"
                f"Location: {record.get('location')}\n"
                f"Phone: {record.get('phone_number')}\n"
            ),
        )
    except Exception as e:
        print(f"[warn] manager notify (followup) failed: {e}")


def _notify_manager(record, detail):
    if not config.MANAGER_NOTIFY_EMAIL:
        return
    try:
        send_email(
            to=config.MANAGER_NOTIFY_EMAIL,
            subject=f"[Booking System] {record['intent']} - {record.get('full_name') or detail['sender_email']}",
            body=(
                f"Intent: {record['intent']}\n"
                f"Sentiment: {record['sentiment']}\n"
                f"Status: {record['status']}\n"
                f"From: {detail['sender_email']}\n"
                f"Subject: {detail['subject']}\n\n"
                f"Summary: {record.get('summary')}\n\n"
                f"Date: {record.get('preferred_date')}\n"
                f"Time: {record.get('preferred_time')}\n"
                f"Service: {record.get('service')}\n"
                f"Location: {record.get('location')}\n"
                f"Phone: {record.get('phone_number')}\n"
            ),
        )
    except Exception as e:
        print(f"[warn] manager notify failed: {e}")


if __name__ == "__main__":
    config.validate_config_for_runtime()
    process_booking_emails()

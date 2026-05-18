# backend/nlp_pipeline.py
#
# Core NLP pipeline. Implements the 8 functions required by the spec:
#   classify_intent(text)
#   extract_booking_info(text)
#   classify_sentiment(text)
#   create_embedding(text)
#   calculate_similarity(text1, text2)
#   summarise_email(text)
#   run_topic_modelling(email_texts)
#   run_pca_visualisation(embeddings)
#
# Each function picks LLM API or local HuggingFace based on config:
#   USE_LLM_API=true         → Gemini / Groq for intent, extract, sentiment, summary, embed
#   USE_LOCAL_MODELS=true    → HuggingFace transformers for intent, sentiment, embedding
#
# When neither AI is available, falls back to a tiny regex parser so the
# system stays alive during outages.

import json
import math
from typing import Optional

import config
from backend import llm_client


# ===========================================================================
# 1) INTENT CLASSIFICATION
# ===========================================================================
#
# Spec output labels:
#   new_booking, reschedule_booking, cancel_booking, price_enquiry,
#   complaint, general_question, not_relevant

INTENT_LABELS = config.ALL_INTENTS  # see config.py


INTENT_SYSTEM_PROMPT = """You are an email intent classifier for a small \
booking business. Read the email and reply ONLY with a JSON object:
{
  "intent": "new_booking" | "reschedule_booking" | "cancel_booking" | "price_enquiry" | "complaint" | "general_question" | "not_relevant",
  "confidence": <float 0..1>,
  "reasoning": <one short sentence>
}

Rules:
- new_booking: customer is asking to BOOK an appointment (even without the word "book" — phrases like "I want an appointment", "can I come in tomorrow at 5pm", "đặt lịch", "I'd like to see the doctor" all count).
- reschedule_booking: customer wants to change date/time of an existing booking.
- cancel_booking: customer wants to cancel.
- price_enquiry: customer is asking how much a service costs.
- complaint: customer is unhappy about a previous service experience.
- general_question: customer asking a genuine question about THIS business (hours, location, services offered). The customer must be acting as a potential customer.
- not_relevant: ANY email that is NOT a real customer inquiry. This includes:
    * newsletters, weekly digests, company updates, blog posts
    * marketing, promotional offers, sales pitches
    * automated notifications (Google, Facebook, GitHub, banks, delivery)
    * password resets, verification codes, OAuth confirmations
    * cold outreach, sales prospecting, B2B sales
    * spam, phishing, scams
    * mass emails with "unsubscribe" links, "view in browser", "no-reply" senders
    * out-of-office auto-replies, calendar invitations
    * internal/system emails not from a customer

DEFAULT TO not_relevant when in doubt. Only classify as one of the other intents if the email is clearly from an individual person addressing this business directly. Ignore the email subject — judge from the body content.

Output JSON only. No markdown. No prose.
"""


# Hard signals that an email is definitely not_relevant — checked BEFORE the
# LLM call to save tokens and prevent misclassification.
NOT_RELEVANT_HARD_SIGNALS = [
    r"\bunsubscribe\b",
    r"\bview\s+(this\s+)?(email\s+)?in\s+(your\s+)?browser\b",
    r"\bno[-_\s]?reply\b",
    r"\bdo\s+not\s+reply\b",
    r"\bweekly\s+(newsletter|digest|update|recap|summary)\b",
    r"\bmonthly\s+(newsletter|digest|update|recap|summary)\b",
    r"\bnewsletter\b",
    r"\bcompany\s+updates?\b",
    r"\bnew\s+blog\s+post\b",
    r"\bpromotional?\s+offer\b",
    r"\blimited[\s-]?time\s+offer\b",
    r"\bsales?\s+pitch\b",
    r"\bverification\s+code\b",
    r"\byour\s+(?:OTP|verification|confirmation)\s+code\b",
    r"\bpassword\s+reset\b",
    r"\bsign\s+in\s+from\s+a?\s*new\s+device\b",
    r"\bsecurity\s+alert\b",
    r"\bautomated\s+(?:message|notification|email)\b",
    r"\bthis\s+is\s+an\s+automated\s+email\b",
    r"\bout\s+of\s+office\b",
    r"\bauto[\s-]?reply\b",
    r"\bcalendar\s+invitation\b",
    r"\bblack\s+friday\b",
    r"\bcyber\s+monday\b",
    r"\b\d{1,3}%\s+off\b",
]


def _hard_signal_not_relevant(text: str) -> Optional[dict]:
    """Cheap pre-LLM check. Returns a result dict if a hard signal matches."""
    import re
    if not text:
        return None
    lower = text.lower()
    for pat in NOT_RELEVANT_HARD_SIGNALS:
        m = re.search(pat, lower)
        if m:
            return {
                "intent": config.INTENT_NOT_RELEVANT,
                "confidence": 0.95,
                "reasoning": f"hard signal matched: {m.group(0)!r}",
            }
    return None


# Tiny but reliable signals that the email IS a real customer message —
# used to decide what to fall back to when LLM is unavailable.
BOOKING_HINTS = (
    "book", "appointment", "schedule", "available", "slot", "reservation",
    "đặt lịch", "đặt hẹn", "lịch hẹn", "khám", "tư vấn",
)


def classify_intent(text: str) -> dict:
    """Return {"intent": str, "confidence": float, "reasoning": str}."""
    if not text or not text.strip():
        return {"intent": config.INTENT_NOT_RELEVANT, "confidence": 1.0,
                "reasoning": "empty email"}

    # Cheap pre-filter: if obvious newsletter/marketing keywords are present,
    # short-circuit without paying for an LLM call.
    hard = _hard_signal_not_relevant(text)
    if hard:
        return hard

    if config.USE_LOCAL_MODELS and config.INTENT_MODEL_NAME:
        try:
            return _classify_intent_local(text)
        except Exception as e:
            print(f"[nlp] local intent model failed ({e}), fall back to LLM")

    if config.USE_LLM_API:
        try:
            data = llm_client.chat_json(INTENT_SYSTEM_PROMPT, text, max_tokens=200)
            intent = (data.get("intent") or "").lower().strip()
            if intent not in INTENT_LABELS:
                intent = config.INTENT_NOT_RELEVANT
            return {
                "intent": intent,
                "confidence": _clip01(data.get("confidence")),
                "reasoning": (data.get("reasoning") or "")[:200],
            }
        except Exception as e:
            print(f"[nlp] LLM intent call failed: {e}")

    # Heuristic last resort
    return _classify_intent_heuristic(text)


def _classify_intent_local(text: str) -> dict:
    """Zero-shot classification with HF (e.g. bart-large-mnli)."""
    from transformers import pipeline  # heavy import — lazy
    clf = _get_hf_pipeline("zero-shot-classification", config.INTENT_MODEL_NAME)
    result = clf(
        text[:1500],
        candidate_labels=INTENT_LABELS,
        hypothesis_template="This email is about {}.",
    )
    return {
        "intent": result["labels"][0],
        "confidence": float(result["scores"][0]),
        "reasoning": f"zero-shot top score {result['scores'][0]:.2f}",
    }


def _classify_intent_heuristic(text: str) -> dict:
    """
    Keyword-based fallback used when both LLM and HF are unavailable.
    DEFAULT IS not_relevant — we only classify as a real intent when there
    is positive evidence the email is from a customer about a booking.
    """
    t = text.lower()
    if any(w in t for w in ("cancel", "huy", "hủy")):
        return {"intent": config.INTENT_CANCEL, "confidence": 0.5,
                "reasoning": "keyword: cancel"}
    if any(w in t for w in ("reschedule", "change time", "move my", "dời", "đổi giờ")):
        return {"intent": config.INTENT_RESCHEDULE, "confidence": 0.5,
                "reasoning": "keyword: reschedule"}
    if any(w in t for w in BOOKING_HINTS):
        return {"intent": config.INTENT_NEW_BOOKING, "confidence": 0.5,
                "reasoning": "booking keyword present"}
    if any(w in t for w in ("price", "cost", "how much", "giá", "phí")):
        return {"intent": config.INTENT_PRICE_ENQUIRY, "confidence": 0.5,
                "reasoning": "keyword: price"}
    if any(w in t for w in ("complain", "terrible", "awful", "tệ", "phàn nàn")):
        return {"intent": config.INTENT_COMPLAINT, "confidence": 0.4,
                "reasoning": "keyword: complaint"}
    # Asking a real question? Require a question mark AND business context.
    if "?" in t and any(w in t for w in ("you", "your", "bạn", "shop", "store",
                                         "clinic", "office", "service")):
        return {"intent": config.INTENT_GENERAL_QUESTION, "confidence": 0.4,
                "reasoning": "question mark + business context"}
    return {"intent": config.INTENT_NOT_RELEVANT, "confidence": 0.6,
            "reasoning": "no booking/customer signal"}


# ===========================================================================
# 2) BOOKING INFORMATION EXTRACTION
# ===========================================================================
#
# Spec: extract customer_name, phone, date, time, service, location, symptom.
# Required (per business rules): date AND time. Everything else is optional.

EXTRACT_SYSTEM_PROMPT_TEMPLATE = """You are a structured data extractor for \
booking emails. Today is {today_full}. Reply ONLY with this JSON object \
(no prose, no markdown):

{{
  "full_name": <string or null>,
  "phone_number": <string or null>,
  "preferred_date": <string YYYY-MM-DD or null>,
  "preferred_time": <string HH:MM 24h or null>,
  "service": <string or null>,
  "location": <string or null>,
  "symptom": <string or null>
}}

Rules:
- Do NOT invent missing information. If a field is not in the email, use null.
- preferred_date: ALWAYS return YYYY-MM-DD.
    * SPECIFIC DATE WINS over weekday name. If the customer writes both, e.g.
      "Wednesday 23/7" or "Friday 25-08-2026", use the specific date (23/7 →
      2026-07-23 if 2026 is the current year and that date is in the future).
    * "23/7" / "23-7" / "23/7/2026"  → treat day-first then month (European).
       If no year, pick the current year if that date is still in the future,
       otherwise next year.
    * "July 23" / "23 July"          → same year logic.
    * "today"                        → {today_iso}
    * "tomorrow"                     → +1 day from today
    * "day after tomorrow"           → +2 days
    * "in N days"                    → today + N days
    * "next Monday/Tuesday/..."      → the next Monday/Tuesday/... STRICTLY after today
    * "this Friday"                  → the upcoming Friday (today if today is Friday)
    * Bare weekday ("Wednesday")     → the upcoming Wednesday (only if no specific date is given)
  Only return null if the email mentions no date at all.
- preferred_time: convert "3pm", "15h", "3:00 PM" → "15:00".
- phone_number: keep digits and leading +; remove spaces and dashes.
- service: short noun phrase ("consultation", "haircut", "dental cleaning", "nail").
- location: only if the customer specified one (e.g. "home visit at 123 Main St").
- symptom: only for medical/health bookings.
"""


def _build_extract_prompt() -> str:
    """Inject today's date so the LLM can resolve relative dates."""
    from datetime import datetime
    today = datetime.now()
    return EXTRACT_SYSTEM_PROMPT_TEMPLATE.format(
        today_full=today.strftime("%A, %d %B %Y"),
        today_iso=today.strftime("%Y-%m-%d"),
        today_weekday=today.strftime("%A"),
    )


def extract_booking_info(text: str, sender_email: Optional[str] = None) -> dict:
    """Extract booking fields. Returns a dict including missing_fields list."""

    extracted = {
        "full_name": None,
        "phone_number": None,
        "preferred_date": None,
        "preferred_time": None,
        "service": None,
        "location": None,
        "symptom": None,
    }

    if config.USE_LLM_API and text and text.strip():
        try:
            data = llm_client.chat_json(_build_extract_prompt(), text, max_tokens=400)
            for k in extracted:
                v = data.get(k)
                if isinstance(v, str):
                    v = v.strip() or None
                extracted[k] = v
        except Exception as e:
            print(f"[nlp] LLM extract failed: {e}, regex fallback")
            extracted.update(_extract_with_regex(text))
    else:
        extracted.update(_extract_with_regex(text))

    # Belt-and-suspenders. If the email contains a specific date like 23/7,
    # ALWAYS use that — even if the LLM returned a weekday-based date.
    abs_date = _parse_absolute_date(text)
    if abs_date:
        if extracted.get("preferred_date") != abs_date:
            print(f"[nlp] overriding LLM date {extracted.get('preferred_date')} "
                  f"with absolute date {abs_date} from body")
        extracted["preferred_date"] = abs_date
    elif not extracted.get("preferred_date"):
        d = _parse_relative_date(text)
        if d:
            extracted["preferred_date"] = d
            print(f"[nlp] relative-date fallback caught: {d}")

    if not extracted.get("preferred_time"):
        t = _parse_time(text)
        if t:
            extracted["preferred_time"] = t

    # Sender email is always known
    extracted["customer_email"] = sender_email

    # Determine missing fields (only date+time are mandatory per spec)
    missing = [f for f in config.REQUIRED_BOOKING_FIELDS if not extracted.get(f)]
    extracted["missing_fields"] = missing
    extracted["is_complete"] = len(missing) == 0
    return extracted


def _extract_with_regex(text: str) -> dict:
    """Last-resort extraction using simple regex. Catches obvious patterns."""
    import re

    result = {}

    # Absolute date wins over relative weekday ("Wednesday 23/7" → 23 July).
    d = _parse_absolute_date(text)
    if not d:
        d = _parse_relative_date(text)
    if d:
        result["preferred_date"] = d

    t = _parse_time(text)
    if t:
        result["preferred_time"] = t

    # Phone: any 8-15 digit sequence with optional + and spaces
    m = re.search(r"(\+?\d[\d\s\-\(\)]{7,15}\d)", text)
    if m:
        digits = re.sub(r"[^\d+]", "", m.group(1))
        if 8 <= len(digits.lstrip("+")) <= 15:
            result["phone_number"] = digits

    # Name: "Full name: X" or "My name is X" or "I am X"
    for p in [r"Full name:\s*([^\n]+)",
              r"My name is\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)",
              r"I am\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)"]:
        m = re.search(p, text)
        if m:
            result["full_name"] = m.group(1).strip()
            break

    return result


# ---------------------------------------------------------------------------
# Relative date + time parsers (used as LLM safety net)
# ---------------------------------------------------------------------------

_WEEKDAYS = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}


_MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2,
    "march": 3, "mar": 3, "april": 4, "apr": 4,
    "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}


def _pick_year(month: int, day: int):
    """Return YYYY-MM-DD assuming current year if future, else next year."""
    from datetime import datetime, date
    today = datetime.now().date()
    for y in (today.year, today.year + 1):
        try:
            cand = date(y, month, day)
            if cand >= today:
                return cand.isoformat()
        except ValueError:
            continue
    return None


def _parse_absolute_date(text: str):
    """
    Resolve absolute dates like "23/7", "23-7-2026", "2026-07-23",
    "July 23", "23 July 2026". Returns YYYY-MM-DD or None.
    DOES NOT match bare weekday names — that's _parse_relative_date's job.
    """
    import re
    from datetime import datetime, date

    if not text:
        return None
    today = datetime.now().date()

    # ISO YYYY-MM-DD or YYYY/MM/DD
    m = re.search(r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b", text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            pass

    # DD/MM/YYYY, DD-MM-YYYY (day-first, European)
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b", text)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        try:
            return date(y, mo, d).isoformat()
        except ValueError:
            pass

    # DD/MM or DD-MM (no year) — e.g. "23/7"
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})\b", text)
    if m:
        d, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            picked = _pick_year(mo, d)
            if picked:
                return picked

    # "Month DD" or "Month DD, YYYY" — e.g. "July 23, 2026"
    pattern = r"\b(" + "|".join(_MONTHS) + r")\s+(\d{1,2})(?:[a-z]{0,2})?(?:,?\s+(\d{4}))?\b"
    m = re.search(pattern, text, re.IGNORECASE)
    if m:
        mo = _MONTHS[m.group(1).lower()]
        d = int(m.group(2))
        if m.group(3):
            try:
                return date(int(m.group(3)), mo, d).isoformat()
            except ValueError:
                pass
        else:
            picked = _pick_year(mo, d)
            if picked:
                return picked

    # "DD Month" or "DD Month YYYY" — e.g. "23 July 2026"
    pattern = r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(" + "|".join(_MONTHS) + r")(?:,?\s+(\d{4}))?\b"
    m = re.search(pattern, text, re.IGNORECASE)
    if m:
        d = int(m.group(1))
        mo = _MONTHS[m.group(2).lower()]
        if m.group(3):
            try:
                return date(int(m.group(3)), mo, d).isoformat()
            except ValueError:
                pass
        else:
            picked = _pick_year(mo, d)
            if picked:
                return picked

    return None


def _parse_relative_date(text: str):
    """
    Resolve "next Wednesday", "tomorrow", "today", "in 3 days", "this Friday",
    "Wed" etc. into a YYYY-MM-DD string using today's date as reference.
    Returns None if nothing matches.
    """
    import re
    from datetime import datetime, timedelta

    if not text:
        return None
    today = datetime.now().date()
    t = text.lower()

    # "today"
    if re.search(r"\btoday\b", t):
        return today.isoformat()
    # "tomorrow"
    if re.search(r"\btomorrow\b", t):
        return (today + timedelta(days=1)).isoformat()
    # "day after tomorrow"
    if re.search(r"\bday\s+after\s+tomorrow\b", t):
        return (today + timedelta(days=2)).isoformat()
    # "in N days"
    m = re.search(r"\bin\s+(\d{1,3})\s+days?\b", t)
    if m:
        return (today + timedelta(days=int(m.group(1)))).isoformat()

    # "next <weekday>"  → strictly after today
    m = re.search(r"\bnext\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|tues|wed|thu|thurs|fri|sat|sun)\b", t)
    if m:
        target = _WEEKDAYS[m.group(1)]
        delta = (target - today.weekday()) % 7
        delta = delta or 7  # "next" must be strictly after today
        return (today + timedelta(days=delta)).isoformat()

    # "this <weekday>"  → upcoming, today counts
    m = re.search(r"\bthis\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|tues|wed|thu|thurs|fri|sat|sun)\b", t)
    if m:
        target = _WEEKDAYS[m.group(1)]
        delta = (target - today.weekday()) % 7
        return (today + timedelta(days=delta)).isoformat()

    # Bare "<weekday>"  → assume upcoming
    m = re.search(r"\b(on\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", t)
    if m:
        target = _WEEKDAYS[m.group(2)]
        delta = (target - today.weekday()) % 7
        delta = delta or 7
        return (today + timedelta(days=delta)).isoformat()

    return None


def _parse_time(text: str):
    """Extract a clock time and normalise to HH:MM 24h."""
    import re

    if not text:
        return None

    # 3pm, 3 pm, 3:30pm
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", text, re.IGNORECASE)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        ampm = m.group(3).lower()
        if ampm == "pm" and hour < 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"

    # 15h, 15h30
    m = re.search(r"\b(\d{1,2})h(\d{2})?\b", text)
    if m:
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"

    # 15:00, 3:00
    m = re.search(r"\b(\d{1,2}):(\d{2})\b", text)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"

    return None


# ===========================================================================
# 3) SENTIMENT ANALYSIS
# ===========================================================================

SENTIMENT_SYSTEM_PROMPT = """Classify the emotional tone of this email. Reply ONLY with JSON:
{"sentiment": "positive" | "neutral" | "negative" | "angry" | "urgent", "confidence": <float 0..1>}

- positive: friendly, grateful
- neutral: matter-of-fact, polite request
- negative: disappointed, unhappy but calm
- angry: clearly hostile, ALL CAPS, profanity, threats
- urgent: time-pressured, asking for ASAP service, emergency
"""


def classify_sentiment(text: str) -> dict:
    if not text or not text.strip():
        return {"sentiment": config.SENTIMENT_NEUTRAL, "confidence": 1.0}

    if config.USE_LOCAL_MODELS and config.SENTIMENT_MODEL_NAME:
        try:
            return _classify_sentiment_local(text)
        except Exception as e:
            print(f"[nlp] local sentiment failed ({e}), fall back to LLM")

    if config.USE_LLM_API:
        try:
            data = llm_client.chat_json(SENTIMENT_SYSTEM_PROMPT, text, max_tokens=80)
            sentiment = (data.get("sentiment") or "").lower().strip()
            if sentiment not in config.ALL_SENTIMENTS:
                sentiment = config.SENTIMENT_NEUTRAL
            return {"sentiment": sentiment, "confidence": _clip01(data.get("confidence"))}
        except Exception as e:
            print(f"[nlp] LLM sentiment failed: {e}")

    # Heuristic
    return _classify_sentiment_heuristic(text)


def _classify_sentiment_local(text: str) -> dict:
    """HF RoBERTa sentiment model — typically returns 3 classes."""
    from transformers import pipeline
    clf = _get_hf_pipeline("sentiment-analysis", config.SENTIMENT_MODEL_NAME)
    out = clf(text[:512])[0]
    label = out["label"].lower()
    # Map twitter-roberta labels (LABEL_0/1/2 or negative/neutral/positive)
    if "neg" in label or label == "label_0":
        mapped = config.SENTIMENT_NEGATIVE
    elif "pos" in label or label == "label_2":
        mapped = config.SENTIMENT_POSITIVE
    else:
        mapped = config.SENTIMENT_NEUTRAL
    # Detect urgency / anger via keywords
    t = text.lower()
    if mapped == config.SENTIMENT_NEGATIVE and any(
        w in t for w in ("furious", "outrage", "unacceptable", "!!!", "wtf", "horrible")
    ):
        mapped = config.SENTIMENT_ANGRY
    if any(w in t for w in ("asap", "urgent", "immediately", "right now", "emergency",
                            "khẩn cấp", "gấp")):
        mapped = config.SENTIMENT_URGENT
    return {"sentiment": mapped, "confidence": float(out["score"])}


def _classify_sentiment_heuristic(text: str) -> dict:
    t = text.lower()
    if any(w in t for w in ("urgent", "asap", "emergency", "gấp", "khẩn")):
        return {"sentiment": config.SENTIMENT_URGENT, "confidence": 0.6}
    if any(w in t for w in ("angry", "furious", "horrible", "outrage", "tệ quá")):
        return {"sentiment": config.SENTIMENT_ANGRY, "confidence": 0.6}
    if any(w in t for w in ("disappointed", "unhappy", "complaint", "thất vọng")):
        return {"sentiment": config.SENTIMENT_NEGATIVE, "confidence": 0.5}
    if any(w in t for w in ("thank", "great", "wonderful", "cảm ơn", "tốt")):
        return {"sentiment": config.SENTIMENT_POSITIVE, "confidence": 0.5}
    return {"sentiment": config.SENTIMENT_NEUTRAL, "confidence": 0.5}


# ===========================================================================
# 4) EMBEDDING / VECTORISATION
# ===========================================================================

_local_embed_model = None


def create_embedding(text: str) -> list:
    """Return a list of floats. Uses BGE locally OR Gemini embed API."""
    if not text:
        return []

    if config.USE_LOCAL_MODELS and config.EMBEDDING_MODEL_NAME:
        try:
            return _embed_local(text)
        except Exception as e:
            print(f"[nlp] local embed failed ({e}), fall back to API")

    if config.USE_LLM_API and config.GEMINI_API_KEY:
        try:
            return llm_client.gemini_embed(text[:8000])
        except Exception as e:
            print(f"[nlp] Gemini embed failed: {e}")

    # Last resort: hash-based pseudo-embedding (lets the rest of the system
    # still work; quality is poor).
    return _hash_embed(text)


def _embed_local(text: str) -> list:
    global _local_embed_model
    if _local_embed_model is None:
        from sentence_transformers import SentenceTransformer
        _local_embed_model = SentenceTransformer(config.EMBEDDING_MODEL_NAME)
    vec = _local_embed_model.encode([text[:8000]], normalize_embeddings=True)[0]
    return vec.tolist()


def _hash_embed(text: str, dim: int = 128) -> list:
    """Deterministic cheap fallback embedding — only for keeping pipeline alive."""
    import hashlib
    vec = [0.0] * dim
    for token in text.lower().split():
        h = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
        vec[h % dim] += 1.0
    # L2-normalise
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


# ===========================================================================
# 5) SIMILARITY CHECK
# ===========================================================================

def calculate_similarity(text1, text2) -> float:
    """Cosine similarity in [-1, 1] (typically 0..1 for non-negative embeddings)."""
    vec1 = text1 if isinstance(text1, list) else create_embedding(text1)
    vec2 = text2 if isinstance(text2, list) else create_embedding(text2)
    return _cosine(vec1, vec2)


def _cosine(a: list, b: list) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


# ===========================================================================
# 6) SUMMARY
# ===========================================================================

SUMMARY_SYSTEM_PROMPT = """Summarise the email below in ONE concise sentence \
(max 25 words) for a busy manager. Be factual. Do NOT invent details. \
Mention what the customer wants and any date/time they specified.
"""


def summarise_email(text: str) -> str:
    if not text or len(text.strip()) < 30:
        return text.strip()

    if config.USE_LLM_API:
        try:
            return llm_client.chat_text(
                SUMMARY_SYSTEM_PROMPT, text, max_tokens=80,
            ).strip().replace("\n", " ")
        except Exception as e:
            print(f"[nlp] summary failed: {e}")

    # Fallback: first 2 lines truncated
    head = " ".join(text.split())[:200]
    return head + ("..." if len(text) > 200 else "")


# ===========================================================================
# 7) TOPIC MODELLING (analytics)
# ===========================================================================

def run_topic_modelling(email_texts: list, n_topics: int = 5, n_top_words: int = 8):
    """Return a list of topics: [{"id": int, "top_words": [str], "size": int}]."""
    if not email_texts or len(email_texts) < 3:
        return []
    try:
        from sklearn.feature_extraction.text import CountVectorizer
        from sklearn.decomposition import LatentDirichletAllocation
    except ImportError:
        print("[nlp] scikit-learn not installed; skip topic modelling")
        return []

    vectorizer = CountVectorizer(
        max_df=0.9, min_df=2, stop_words="english", max_features=1000,
    )
    try:
        X = vectorizer.fit_transform(email_texts)
    except ValueError:
        return []

    lda = LatentDirichletAllocation(
        n_components=min(n_topics, X.shape[0]),
        random_state=42, learning_method="batch",
    )
    lda.fit(X)
    feature_names = vectorizer.get_feature_names_out()
    doc_topic = lda.transform(X).argmax(axis=1)

    topics = []
    for k, comp in enumerate(lda.components_):
        top_idx = comp.argsort()[-n_top_words:][::-1]
        topics.append({
            "id": k,
            "top_words": [feature_names[i] for i in top_idx],
            "size": int((doc_topic == k).sum()),
        })
    return topics


# ===========================================================================
# 8) PCA VISUALISATION
# ===========================================================================

def run_pca_visualisation(embeddings: list):
    """Return a list of (x, y) tuples — one per input embedding."""
    if not embeddings or len(embeddings) < 2:
        return []
    try:
        import numpy as np
        from sklearn.decomposition import PCA
    except ImportError:
        print("[nlp] scikit-learn / numpy not installed; skip PCA")
        return []

    X = np.array(embeddings, dtype=float)
    n_components = min(2, X.shape[0], X.shape[1])
    pca = PCA(n_components=n_components, random_state=42)
    coords = pca.fit_transform(X)
    if coords.shape[1] == 1:
        coords = np.column_stack([coords, np.zeros(coords.shape[0])])
    return [(float(x), float(y)) for x, y in coords]


# ===========================================================================
# Helpers
# ===========================================================================

_hf_pipelines: dict = {}


def _get_hf_pipeline(task: str, model_name: str):
    key = (task, model_name)
    if key not in _hf_pipelines:
        from transformers import pipeline
        _hf_pipelines[key] = pipeline(task, model=model_name)
    return _hf_pipelines[key]


def _clip01(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, v))


# ===========================================================================
# Direct test
# ===========================================================================

if __name__ == "__main__":
    sample = (
        "Hi, I'd like to book a consultation next Wednesday at 3pm. "
        "My name is John Smith, phone 07123456789. "
        "Please confirm. Thanks!"
    )
    print("Intent:", classify_intent(sample))
    print("Extract:", json.dumps(extract_booking_info(sample, "john@example.com"),
                                  indent=2, ensure_ascii=False))
    print("Sentiment:", classify_sentiment(sample))
    print("Summary:", summarise_email(sample))
    vec = create_embedding(sample)
    print(f"Embedding dim: {len(vec)}")
    print(f"Self similarity: {calculate_similarity(vec, vec):.3f}")

    


# ===========================================================================
# 6) SUMMARY
# ===========================================================================

SUMMARY_SYSTEM_PROMPT = """Summarise the email below in ONE concise sentence \
(max 25 words) for a busy manager. Be factual. Do NOT invent details. \
Mention what the customer wants and any date/time they specified.
"""


def summarise_email(text: str) -> str:
    if not text or len(text.strip()) < 30:
        return text.strip()

    if config.USE_LLM_API:
        try:
            return llm_client.chat_text(
                SUMMARY_SYSTEM_PROMPT, text, max_tokens=80,
            ).strip().replace("\n", " ")
        except Exception as e:
            print(f"[nlp] summary failed: {e}")

    head = " ".join(text.split())[:200]
    return head + ("..." if len(text) > 200 else "")


# ===========================================================================
# 7) TOPIC MODELLING (analytics)
# ===========================================================================

def run_topic_modelling(email_texts: list, n_topics: int = 5, n_top_words: int = 8):
    if not email_texts or len(email_texts) < 3:
        return []
    try:
        from sklearn.feature_extraction.text import CountVectorizer
        from sklearn.decomposition import LatentDirichletAllocation
    except ImportError:
        print("[nlp] scikit-learn not installed; skip topic modelling")
        return []

    vectorizer = CountVectorizer(
        max_df=0.9, min_df=2, stop_words="english", max_features=1000,
    )
    try:
        X = vectorizer.fit_transform(email_texts)
    except ValueError:
        return []

    lda = LatentDirichletAllocation(
        n_components=min(n_topics, X.shape[0]),
        random_state=42, learning_method="batch",
    )
    lda.fit(X)
    feature_names = vectorizer.get_feature_names_out()
    doc_topic = lda.transform(X).argmax(axis=1)

    topics = []
    for k, comp in enumerate(lda.components_):
        top_idx = comp.argsort()[-n_top_words:][::-1]
        topics.append({
            "id": k,
            "top_words": [feature_names[i] for i in top_idx],
            "size": int((doc_topic == k).sum()),
        })
    return topics


# ===========================================================================
# 8) PCA VISUALISATION
# ===========================================================================

def run_pca_visualisation(embeddings: list):
    if not embeddings or len(embeddings) < 2:
        return []
    try:
        import numpy as np
        from sklearn.decomposition import PCA
    except ImportError:
        print("[nlp] scikit-learn / numpy not installed; skip PCA")
        return []

    X = np.array(embeddings, dtype=float)
    n_components = min(2, X.shape[0], X.shape[1])
    pca = PCA(n_components=n_components, random_state=42)
    coords = pca.fit_transform(X)
    if coords.shape[1] == 1:
        coords = np.column_stack([coords, np.zeros(coords.shape[0])])
    return [(float(x), float(y)) for x, y in coords]


# ===========================================================================
# Helpers
# ===========================================================================

_hf_pipelines: dict = {}


def _get_hf_pipeline(task: str, model_name: str):
    key = (task, model_name)
    if key not in _hf_pipelines:
        from transformers import pipeline
        _hf_pipelines[key] = pipeline(task, model=model_name)
    return _hf_pipelines[key]


def _clip01(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, v))


# ===========================================================================
# Direct test
# ===========================================================================

if __name__ == "__main__":
    sample = (
        "Hi, I'd like to book a consultation next Wednesday at 3pm. "
        "My name is John Smith, phone 07123456789. "
        "Please confirm. Thanks!"
    )
    print("Intent:", classify_intent(sample))
    print("Extract:", json.dumps(
        extract_booking_info(sample, "john@example.com"),
        indent=2, ensure_ascii=False,
    ))
    print("Sentiment:", classify_sentiment(sample))
    print("Summary:", summarise_email(sample))
    vec = create_embedding(sample)
    print(f"Embedding dim: {len(vec)}")
    print(f"Self similarity: {calculate_similarity(vec, vec):.3f}")
    print("Summary:", summarise_email(sample))
    vec = create_embedding(sample)
    print(f"Embedding dim: {len(vec)}")
    print(f"Self similarity: {calculate_similarity(vec, vec):.3f}")

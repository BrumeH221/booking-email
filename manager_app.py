# manager_app.py
#
# Streamlit dashboard. Tabs: Pending queue, Need More Info, All, Stats.
# Each card shows AI intent + sentiment + summary + extracted fields, and
# action buttons (Confirm / Cancel / Need More Info / Unavailable / Complete).

import json
import pandas as pd
import streamlit as st

import config
from backend import database as db
from backend import email_templates as templates
from backend.gmail_service import send_email


st.set_page_config(page_title="Booking Manager (NLP)", layout="wide")

try:
    db.init_db()
except Exception as e:
    st.error(f"DB init failed: {e}")
    st.stop()

st.title("Booking Manager Dashboard")
st.caption(
    f"DB: **{config.DB_BACKEND}**  |  LLM: **{config.LLM_PROVIDER}**  |  "
    f"Local HF models: **{'on' if config.USE_LOCAL_MODELS else 'off'}**  |  "
    f"Sheets mirror: **{'on' if config.SHEETS_ENABLED else 'off'}**"
)


INTENT_BADGE = {
    config.INTENT_NEW_BOOKING:    ":green-background[NEW]",
    config.INTENT_RESCHEDULE:     ":orange-background[RESCHEDULE]",
    config.INTENT_CANCEL:         ":red-background[CANCEL]",
    config.INTENT_PRICE_ENQUIRY:  ":blue-background[PRICE]",
    config.INTENT_COMPLAINT:      ":red-background[COMPLAINT]",
    config.INTENT_GENERAL_QUESTION: ":blue-background[QUESTION]",
    config.INTENT_NOT_RELEVANT:   ":gray-background[NOT RELEVANT]",
}
STATUS_BADGE = {
    config.STATUS_PENDING:        ":orange-background[Pending]",
    config.STATUS_NEED_MORE_INFO: ":yellow-background[Need Info]",
    config.STATUS_NOT_RELEVANT:   ":gray-background[Not Relevant]",
    config.STATUS_CONFIRMED:      ":green-background[Confirmed]",
    config.STATUS_CANCELLED:      ":red-background[Cancelled]",
    config.STATUS_UNAVAILABLE:    ":violet-background[Unavailable]",
    config.STATUS_COMPLETED:      ":blue-background[Completed]",
}
SENT_BADGE = {
    config.SENTIMENT_POSITIVE: "😊 positive",
    config.SENTIMENT_NEUTRAL:  "😐 neutral",
    config.SENTIMENT_NEGATIVE: "🙁 negative",
    config.SENTIMENT_ANGRY:    "😠 angry",
    config.SENTIMENT_URGENT:   "⚠️ urgent",
}


def _send_status_email(booking, status, note):
    out = templates.for_status_change(status, booking, note)
    if not out:
        return False
    subj, body = out
    if not booking.get("customer_email"):
        return False
    send_email(to=booking["customer_email"], subject=subj, body=body)
    return True


def _apply(booking_id, booking, new_status, note):
    db.update_booking_status(booking_id, new_status, note)
    sent = _send_status_email(booking, new_status, note)
    msg = f"#{booking_id} → {new_status}"
    if sent:
        msg += " · email sent"
    st.success(msg)
    st.rerun()


def _card(b, context="main"):
    bid = b["id"]
    key_prefix = f"{context}_{bid}"
    header = f"#{bid} · {b.get('service') or '(no service)'} · {b.get('full_name') or '(no name)'}"
    with st.container(border=True):
        c1, c2 = st.columns([3, 1])
        c1.markdown(f"### {header}")
        c2.markdown(
            f"{INTENT_BADGE.get(b.get('intent'), b.get('intent') or '-')}  "
            f"{STATUS_BADGE.get(b.get('status'), b.get('status') or '-')}  "
            f"{SENT_BADGE.get(b.get('sentiment'), b.get('sentiment') or '-')}"
        )

        if b.get("summary"):
            st.markdown(f"**AI summary:** {b['summary']}")

        d1, d2, d3 = st.columns(3)
        d1.write(f"**Customer:** {b.get('full_name') or '-'}")
        d1.write(f"**Email:** {b.get('customer_email') or '-'}")
        d1.write(f"**Phone:** {b.get('phone_number') or '-'}")
        d2.write(f"**Date:** {b.get('preferred_date') or '-'}")
        d2.write(f"**Time:** {b.get('preferred_time') or '-'}")
        d2.write(f"**Service:** {b.get('service') or '-'}")
        d3.write(f"**Location:** {b.get('location') or '-'}")
        d3.write(f"**Symptom:** {b.get('symptom') or '-'}")
        d3.write(f"**Created:** {b.get('created_at') or '-'}")

        with st.expander("Raw cleaned body"):
            st.text(b.get("cleaned_body") or "(empty)")

        note = st.text_area(
            "Manager note (sent to customer for Cancelled / Unavailable / Need Info)",
            value=b.get("manager_note") or "",
            key=f"{key_prefix}_note", height=68,
        )

        status = b.get("status")
        a1, a2, a3, a4 = st.columns(4)

        if status in (config.STATUS_PENDING, config.STATUS_NEED_MORE_INFO):
            if a1.button("✅ Confirm", key=f"{key_prefix}_conf", use_container_width=True):
                _apply(bid, b, config.STATUS_CONFIRMED, note)
            if a2.button("❌ Cancel", key=f"{key_prefix}_can", use_container_width=True):
                _apply(bid, b, config.STATUS_CANCELLED, note)
            if a3.button("⛔ Unavailable", key=f"{key_prefix}_un", use_container_width=True):
                _apply(bid, b, config.STATUS_UNAVAILABLE, note)
            if status != config.STATUS_NEED_MORE_INFO:
                if a4.button("ℹ️ Need Info", key=f"{key_prefix}_ni", use_container_width=True):
                    _apply(bid, b, config.STATUS_NEED_MORE_INFO, note)
        elif status == config.STATUS_CONFIRMED:
            if a1.button("🏁 Mark Completed", key=f"{key_prefix}_comp", use_container_width=True):
                _apply(bid, b, config.STATUS_COMPLETED, note)
            if a2.button("❌ Cancel", key=f"{key_prefix}_can", use_container_width=True):
                _apply(bid, b, config.STATUS_CANCELLED, note)


# ----- Load -----
all_bookings = db.get_all_bookings()
df = pd.DataFrame(all_bookings) if all_bookings else pd.DataFrame()


# ----- Tabs -----
t_pend, t_info, t_all, t_stats = st.tabs(
    ["Pending queue", "Need more info", "All bookings", "Stats"]
)

with t_pend:
    pending = [b for b in all_bookings if b.get("status") == config.STATUS_PENDING]
    st.write(f"**{len(pending)}** pending")
    if not pending:
        st.info("Pending queue is empty.")
    else:
        for b in pending:
            _card(b, context="pending")

with t_info:
    need = [b for b in all_bookings if b.get("status") == config.STATUS_NEED_MORE_INFO]
    st.write(f"**{len(need)}** waiting for more info")
    if not need:
        st.info("Nothing waiting on customer info.")
    else:
        for b in need:
            _card(b, context="needinfo")

with t_all:
    if df.empty:
        st.info("No bookings yet.")
    else:
        f1, f2, f3, f4 = st.columns(4)
        s_filter = f1.multiselect("Status", config.ALL_STATUSES, default=config.ALL_STATUSES)
        i_filter = f2.multiselect("Intent", config.ALL_INTENTS, default=config.ALL_INTENTS)
        e_filter = f3.multiselect("Sentiment", config.ALL_SENTIMENTS, default=config.ALL_SENTIMENTS)
        search = f4.text_input("Search")

        d = df.copy()
        if s_filter: d = d[d["status"].isin(s_filter)]
        if i_filter and "intent" in d.columns: d = d[d["intent"].isin(i_filter)]
        if e_filter and "sentiment" in d.columns: d = d[d["sentiment"].isin(e_filter)]
        if search:
            s = search.lower()
            mask = (
                d.get("full_name", "").astype(str).str.lower().str.contains(s, na=False)
                | d.get("customer_email", "").astype(str).str.lower().str.contains(s, na=False)
                | d.get("summary", "").astype(str).str.lower().str.contains(s, na=False)
            )
            d = d[mask]

        st.write(f"**{len(d)}** booking(s)")
        cols = [c for c in [
            "id", "intent", "sentiment", "status", "full_name",
            "preferred_date", "preferred_time", "service", "customer_email",
            "summary", "created_at",
        ] if c in d.columns]
        st.dataframe(d[cols], use_container_width=True, hide_index=True)

        with st.expander("Edit specific booking"):
            ids = d["id"].tolist() if "id" in d.columns else []
            if ids:
                pick = st.selectbox("Booking id", ids, key="edit_booking_id")
                row = next((b for b in all_bookings if b["id"] == pick), None)
                if row:
                    _card(row, context="edit")

with t_stats:
    if df.empty:
        st.info("No data yet.")
    else:
        c1, c2, c3 = st.columns(3)
        with c1:
            st.subheader("By status")
            st.bar_chart(df["status"].value_counts())
        with c2:
            if "intent" in df.columns:
                st.subheader("By intent")
                st.bar_chart(df["intent"].value_counts())
        with c3:
            if "sentiment" in df.columns:
                st.subheader("By sentiment")
                st.bar_chart(df["sentiment"].value_counts())

        st.divider()
        st.info("For LDA topics and PCA clusters across many emails, "
                "run `streamlit run analytics_app.py`")

# analytics_app.py
#
# Separate dashboard for LDA topic modelling and PCA cluster visualisation.
# Heavy operations (loading scikit-learn, transforming embeddings) are run
# on-demand when the user clicks "Refresh".

import json
import streamlit as st

import config
from backend import database as db
from backend.nlp_pipeline import run_topic_modelling, run_pca_visualisation


st.set_page_config(page_title="Booking Analytics", layout="wide")
db.init_db()

st.title("Booking Analytics")
st.caption("LDA topic modelling + PCA 2D clusters across all collected emails.")

all_bookings = db.get_all_bookings()
st.write(f"Loaded **{len(all_bookings)}** booking(s) from the database.")

if not all_bookings:
    st.info("No data yet — process some emails first.")
    st.stop()

texts = [b.get("cleaned_body") or b.get("summary") or "" for b in all_bookings]
non_empty = [t for t in texts if t.strip()]

st.divider()

# ---- LDA ----
st.subheader("Topic modelling (LDA)")

col1, col2 = st.columns([1, 4])
n_topics = col1.number_input("Number of topics", min_value=2, max_value=10, value=5)
n_words = col1.number_input("Top words per topic", min_value=3, max_value=15, value=8)

if col1.button("Run LDA", type="primary"):
    with st.spinner("Fitting LDA..."):
        topics = run_topic_modelling(non_empty, n_topics=n_topics, n_top_words=n_words)
    if not topics:
        col2.warning("Not enough data for LDA (need at least 3 emails).")
    else:
        for t in topics:
            col2.markdown(f"**Topic {t['id']}**  ({t['size']} emails)")
            col2.write(", ".join(t["top_words"]))
            col2.divider()

st.divider()

# ---- PCA ----
st.subheader("PCA 2D visualisation of email embeddings")

embeddings = []
labels = []
for b in all_bookings:
    raw = b.get("embedding_json") or "[]"
    if isinstance(raw, list):
        vec = raw
    else:
        try: vec = json.loads(raw)
        except Exception: vec = []
    if vec:
        embeddings.append(vec)
        labels.append({
            "intent": b.get("intent") or "-",
            "status": b.get("status") or "-",
            "summary": (b.get("summary") or "")[:80],
            "id": b.get("id"),
        })

if not embeddings:
    st.warning("No embeddings stored. Process more emails with the worker first.")
else:
    st.write(f"{len(embeddings)} embedding(s) available.")
    if st.button("Run PCA", type="primary"):
        with st.spinner("Reducing to 2D..."):
            coords = run_pca_visualisation(embeddings)
        if not coords:
            st.warning("PCA produced no result.")
        else:
            import pandas as pd
            df = pd.DataFrame(
                [{"x": x, "y": y, **labels[i]} for i, (x, y) in enumerate(coords)]
            )
            st.scatter_chart(df, x="x", y="y", color="intent", size=100)
            with st.expander("Show data"):
                st.dataframe(df, use_container_width=True, hide_index=True)

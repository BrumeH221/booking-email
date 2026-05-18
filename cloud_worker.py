# cloud_worker.py — Flask app for Cloud Run, triggered by Cloud Scheduler.
import os, traceback
from flask import Flask, request, jsonify

import config
from main import process_booking_emails

app = Flask(__name__)


@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "booking-email-nlp"})


@app.route("/run", methods=["POST", "GET"])
def run():
    if config.WORKER_SHARED_SECRET:
        if request.headers.get("x-worker-secret", "") != config.WORKER_SHARED_SECRET:
            return jsonify({"error": "unauthorized"}), 401
    try:
        config.validate_config_for_runtime()
        summary = process_booking_emails()
        return jsonify({"ok": True, **summary})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))

"""
app.py — Provenance Guard Flask backend.

Milestone 3 scope:
  - POST /submit : accepts text, runs Signal 1 (Groq), returns a content_id,
                   attribution result, a (placeholder) confidence score, and a
                   (placeholder) label. Writes a structured audit log entry.
  - GET  /log    : returns the audit log entries as JSON.

Confidence is currently just the Groq score. Milestone 4 will add the second
(stylometric) signal and combine the two into the real confidence score.
Milestone 5 will replace the placeholder label with the real transparency labels.
"""

import json
import os
import uuid
from datetime import datetime, timezone

from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from detection import groq_signal

app = Flask(__name__)

# Rate limiting (per planning.md: 10 submissions per minute per IP)
limiter = Limiter(get_remote_address, app=app)

LOG_FILE = "audit_log.json"

# Thresholds from planning.md
AI_THRESHOLD = 0.75      # >= this  -> likely_ai
HUMAN_THRESHOLD = 0.40   # <= this  -> likely_human
# anything in between    -> uncertain


def classify(confidence):
    """Map a confidence score to an attribution result."""
    if confidence >= AI_THRESHOLD:
        return "likely_ai"
    if confidence <= HUMAN_THRESHOLD:
        return "likely_human"
    return "uncertain"


def read_log():
    """Read all audit log entries. Returns an empty list if no log yet."""
    if not os.path.exists(LOG_FILE):
        return []
    try:
        with open(LOG_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError):
        return []


def write_log(entry):
    """Append a structured entry to the audit log."""
    logs = read_log()
    logs.append(entry)
    with open(LOG_FILE, "w") as f:
        json.dump(logs, f, indent=2)


@app.route("/submit", methods=["POST"])
@limiter.limit("10 per minute")
def submit():
    data = request.get_json(silent=True) or {}
    text = data.get("text")
    creator_id = data.get("creator_id", "anonymous")

    if not text or not text.strip():
        return jsonify({"error": "Missing 'text' field"}), 400

    # Signal 1: Groq LLM
    llm_score = groq_signal(text)

    # M3 placeholder: confidence is just the LLM score for now.
    # M4 will combine this with the stylometric signal.
    confidence = llm_score
    attribution = classify(confidence)

    content_id = str(uuid.uuid4())

    # M3 placeholder label. Real transparency labels arrive in M5.
    label = f"[placeholder] {attribution} (confidence {confidence:.2f})"

    # Write a structured audit log entry
    entry = {
        "content_id": content_id,
        "creator_id": creator_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "attribution": attribution,
        "confidence": round(confidence, 2),
        "llm_score": round(llm_score, 2),
        "status": "classified",
    }
    write_log(entry)

    return jsonify({
        "content_id": content_id,
        "attribution": attribution,
        "confidence": round(confidence, 2),
        "label": label,
    })


@app.route("/log", methods=["GET"])
def get_log():
    return jsonify({"entries": read_log()})


if __name__ == "__main__":
    app.run(debug=True, port=5000)

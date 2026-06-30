"""
app.py — Provenance Guard Flask backend.

Milestone 5 scope (production layer):
  - POST /submit : runs both signals, combines into confidence, returns the
                   REAL transparency label (one of three variants), writes a
                   complete structured audit log entry.
  - POST /appeal : accepts a content_id + creator_reasoning, logs the appeal
                   alongside the original decision, flips status to
                   "under_review", returns confirmation.
  - GET  /log    : returns the audit log entries as JSON.
  - Rate limiting on /submit (10/minute per planning.md).
"""

import json
import os
import uuid
from datetime import datetime, timezone

from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from detection import groq_signal, stylometric_signal

app = Flask(__name__)

# Rate limiting (per planning.md: 10 submissions per minute per IP).
# storage_uri="memory://" is required by Flask-Limiter 3.x for local dev.
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)

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


def generate_label(confidence):
    """
    Map a confidence score to one of the three transparency labels from
    planning.md. The text changes based on the score — it is never the same
    text regardless of score.
    """
    if confidence >= AI_THRESHOLD:
        return (
            "This content shows strong indicators of AI generation. "
            "Our system detected patterns consistent with AI-generated text, "
            "including uniform sentence structure and low stylistic variation. "
            "If you believe this is an error, you can submit an appeal."
        )
    if confidence <= HUMAN_THRESHOLD:
        return (
            "This content shows strong indicators of human authorship. "
            "Our system detected variable sentence structure, diverse vocabulary, "
            "and natural stylistic patterns consistent with human writing. "
            "If you believe this is an error, you can submit an appeal."
        )
    return (
        "Our system could not confidently determine the origin of this content. "
        "This does not mean something is wrong with your writing — it means the "
        "signals were mixed and the system is not sure either way. "
        "You may submit an appeal if you'd like a human to review it."
    )


def read_log():
    """Read all audit log entries. Returns an empty list if no log yet."""
    if not os.path.exists(LOG_FILE):
        return []
    try:
        with open(LOG_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError):
        return []


def write_log(logs):
    """Write the full list of audit log entries back to disk."""
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

    # Run both detection signals
    llm_score = groq_signal(text)
    style_score = stylometric_signal(text)

    # Combine into the confidence score (both weighted equally per planning.md)
    confidence = (llm_score + style_score) / 2
    attribution = classify(confidence)
    label = generate_label(confidence)

    content_id = str(uuid.uuid4())

    # Complete structured audit log entry
    entry = {
        "content_id": content_id,
        "creator_id": creator_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "attribution": attribution,
        "confidence": round(confidence, 2),
        "llm_score": round(llm_score, 2),
        "stylometric_score": round(style_score, 2),
        "status": "classified",
        "appeal_reasoning": None,
    }
    logs = read_log()
    logs.append(entry)
    write_log(logs)

    return jsonify({
        "content_id": content_id,
        "attribution": attribution,
        "confidence": round(confidence, 2),
        "llm_score": round(llm_score, 2),
        "stylometric_score": round(style_score, 2),
        "label": label,
    })


@app.route("/appeal", methods=["POST"])
def appeal():
    data = request.get_json(silent=True) or {}
    content_id = data.get("content_id")
    reasoning = data.get("creator_reasoning")

    if not content_id or not reasoning:
        return jsonify({
            "error": "Both 'content_id' and 'creator_reasoning' are required"
        }), 400

    logs = read_log()

    # Find the original decision for this content_id
    matched = None
    for entry in logs:
        if entry.get("content_id") == content_id:
            matched = entry
            break

    if matched is None:
        return jsonify({"error": f"No content found with id {content_id}"}), 404

    # Log the appeal alongside the original decision and flip status.
    # Automated re-classification is NOT performed — a human reviews it later.
    matched["status"] = "under_review"
    matched["appeal_reasoning"] = reasoning
    matched["appeal_timestamp"] = datetime.now(timezone.utc).isoformat()
    write_log(logs)

    return jsonify({
        "message": "Appeal received. Your content has been marked for human review.",
        "content_id": content_id,
        "status": "under_review",
    })


@app.route("/log", methods=["GET"])
def get_log():
    return jsonify({"entries": read_log()})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
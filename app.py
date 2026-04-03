"""
DocMind — Micro-SaaS MVP
Flask backend with FAISS contextual retrieval from uploaded PDFs.
"""

import os
import traceback
from pathlib import Path

from flask import Flask, request, jsonify, render_template
from werkzeug.utils import secure_filename

import usage_tracker as tracker
import retrieval_engine as engine

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024  # 32 MB upload cap
UPLOAD_DIR = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_EXT = {"pdf"}


def _allowed(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


# ── Pages ───────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ── API ─────────────────────────────────────────────────────

@app.route("/api/status")
def api_status():
    return jsonify(tracker.get_status())


@app.route("/api/upload", methods=["POST"])
def api_upload():
    status = tracker.get_status()
    if not status["can_upload"]:
        return jsonify({"error": "Upload limit reached for your tier."}), 403

    if "file" not in request.files:
        return jsonify({"error": "No file provided."}), 400

    file = request.files["file"]
    if file.filename == "" or not _allowed(file.filename):
        return jsonify({"error": "Only .pdf files are accepted."}), 400

    safe_name = secure_filename(file.filename)
    save_path = UPLOAD_DIR / safe_name
    file.save(str(save_path))

    try:
        result = engine.ingest_pdf(str(save_path), safe_name)
        tracker.record_upload()
        return jsonify({"ok": True, **result})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/query", methods=["POST"])
def api_query():
    status = tracker.get_status()
    if not status["can_query"]:
        return jsonify({"error": "Query limit reached for your tier."}), 403

    data = request.get_json(silent=True) or {}
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"error": "Empty question."}), 400

    # Contextual retrieval
    chunks = engine.contextual_search(question, k=5)
    if not chunks:
        tracker.record_query()
        return jsonify({
            "answer": "I don't have any documents to search yet. Please upload a PDF first.",
            "sources": [],
        })

    # Build a grounded answer from retrieved context
    # (In production, send chunks + question to an LLM like Claude.)
    context_block = "\n\n---\n\n".join(
        f"[{c['source']} p.{c['page']}]  {c['text']}" for c in chunks
    )

    answer = (
        f"Based on your documents, here are the most relevant passages:\n\n"
    )
    for i, c in enumerate(chunks[:3], 1):
        snippet = c["text"][:300].replace("\n", " ")
        answer += f"**{i}. {c['source']} (p.{c['page']})**\n{snippet}...\n\n"

    tracker.record_query()
    return jsonify({
        "answer": answer,
        "sources": [
            {"file": c["source"], "page": c["page"], "relevance": c["score"]}
            for c in chunks[:3]
        ],
    })


@app.route("/api/documents")
def api_documents():
    return jsonify({"documents": engine.list_documents()})


@app.route("/api/tier", methods=["POST"])
def api_set_tier():
    data = request.get_json(silent=True) or {}
    tier = data.get("tier")
    if tier not in (1, 2):
        return jsonify({"error": "Tier must be 1 or 2"}), 400
    return jsonify(tracker.set_tier(tier))


@app.route("/api/reset", methods=["POST"])
def api_reset():
    """Dev helper: wipe usage counters."""
    return jsonify(tracker.reset())


# ── Run ─────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)

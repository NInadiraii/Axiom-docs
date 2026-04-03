"""
DocMind + Contextual Transmuter — Micro-SaaS MVP
Flask backend with FAISS contextual retrieval from uploaded PDFs
and a Claude-powered document transmuter.
"""

import os
import traceback
from pathlib import Path

from flask import Flask, request, jsonify, render_template
from werkzeug.utils import secure_filename

import usage_tracker as tracker
import retrieval_engine as engine
import transmuter

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024  # 32 MB upload cap
UPLOAD_DIR = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_EXT = {"pdf"}


def _allowed(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


# ── Pages ────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ── DocMind API ──────────────────────────────────────────────

@app.route("/api/status")
def api_status():
    return jsonify(tracker.get_status())


@app.route("/api/usage")
def api_usage():
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
        usage = tracker.record_upload()
        return jsonify({"ok": True, "usage": usage, **result})
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

    chunks = engine.contextual_search(question, k=5)
    if not chunks:
        tracker.record_query()
        return jsonify({
            "ok": True,
            "answer": "I don't have any documents to search yet. Please upload a PDF first.",
            "sources": [],
            "usage": tracker.get_status(),
        })

    answer = "Based on your documents, here are the most relevant passages:\n\n"
    for i, c in enumerate(chunks[:3], 1):
        snippet = c["text"][:300].replace("\n", " ")
        answer += f"**{i}. {c['source']} (p.{c['page']})**\n{snippet}...\n\n"

    usage = tracker.record_query()
    return jsonify({
        "ok": True,
        "answer": answer,
        "sources": [
            {"file": c["source"], "page": c["page"], "relevance": c["score"]}
            for c in chunks[:3]
        ],
        "usage": usage,
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


@app.route("/api/upgrade", methods=["POST"])
def api_upgrade():
    return jsonify({"ok": True, "usage": tracker.set_tier(2)})


@app.route("/api/reset", methods=["POST"])
def api_reset():
    """Dev helper: wipe usage counters."""
    return jsonify(tracker.reset())


# ── Transmuter API ───────────────────────────────────────────

@app.route("/api/transmute", methods=["POST"])
def api_transmute():
    """
    Convert raw informal text into a polished professional document.

    Request JSON:
        {
            "text":       "<raw input>",
            "mode":       "auto" | "academic" | "professional",  // optional
            "target_doc": "<desired output description>"         // optional
        }

    Response JSON:
        {
            "ok":            true,
            "document":      "<markdown string>",
            "detected_mode": "academic" | "professional",
            "input_tokens":  <int>,
            "output_tokens": <int>
        }
    """
    data = request.get_json(silent=True) or {}

    raw_text = (data.get("text") or "").strip()
    if not raw_text:
        return jsonify({"error": "No text provided."}), 400

    mode = data.get("mode", "auto")
    if mode not in ("auto", "academic", "professional"):
        mode = "auto"

    target_doc = (data.get("target_doc") or "").strip()

    try:
        result = transmuter.transmute(raw_text, mode=mode, target_doc=target_doc)
        return jsonify({"ok": True, **result})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except Exception:
        traceback.print_exc()
        return jsonify({"error": "Transmutation failed. Check server logs."}), 500


# ── Run ──────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)

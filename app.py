from __future__ import annotations

import logging
import os
from dataclasses import asdict

from flask import Flask, Response, jsonify, render_template, request

from nptel_verifier import VerificationResult, build_csv, verify_certificate

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB upload cap

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Security headers (applied to every response)
# ---------------------------------------------------------------------------

@app.after_request
def set_security_headers(response: Response) -> Response:
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "media-src 'self'; "
        "connect-src 'self'; "
        "frame-ancestors 'none';"
    )
    return response


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PDF_MAGIC = b"%PDF"
MAX_FILES = 100


def _is_valid_pdf(content: bytes) -> bool:
    return content[:4] == PDF_MAGIC


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
def index():
    return render_template("index.html")


@app.get("/toolkit")
def toolkit():
    return render_template("toolkit.html")


@app.post("/api/verify")
def verify_uploads():
    files = request.files.getlist("certificates")
    if not files:
        return jsonify({"error": "Upload at least one certificate PDF."}), 400

    if len(files) > MAX_FILES:
        return jsonify({"error": f"Maximum {MAX_FILES} files per request."}), 400

    results: list[VerificationResult] = []
    for uploaded_file in files:
        content = uploaded_file.read()
        if not content:
            continue
        if not _is_valid_pdf(content):
            logger.warning("Rejected non-PDF upload: %s", uploaded_file.filename)
            return jsonify({"error": f"{uploaded_file.filename!r} is not a valid PDF."}), 400
        try:
            results.append(verify_certificate(uploaded_file.filename, content))
        except ValueError:
            logger.info("Rejected unreadable PDF upload: %s", uploaded_file.filename)
            return jsonify({"error": "One or more uploaded files could not be processed as PDFs."}), 400
        except Exception:
            logger.exception("Verification failed for %s", uploaded_file.filename)
            return jsonify({"error": "Verification failed. Please try again."}), 500

    if not results:
        return jsonify({"error": "Upload at least one non-empty certificate PDF."}), 400

    logger.info("Verified %d certificate(s)", len(results))
    return jsonify({"results": [asdict(r) for r in results]})


@app.post("/api/export")
def export_csv_from_payload():
    payload = request.get_json(silent=True) or {}
    raw_results = payload.get("results")
    if not raw_results or not isinstance(raw_results, list):
        return jsonify({"error": "No results provided."}), 400
    if len(raw_results) > MAX_FILES:
        return jsonify({"error": f"Maximum {MAX_FILES} results per export."}), 400

    try:
        results = [_result_from_dict(item) for item in raw_results]
    except Exception:
        logger.exception("Failed to deserialise export payload")
        return jsonify({"error": "Invalid results payload."}), 400

    csv_text = build_csv(results)
    return Response(
        csv_text,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=certforge-nptel-report.csv"},
    )


def _result_from_dict(data: dict) -> VerificationResult:
    from nptel_verifier import CertificateFields

    return VerificationResult(
        filename=str(data.get("filename", "")),
        status=str(data.get("status", "")),
        confidence=int(data.get("confidence", 0) or 0),
        qr_url=str(data.get("qr_url", "")),
        certificate_url=str(data.get("certificate_url", "")),
        uploaded=CertificateFields(**(data.get("uploaded") or {})),
        online=CertificateFields(**(data.get("online") or {})),
        field_matches=dict(data.get("field_matches") or {}),
        messages=list(data.get("messages") or []),
        same_file=bool(data.get("same_file")),
        local_sha256=str(data.get("local_sha256", "")),
        online_sha256=str(data.get("online_sha256", "")),
    )


@app.get("/health")
def health():
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(413)
def request_too_large(e):
    return jsonify({"error": "Upload exceeds the 50 MB limit."}), 413


@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found."}), 404


@app.errorhandler(500)
def internal_error(e):
    logger.exception("Unhandled server error")
    return jsonify({"error": "An unexpected error occurred."}), 500


# ---------------------------------------------------------------------------
# Entry point (development only — use gunicorn in production)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    app.run(host="127.0.0.1", port=5000, debug=debug)

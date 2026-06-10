"""
Vercel serverless entry point for Venmo OSINT.

Differences from local app.py:
  - No threading (serverless is single-process)
  - No file-based cookie storage; cookie supplied via VENMO_COOKIE env var
    (set it in Vercel project settings → Environment Variables)
  - Pattern search runs sequentially with a hard cap of 5 probes to stay
    inside Vercel's 10-second function timeout
  - SESSION is re-created per cold-start (no persistent state)
"""

import json
import os
import sys

# Make sure the project root is on the path so we can import venmo_osint
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from flask import Flask, Response, jsonify, request, render_template_string


from venmo_osint import (
    SESSION,
    apply_cookie,
    fetch_profile,
    search_users,
    search_by_name,
)

# Apply cookie from environment variable at cold-start
_env_cookie = os.environ.get("VENMO_COOKIE", "")
if _env_cookie:
    apply_cookie(_env_cookie)

app = Flask(__name__)


# ── Global error handlers ─────────────────────────────────────────────────────

import traceback

@app.errorhandler(Exception)
def handle_exception(e):
    if request.path.startswith("/api/"):
        tb = traceback.format_exc()
        return jsonify({"error": f"{type(e).__name__}: {e}", "trace": tb[-800:]}), 500
    raise e

@app.errorhandler(404)
def handle_404(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Not found"}), 404
    return render_template_string(HTML)


# ── routes ────────────────────────────────────────────────────────────────────

# Serve the same HTML from app.py (import it)
try:
    from app import HTML
except ImportError:
    HTML = "<h1>Venmo OSINT</h1><p>Could not load app.py</p>"


@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/api/profile/<username>")
def api_profile(username):
    return jsonify(fetch_profile(username))


@app.route("/api/image-proxy")
def api_image_proxy():
    url = request.args.get("url", "")
    if not url:
        return jsonify({"error": "Missing url"}), 400

    allowed_hosts = ("pics-v3.venmo.com", "s3.amazonaws.com", "venmo.com")
    if not any(h in url for h in allowed_hosts) or not url.startswith("https://"):
        return jsonify({"error": "URL not allowed"}), 400

    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as exc:
        return jsonify({"error": str(exc)}), 502

    return Response(
        resp.content,
        mimetype=resp.headers.get("content-type", "image/jpeg"),
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.route("/api/search/name")
def api_search_name():
    first = request.args.get("first", "").strip()
    last  = request.args.get("last",  "").strip()
    limit = min(int(request.args.get("limit", 20)), 50)
    if not first and not last:
        return jsonify([{"error": "Provide at least a first or last name"}])
    return jsonify(search_by_name(first, last, limit=limit))


@app.route("/api/search")
def api_search():
    q     = request.args.get("q", "").strip()
    limit = int(request.args.get("limit", 10))
    if not q:
        return jsonify([{"error": "Missing query parameter 'q'"}])
    return jsonify(search_users(q, limit=limit))


@app.route("/api/cookie/status")
def api_cookie_status():
    has_cookie = bool(_env_cookie or SESSION.cookies)
    source = "VENMO_COOKIE env var" if _env_cookie else ("session" if SESSION.cookies else "not set")
    return jsonify({"active": has_cookie, "detail": source})


# Cookie save/clear are no-ops on Vercel (use env vars instead)
@app.route("/api/cookie/save", methods=["POST"])
def api_cookie_save():
    return jsonify({"ok": False, "error": "On Vercel, set the VENMO_COOKIE environment variable in your project settings instead of saving it here."})


@app.route("/api/cookie/clear", methods=["POST"])
def api_cookie_clear():
    return jsonify({"ok": False, "error": "On Vercel, remove the VENMO_COOKIE environment variable in your project settings."})


@app.route("/api/cookie/capabilities")
def api_cookie_capabilities():
    return jsonify({"grab_available": False})


@app.route("/api/cookie/grab", methods=["POST"])
def api_cookie_grab():
    return jsonify({
        "ok": False,
        "error": "Grab from Browser is not available on the hosted Vercel version — it requires local machine access to your browser profile. Run the app locally with: python3 app.py"
    })


# Vercel calls the app as `app`

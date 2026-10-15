"""
app.py - Website Change Detector
---------------------------------
A simple Flask app that monitors public webpages for content changes.
Uses SQLite for storage, SHA-256 hashing for change detection,
and BeautifulSoup for text extraction.
"""

import atexit
import difflib
import hashlib
import ipaddress
import os
import socket
import sqlite3
import threading
import time
import urllib.parse
from datetime import datetime, timedelta

from bs4 import BeautifulSoup
from flask import Flask, jsonify, render_template, request
import requests

app = Flask(__name__)
DB_PATH = os.path.join(os.path.dirname(__file__), "change_detector.db")


# ==========================================
# 1. Database
# ==========================================

def get_db():
    """Return a SQLite connection with row-name access enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


# Allowed check intervals in minutes (0 = manual only)
ALLOWED_INTERVALS = [0, 1, 15, 30, 60, 1440]


def init_db():
    """Create tables if they don't exist yet, and add new columns safely."""
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS websites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
                last_status TEXT DEFAULT 'Pending',
                last_message TEXT DEFAULT 'Not checked yet',
                last_checked TEXT,
                last_hash TEXT,
                last_snippet TEXT,
                check_interval INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS change_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                website_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                summary TEXT NOT NULL,
                diff_snippet TEXT,
                checked_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (website_id) REFERENCES websites(id) ON DELETE CASCADE
            );
        """)
        # Safe migration: add check_interval column if upgrading from older schema
        columns = [row[1] for row in conn.execute("PRAGMA table_info(websites)").fetchall()]
        if "check_interval" not in columns:
            conn.execute("ALTER TABLE websites ADD COLUMN check_interval INTEGER DEFAULT 0")


# ==========================================
# 2. Security (SSRF Protection)
# ==========================================

def is_safe_url(url):
    """
    Block localhost, private/internal IPs, and cloud metadata endpoints
    to prevent Server-Side Request Forgery (SSRF) attacks.
    """
    try:
        parsed = urllib.parse.urlparse(url.strip())

        # Must be http or https with a valid hostname
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False, "URL must start with http:// or https:// and include a valid domain."

        host = parsed.hostname.lower()

        # Block obvious localhost variants
        if host in ("localhost", "0.0.0.0") or host.endswith(".localhost"):
            return False, "Access to localhost is blocked for security."

        # Resolve hostname and check each IP address
        for _, _, _, _, sockaddr in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(sockaddr[0])
            if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                return False, f"Blocked: URL points to private or internal IP ({ip})."

        return True, "Safe URL."
    except Exception as e:
        return False, f"Invalid URL or domain could not be resolved: {e}"


# ==========================================
# 3. Scraping & Change Detection
# ==========================================

def fetch_text(url):
    """Download webpage HTML (8s timeout, 2MB limit) and extract readable text."""
    headers = {"User-Agent": "WebsiteChangeDetector/1.0"}
    resp = requests.get(url, headers=headers, timeout=8, stream=True, allow_redirects=True)
    resp.raise_for_status()

    # Read up to 2MB to prevent memory issues
    content = bytearray()
    for chunk in resp.iter_content(chunk_size=16384):
        content.extend(chunk)
        if len(content) > 2 * 1024 * 1024:
            raise ValueError("Webpage exceeds 2MB size limit.")

    soup = BeautifulSoup(content.decode(resp.encoding or "utf-8", errors="replace"), "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "header", "footer"]):
        tag.decompose()

    # Normalize whitespace into clean lines
    lines = [" ".join(line.split()) for line in soup.get_text("\n").splitlines()]
    return "\n".join(line for line in lines if line)


def detect_changes(url, previous_hash=None, previous_snippet=None):
    """
    Fetch URL, hash its text content, and compare with the previous baseline.
    Returns: (status, message, new_hash, new_snippet, diff_snippet)
    """
    safe, reason = is_safe_url(url)
    if not safe:
        return "Error", reason, previous_hash, previous_snippet, None

    try:
        text = fetch_text(url)
        new_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        snippet = text[:800]

        # First scan — establish baseline
        if not previous_hash:
            return ("Baseline Created",
                    f"Baseline saved ({len(text):,} characters indexed).",
                    new_hash, snippet,
                    f"Baseline established:\n{snippet[:200]}...")

        # Content unchanged
        if new_hash == previous_hash:
            return "No Change", "Content is identical to previous check.", new_hash, snippet, None

        # Content changed — generate diff
        old_lines = (previous_snippet or "").splitlines()
        new_lines = snippet.splitlines()
        diff = "\n".join(list(difflib.unified_diff(
            old_lines, new_lines, fromfile="Previous", tofile="Current", lineterm=""
        ))[:12])
        return "Changed", "Webpage content has changed!", new_hash, snippet, diff

    except requests.exceptions.Timeout:
        return "Error", "Request timed out after 8 seconds.", previous_hash, previous_snippet, None
    except requests.exceptions.ConnectionError:
        return "Error", "Connection failed. Website may be down or domain not found.", previous_hash, previous_snippet, None
    except Exception as e:
        return "Error", f"Failed to check website: {e}", previous_hash, previous_snippet, None


# ==========================================
# 4. Flask Routes
# ==========================================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/websites", methods=["GET"])
def get_websites():
    """Return all monitored websites with summary stats and next check time."""
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM websites ORDER BY id DESC").fetchall()
        websites = []
        for r in rows:
            w = dict(r)
            # Calculate next scheduled check time
            w["next_check"] = compute_next_check(w)
            websites.append(w)

    stats = {
        "total": len(websites),
        "changed": sum(1 for w in websites if w["last_status"] == "Changed"),
        "unchanged": sum(1 for w in websites if w["last_status"] in ("No Change", "Baseline Created")),
        "errors": sum(1 for w in websites if w["last_status"] == "Error"),
    }
    return jsonify({"success": True, "websites": websites, "stats": stats})


def compute_next_check(website):
    """Return a human-readable string for when the next auto-check is due."""
    interval = website.get("check_interval") or 0
    if interval == 0:
        return "Manual only"
    last = website.get("last_checked")
    if not last:
        return "Now"
    try:
        last_dt = datetime.strptime(last, "%Y-%m-%d %H:%M:%S")
        next_dt = last_dt + timedelta(minutes=interval)
        now = datetime.now()
        if next_dt <= now:
            return "Due now"
        diff = next_dt - now
        mins = int(diff.total_seconds() / 60)
        if mins < 1:
            return "< 1 min"
        if mins < 60:
            return f"~{mins} min"
        return f"~{mins // 60}h {mins % 60}m"
    except ValueError:
        return "Unknown"


@app.route("/api/websites", methods=["POST"])
def add_website():
    """Add a new website and run an immediate baseline scan."""
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    url = (data.get("url") or "").strip()
    interval = data.get("interval", 0)

    if not name or not url:
        return jsonify({"success": False, "error": "Name and URL are required."}), 400

    # Validate interval
    try:
        interval = int(interval)
    except (TypeError, ValueError):
        interval = 0
    if interval not in ALLOWED_INTERVALS:
        interval = 0

    # Auto-add https:// if no scheme provided
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    with get_db() as conn:
        if conn.execute("SELECT id FROM websites WHERE url = ?", (url,)).fetchone():
            return jsonify({"success": False, "error": "This URL is already monitored."}), 409

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor = conn.execute(
            "INSERT INTO websites (name, url, check_interval, created_at) VALUES (?, ?, ?, ?)",
            (name, url, interval, now),
        )
        site_id = cursor.lastrowid

    # Run immediate baseline scan
    status, msg, chash, snippet, diff = detect_changes(url)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        conn.execute(
            "UPDATE websites SET last_status=?, last_message=?, last_checked=?, last_hash=?, last_snippet=? WHERE id=?",
            (status, msg, now, chash, snippet, site_id),
        )
        conn.execute(
            "INSERT INTO change_history (website_id, status, summary, diff_snippet, checked_at) VALUES (?,?,?,?,?)",
            (site_id, status, msg, diff, now),
        )

    return jsonify({"success": True, "message": f"Added '{name}' and established baseline."}), 201


@app.route("/api/websites/<int:site_id>/check", methods=["POST"])
def check_website(site_id):
    """Manually re-check a website for changes."""
    with get_db() as conn:
        site = conn.execute("SELECT * FROM websites WHERE id = ?", (site_id,)).fetchone()
        if not site:
            return jsonify({"success": False, "error": "Website not found."}), 404

        status, msg, chash, snippet, diff = detect_changes(site["url"], site["last_hash"], site["last_snippet"])
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        conn.execute(
            "UPDATE websites SET last_status=?, last_message=?, last_checked=?, last_hash=?, last_snippet=? WHERE id=?",
            (status, msg, now, chash, snippet, site_id),
        )
        # Only record history if content actually changed or there's an error
        if status != "No Change":
            conn.execute(
                "INSERT INTO change_history (website_id, status, summary, diff_snippet, checked_at) VALUES (?,?,?,?,?)",
                (site_id, status, msg, diff, now),
            )

    return jsonify({"success": True, "status": status, "message": msg})


@app.route("/api/websites/<int:site_id>", methods=["DELETE"])
def delete_website(site_id):
    """Remove a website and its history from monitoring."""
    with get_db() as conn:
        conn.execute("DELETE FROM websites WHERE id = ?", (site_id,))
    return jsonify({"success": True, "message": "Website removed from monitoring."})


@app.route("/api/websites/<int:site_id>/interval", methods=["PATCH"])
def update_interval(site_id):
    """Update the automatic check interval for a website."""
    data = request.get_json() or {}
    try:
        interval = int(data.get("interval", 0))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Invalid interval."}), 400

    if interval not in ALLOWED_INTERVALS:
        return jsonify({"success": False, "error": f"Interval must be one of {ALLOWED_INTERVALS}."}), 400

    with get_db() as conn:
        site = conn.execute("SELECT id FROM websites WHERE id = ?", (site_id,)).fetchone()
        if not site:
            return jsonify({"success": False, "error": "Website not found."}), 404
        conn.execute("UPDATE websites SET check_interval = ? WHERE id = ?", (interval, site_id))

    label = f"{interval} min" if interval > 0 else "Manual only"
    return jsonify({"success": True, "message": f"Check interval set to {label}."})


@app.route("/api/websites/<int:site_id>/history", methods=["GET"])
def get_history(site_id):
    """Return the last 20 check history entries for a website."""
    with get_db() as conn:
        site = conn.execute("SELECT name, url FROM websites WHERE id = ?", (site_id,)).fetchone()
        if not site:
            return jsonify({"success": False, "error": "Website not found."}), 404
        rows = conn.execute(
            "SELECT * FROM change_history WHERE website_id = ? ORDER BY id DESC LIMIT 20",
            (site_id,),
        ).fetchall()

    return jsonify({
        "success": True,
        "website": dict(site),
        "history": [dict(r) for r in rows],
    })


# ==========================================
# 5. Background Scheduler
# ==========================================

def scheduler_loop(stop_event):
    """
    Background thread: wakes every 60 seconds and checks websites that are
    past their scheduled check_interval. Runs inside its own thread so the
    Flask server stays responsive.
    """
    while not stop_event.is_set():
        try:
            with get_db() as conn:
                sites = conn.execute(
                    "SELECT * FROM websites WHERE check_interval > 0"
                ).fetchall()

            now = datetime.now()
            for site in sites:
                try:
                    # Decide if this site is due for a check
                    last = site["last_checked"]
                    if last:
                        last_dt = datetime.strptime(last, "%Y-%m-%d %H:%M:%S")
                        next_dt = last_dt + timedelta(minutes=site["check_interval"])
                        if next_dt > now:
                            continue  # Not due yet

                    # Run the check (reuses same function as manual checks)
                    status, msg, chash, snippet, diff = detect_changes(
                        site["url"], site["last_hash"], site["last_snippet"]
                    )
                    checked_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    with get_db() as conn:
                        conn.execute(
                            "UPDATE websites SET last_status=?, last_message=?, last_checked=?, last_hash=?, last_snippet=? WHERE id=?",
                            (status, msg, checked_at, chash, snippet, site["id"]),
                        )
                        # Only save history when content actually changed or errored
                        if status != "No Change":
                            conn.execute(
                                "INSERT INTO change_history (website_id, status, summary, diff_snippet, checked_at) VALUES (?,?,?,?,?)",
                                (site["id"], status, msg, diff, checked_at),
                            )
                    print(f"[Scheduler] Checked '{site['name']}' → {status}")

                except Exception as e:
                    print(f"[Scheduler] Error checking '{site['name']}': {e}")

        except Exception as e:
            print(f"[Scheduler] Loop error: {e}")

        # Sleep in 1-second increments so we can stop quickly
        for _ in range(60):
            if stop_event.is_set():
                break
            time.sleep(1)

    print("[Scheduler] Stopped.")


def start_scheduler():
    """
    Start the background scheduler thread. Uses an environment variable
    guard so Flask's debug-mode reloader doesn't create duplicate threads.
    """
    # In debug mode, Flask runs the app twice (reloader + actual).
    # Only start the scheduler in the actual process (not the reloader).
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true" and app.debug:
        return

    if os.environ.get("SCHEDULER_STARTED"):
        return
    os.environ["SCHEDULER_STARTED"] = "1"

    stop_event = threading.Event()
    thread = threading.Thread(target=scheduler_loop, args=(stop_event,), daemon=True)
    thread.start()
    atexit.register(stop_event.set)
    print("[Scheduler] Background scheduler started (checks every 60 seconds).")


if __name__ == "__main__":
    init_db()
    start_scheduler()
    print("Website Change Detector running at http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=True)

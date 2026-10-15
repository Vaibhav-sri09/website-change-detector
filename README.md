# 🌐 Website Change Detector

A beginner-friendly web app built with **Python Flask**, **SQLite**, and **Vanilla JavaScript**. Monitor public webpages, extract their readable text, and detect when content changes between checks.

---

## 🎯 Features

1. **Responsive Dark Dashboard** — Clean, professional design with stat counters and status badges.
2. **Add & Monitor Websites** — Enter a name and public URL to start monitoring.
3. **SQLite Persistence** — Websites and check history are saved to a local database file.
4. **Text Extraction** — Fetches HTML, strips scripts/styles, and extracts readable text using BeautifulSoup.
5. **Change Detection** — Compares SHA-256 content hashes; avoids duplicate snapshots when content hasn't changed.
6. **Diff Viewer** — Shows color-coded unified diffs of what changed.
7. **Manual Check** — Re-scan any website on demand.
8. **Delete Websites** — Remove a site and its history from monitoring.
9. **Error Handling** — Clear messages for invalid URLs, timeouts, DNS failures, and HTTP errors.
10. **SSRF Protection** — Blocks requests to localhost, private IPs, and internal networks.

---

## 📂 Project Structure

```text
webvinnit/
├── app.py              # Flask backend: routes, scraping, security, database
├── templates/
│   └── index.html      # Dashboard HTML
├── static/
│   ├── style.css       # Dark theme styles
│   └── script.js       # Frontend JavaScript (API calls, DOM updates)
├── requirements.txt    # Python dependencies
├── README.md           # This file
└── .gitignore          # Ignores database, bytecode, virtualenvs
```

The SQLite database (`change_detector.db`) is created automatically at runtime and excluded from Git.

---

## 🚀 Quick Start

### 1. Install Dependencies
```bash
python -m pip install -r requirements.txt
```

### 2. Start the App
```bash
python app.py
```

### 3. Open in Browser
```
http://127.0.0.1:5000
```

---

## 🧪 How to Test

### Adding a Website
1. Click **+ Add Website**.
2. Enter a name and URL (e.g. `Example Domain` / `https://example.com`), or use the quick preset.
3. Click **Start Monitoring** — a baseline scan runs immediately.

### Detecting Changes
1. Click **🔄 Check** on any monitored website.
2. If the content has changed since the last check, the status updates to **Changed**.
3. Click **📜 History** to see a timeline with color-coded diffs.

### Testing Error Handling
- Try a private IP (e.g. `http://192.168.1.1`) — blocked by SSRF protection.
- Try a fake domain (e.g. `https://thisdomainwillneverexist12345.com`) — shows a connection error.
- Try `http://localhost/admin` — blocked for security.

---

## 🔒 Security

- URLs are validated before any HTTP request is made.
- Localhost, private IPs (`10.x`, `172.16.x`, `192.168.x`), and cloud metadata endpoints are blocked.
- Requests have an 8-second timeout and a 2MB response size limit.
- All user input is escaped in HTML output (XSS prevention).
- The database file and secrets are excluded from version control.

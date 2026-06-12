# Venmo OSINT

A tool for locating and extracting public Venmo profile data. Supports both a CLI and a dark-themed web GUI. Only accesses information Venmo makes publicly available.

Live demo: [venmo-osint.vercel.app](https://venmo-osint.vercel.app)

---

## Features

- **Profile lookup** — username, display name, first/last name, user ID, bio, account type, member since, friend count, avatar
- **Name search** — find accounts by first + last name using DuckDuckGo indexing + 34 username pattern probes (including `First-Last-N` auto-generated variants up to any number)
- **Keyword/username search** — search Venmo's user index
- **Public transactions** — pulls a profile's recent public payment feed (who paid whom, note, date, direction) from Venmo's stories API. **Requires a valid session cookie.**
- **Export** — download results as JSON, TXT, CSV, or a structured PDF (with embedded profile photo), or copy to clipboard
- **Session cookie support** — paste or auto-grab your Venmo cookie to unlock transactions and keyword search
- **Mobile-friendly** — bottom nav bar, stacked inputs, responsive layout
- **Hosted + local** — deploy to Vercel or run locally

---

## Quickstart

### Local web GUI

```bash
git clone https://github.com/denniskeefe/venmo-osint.git
cd venmo-osint
pip3 install -r requirements.txt
python3 app.py
```

Opens automatically at `http://127.0.0.1:5050`.

### CLI

```bash
pip3 install -r requirements.txt

# Look up a profile
python3 venmo_osint.py profile venmo

# Search by name
python3 venmo_osint.py name John Smith

# Search by keyword
python3 venmo_osint.py search john

# Output as JSON
python3 venmo_osint.py -f json profile venmo
```

---

## Session Cookie (optional)

A Venmo session cookie unlocks keyword search and exposes more transaction data. Without one, profile lookup and name search still work.

### Auto-grab (local only)

In the web GUI → **Cookie / Auth** → **Grab from Browser**. Reads your Chrome, Firefox, or Brave cookie store directly.

### Manual

1. Log in to [venmo.com](https://venmo.com) in Chrome
2. Open DevTools → Network tab → reload the page
3. Click any `venmo.com` request → Headers → copy the `Cookie:` value
4. Paste it in the GUI or pass via `--cookie`

**Cookie priority (highest first):**
1. `--cookie` CLI flag
2. `VENMO_COOKIE` environment variable
3. `~/.venmo_osint` config file (saved automatically, `chmod 600`)

---

## Name Search

Runs three strategies concurrently:

| Strategy | How it works |
|---|---|
| DuckDuckGo | `site:venmo.com/u "First Last"` — finds indexed public profiles |
| Pattern probing | 34 username variants (`johnsmith`, `john.smith`, `jsmith`, `johnsmith1`, etc.) probed in parallel with 15 workers |
| Dash-number scan | `First-Last-1`, `First-Last-2`, … scanned in batches of 10 until an entire batch returns 404 — finds Venmo auto-generated usernames like `Chris-Keefe-10` regardless of how high the number goes |

---

## Public Transactions

Each profile lookup attempts to pull the account's recent **public** payment feed — actor, target, note, date, and direction (paid vs. charged).

- Source: `api.venmo.com/v1/stories/target-or-actor/<user_id>`
- **Requires a valid session cookie.** Venmo removed the global public feed in 2021; viewing even public transactions now requires being logged in. Without a cookie (or with an expired one), the tool shows a prompt to add/refresh your cookie rather than a misleading "no transactions" message.
- Only data the target has marked **public** is returned; private transactions are never accessible.

---

## Export

After a profile lookup, an export bar appears below the result:

| Format | Contents |
|---|---|
| **JSON** | Full raw data object |
| **TXT** | Human-readable report with all fields and transactions |
| **CSV** | Spreadsheet-ready rows, one per field + one per transaction |
| **PDF** | Structured report with embedded profile photo, field table, and transaction list |
| **Copy** | JSON to clipboard |

Files are named `venmo_<username>_<date>.<ext>`. PDF and photo embedding use a same-origin image proxy (`/api/image-proxy`) to avoid browser CORS restrictions on Venmo's CDN.

---

## Deployment (Vercel)

```bash
vercel deploy
```

`vercel.json` routes all traffic through `api/index.py`. A slimmed `requirements-vercel.txt` is used (excludes `browser-cookie3` which requires native libs unavailable in serverless).

To use a session cookie on Vercel: add `VENMO_COOKIE` as an environment variable in your Vercel project settings.

> **Note:** Grab from Browser is disabled on the hosted version — it requires local filesystem access to your browser profile.

---

## Rate Limiting

Venmo throttles IPs that make many requests in a short window. If you see:

> *Venmo is rate-limiting this IP — please wait a few minutes and try again.*

Wait 15–30 minutes before retrying. To avoid triggering the limit, test with single profile lookups before running name searches.

---

## Project Structure

```
venmo_osint.py        # Core library + CLI
app.py                # Flask web GUI (local)
api/index.py          # Vercel serverless adapter
requirements.txt      # Full deps (local)
requirements-vercel.txt  # Slim deps (Vercel, no browser-cookie3)
vercel.json           # Vercel routing config
```

---

## Legal

This tool only accesses data Venmo makes publicly available. Do not use it to harass, stalk, or harm individuals. You are responsible for complying with Venmo's Terms of Service and applicable laws.

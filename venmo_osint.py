#!/usr/bin/env python3
"""
Venmo OSINT Tool — locates and extracts public Venmo profile data.
Only accesses information that Venmo makes publicly available.

Cookie support
--------------
A Venmo session cookie unlocks the search endpoint and exposes more
transaction data on private-ish profiles. You can provide it three ways
(highest priority first):

  1. CLI flag:        --cookie "venmo_device_id=abc; _venmoid=xyz; ..."
  2. Env variable:    VENMO_COOKIE="..."
  3. Config file:     ~/.venmo_osint  (one line: cookie = <value>)

To grab your cookie: log in to venmo.com in Chrome → DevTools →
Application → Cookies → copy the full "Cookie" request header value from
any venmo.com network request.
"""

import argparse
import configparser
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Config / cookie resolution
# ---------------------------------------------------------------------------

CONFIG_PATH = Path.home() / ".venmo_osint"


def load_saved_cookie() -> Optional[str]:
    """Read cookie from ~/.venmo_osint if it exists."""
    if not CONFIG_PATH.exists():
        return None
    cfg = configparser.RawConfigParser()
    cfg.read(CONFIG_PATH)
    return cfg.get("venmo", "cookie", fallback=None) or None


def save_cookie(cookie: str):
    """Persist a cookie to ~/.venmo_osint."""
    # RawConfigParser avoids treating % in cookie values as interpolation syntax
    cfg = configparser.RawConfigParser()
    if CONFIG_PATH.exists():
        cfg.read(CONFIG_PATH)
    if "venmo" not in cfg:
        cfg["venmo"] = {}
    cfg["venmo"]["cookie"] = cookie
    with open(CONFIG_PATH, "w") as f:
        cfg.write(f)
    CONFIG_PATH.chmod(0o600)
    print(f"[✓] Cookie saved to {CONFIG_PATH}")


def clear_cookie():
    """Remove cookie from ~/.venmo_osint."""
    if not CONFIG_PATH.exists():
        print("No config file found — nothing to clear.")
        return
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH)
    if cfg.has_option("venmo", "cookie"):
        cfg.remove_option("venmo", "cookie")
        with open(CONFIG_PATH, "w") as f:
            cfg.write(f)
        print(f"[✓] Cookie cleared from {CONFIG_PATH}")
    else:
        print("No cookie stored.")


def resolve_cookie(cli_cookie: Optional[str]) -> Optional[str]:
    """Return the best available cookie: CLI > env > config file."""
    return (
        cli_cookie
        or os.environ.get("VENMO_COOKIE")
        or load_saved_cookie()
    )


# ---------------------------------------------------------------------------
# HTTP session
# ---------------------------------------------------------------------------

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def apply_cookie(cookie_str: str):
    """Parse a raw Cookie header string and inject it into the session."""
    for pair in cookie_str.split(";"):
        pair = pair.strip()
        if "=" in pair:
            name, _, value = pair.partition("=")
            SESSION.cookies.set(name.strip(), value.strip(), domain=".venmo.com")


# ---------------------------------------------------------------------------
# Profile lookup
# ---------------------------------------------------------------------------

def fetch_profile(username: str) -> dict:
    """
    Fetch public profile data for a Venmo username.

    Strategy (in order):
      1. api.venmo.com/v1/users/<username>  — always reliable, no auth needed
      2. account.venmo.com/u/<username>     — richer (transactions) when a
                                              session cookie is present; also
                                              used to merge extra fields
    """
    username = username.strip().lstrip("@")

    # ── Strategy 1: public REST API (fast, no cookie needed) ─────────────────
    base = _fetch_api_profile(username)

    # ── Strategy 2: scrape account page (richer data; also handles usernames
    #    like First-Last-N that the REST API doesn't resolve) ─────────────────
    scraped = _fetch_scraped_profile(username)

    if "error" not in base:
        # Merge: prefer API for identity fields, scrape for transactions/bio
        if "error" not in scraped:
            base["bio"]                = scraped.get("bio") or base.get("bio")
            base["is_business"]        = scraped.get("is_business") or base.get("is_business")
            base["recent_transactions"]= scraped.get("recent_transactions", [])
            base["transactions_note"]  = scraped.get("transactions_note")
            base["friend_count"]       = scraped.get("friend_count", base.get("friend_count"))
        return base

    if "error" not in scraped:
        # API failed (404 or rate-limited) but scrape worked — use scrape only
        return scraped

    # Both failed — return whichever error is more informative
    # Prefer a hard 404 from scrape over a generic API error
    return scraped if "404" in scraped.get("error", "") else base


def _fetch_api_profile(username: str) -> dict:
    """Call api.venmo.com/v1/users/<username> — no auth needed for public data."""
    try:
        resp = SESSION.get(
            f"https://api.venmo.com/v1/users/{username}",
            timeout=12,
        )
    except requests.RequestException as exc:
        return {"error": str(exc)}

    if resp.status_code == 404:
        # Real 404 = JSON body; HTML body = rate-limited / IP blocked
        ct = resp.headers.get("content-type", "")
        if "html" in ct or resp.text.strip().startswith("<"):
            return {"error": "rate_limited"}
        return {"error": f"User '{username}' not found (404)"}
    if resp.status_code == 429:
        return {"error": "rate_limited"}
    if resp.status_code != 200:
        return {"error": f"API HTTP {resp.status_code}"}

    try:
        u = resp.json().get("data", {})
        if not u:
            return {"error": "Empty API response"}

        # Detect business vs personal
        identity = u.get("identity_type", "")
        is_business = "business" in identity.lower() if identity else None

        return {
            "username":            u.get("username") or username,
            "display_name":        u.get("display_name"),
            "first_name":          u.get("first_name"),
            "last_name":           u.get("last_name", "").strip() or None,
            "id":                  u.get("id"),
            "profile_picture_url": u.get("profile_picture_url"),
            "bio":                 u.get("about") or u.get("description"),
            "is_business":         is_business,
            "identity_type":       identity or None,
            "date_joined":         u.get("date_joined"),
            "friend_count":        None,   # not in API response
            "profile_url":         f"https://venmo.com/{u.get('username') or username}",
            "recent_transactions": [],
        }
    except (json.JSONDecodeError, KeyError, AttributeError) as exc:
        return {"error": f"API parse error: {exc}"}


def _fetch_scraped_profile(username: str) -> dict:
    """Scrape account.venmo.com for friend count, transactions, and bio."""
    url = f"https://account.venmo.com/u/{username}"
    try:
        resp = SESSION.get(url, timeout=15)
    except requests.RequestException as exc:
        return {"error": str(exc)}

    if resp.status_code == 404:
        return {"error": f"User '{username}' not found (404)"}
    if resp.status_code == 403:
        return {"error": "Access denied (bot detection) — add a session cookie for reliable scraping"}
    if resp.status_code != 200:
        return {"error": f"HTTP {resp.status_code}"}

    soup = BeautifulSoup(resp.text, "html.parser")
    nd_tag = soup.find("script", id="__NEXT_DATA__")
    if not nd_tag or not nd_tag.string:
        return {"error": "Page loaded but __NEXT_DATA__ missing — Venmo may be rate-limiting this IP"}

    try:
        data  = json.loads(nd_tag.string)
        props = data["props"]["pageProps"]
    except (json.JSONDecodeError, KeyError):
        return {"error": "Could not parse __NEXT_DATA__"}

    user = (
        props.get("profileData", {}).get("user")
        or props.get("user")            # logged-out page
        or props.get("otherUser")       # authenticated page (viewing someone else)
        or props.get("profileUser")
    )
    if not user:
        return {"error": "Profile data not found in page (account may be private or require login)"}

    # ── Transactions ─────────────────────────────────────────────────────────
    # Newer Venmo no longer embeds the feed in __NEXT_DATA__; it is fetched
    # client-side from the authenticated stories API. Try the embedded feed
    # first (older accounts), then fall back to the stories endpoint.
    transactions = []
    feed = (
        props.get("profileData", {}).get("transactions")
        or props.get("transactions")
        or []
    )
    for txn in feed[:20]:
        payment = txn.get("payment") if isinstance(txn.get("payment"), dict) else {}
        transactions.append({
            "id":     txn.get("id"),
            "date":   txn.get("datetime") or txn.get("date_created"),
            "note":   txn.get("note") or txn.get("message"),
            "type":   txn.get("type") or txn.get("action"),
            "actor":  _name(txn.get("actor")),
            "target": _name(payment.get("target") or txn.get("target")),
        })

    txn_note = None
    if not transactions and user.get("id"):
        transactions, auth_required = _fetch_user_stories(user["id"], referer=url)
        if auth_required:
            txn_note = (
                "Transactions require a valid Venmo session cookie. "
                "Add or refresh your cookie in the Cookie / Auth tab to view them."
            )

    # Derive display name — new structure has firstName/lastName separately
    display = (
        user.get("displayName")
        or user.get("name")
        or f"{user.get('firstName','')} {user.get('lastName','').strip()}".strip()
        or None
    )
    identity = user.get("identityType", "")
    is_business = (
        user.get("isBusiness")
        or ("business" in (identity or "").lower())
        or None
    )

    return {
        "username":            user.get("username") or username,
        "display_name":        display,
        "first_name":          user.get("firstName"),
        "last_name":           (user.get("lastName") or "").strip() or None,
        "id":                  user.get("id"),
        "profile_picture_url": user.get("profilePictureUrl") or user.get("picture"),
        "bio":                 user.get("about") or user.get("description"),
        "is_business":         is_business,
        "identity_type":       identity or None,
        "is_active":           user.get("isActive"),
        "initials":            user.get("initials"),
        "friend_count":        user.get("friendCount"),
        "profile_url":         f"https://venmo.com/{user.get('username') or username}",
        "recent_transactions": transactions,
        "transactions_note":   txn_note,
    }


def _name(obj) -> Optional[str]:
    if not obj:
        return None
    if isinstance(obj, dict):
        return (
            obj.get("displayName")
            or obj.get("display_name")
            or obj.get("name")
            or obj.get("username")
        )
    return str(obj)


def _fetch_user_stories(user_id: str, referer: str = "https://account.venmo.com/") -> tuple[list[dict], bool]:
    """
    Fetch a user's public transaction feed from Venmo's stories API.

    Returns (transactions, auth_required). This endpoint requires a valid
    session cookie; without one it returns 401, in which case we return
    ([], True) so the caller can prompt the user to add a cookie.
    """
    api = f"https://api.venmo.com/v1/stories/target-or-actor/{user_id}"
    headers = {"Accept": "application/json", "Referer": referer}

    try:
        resp = SESSION.get(api, headers=headers, timeout=15)
    except requests.RequestException:
        return [], False

    if resp.status_code in (401, 403):
        return [], True       # session cookie missing or expired
    if resp.status_code != 200:
        return [], False      # 404/other — genuinely no feed

    try:
        payload = resp.json()
    except json.JSONDecodeError:
        return [], False

    stories = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(stories, list):
        return [], False
    return [_parse_story(s) for s in stories[:20] if isinstance(s, dict)], False


def _parse_story(s: dict) -> dict:
    """Normalize a single Venmo 'story' object into our transaction shape."""
    payment = s.get("payment") if isinstance(s.get("payment"), dict) else {}

    # actor = who initiated; target.user = the other party
    actor = _name(payment.get("actor")) or _name(s.get("actor"))

    target_obj = payment.get("target") if isinstance(payment.get("target"), dict) else {}
    target = _name(target_obj.get("user")) or _name(target_obj.get("merchant"))

    # Direction: "pay" = actor -> target; "charge" = actor requested from target
    action = payment.get("action") or s.get("type") or "pay"
    verb = {"pay": "paid", "charge": "charged"}.get(action, action)

    return {
        "id":       s.get("id"),
        "date":     s.get("date_created") or payment.get("date_created"),
        "note":     s.get("note") or payment.get("note"),
        "type":     verb,
        "actor":    actor,
        "target":   target,
        "audience": s.get("audience") or payment.get("audience"),
    }


# ---------------------------------------------------------------------------
# Name → username pattern generator
# ---------------------------------------------------------------------------

def username_patterns(first: str, last: str, top_only: bool = False) -> list[str]:
    """
    Generate likely Venmo username candidates from a first + last name.
    Returns a de-duplicated list preserving order.
    If top_only=True, returns only the highest-probability patterns (faster).
    """
    f  = first.lower().strip()
    l  = last.lower().strip()
    f1 = f[0] if f else ""
    l1 = l[0] if l else ""

    # Ordered by real-world frequency on Venmo
    top = [
        f"{f}{l}",        # johnsmith
        f"{f}.{l}",       # john.smith
        f"{f}_{l}",       # john_smith
        f"{f}-{l}",       # john-smith
        f"{f1}{l}",       # jsmith
        f"{f}{l1}",       # johns
    ]

    extended = top + [
        f"{l}{f}",        # smithjohn
        f"{l}.{f}",       # smith.john
        f"{l}_{f}",       # smith_john
        f"{l}-{f}",       # smith-john
        f"{f}",           # john
        f"{l}",           # smith
        f"{f}{l[:3]}",    # johnsmi
        f"{f1}{l1}",      # js
    ]

    # Number-suffix variants (catches johnsmith1, john.smith2, etc.)
    plain_suffixes = ["1", "2", "3", "123", "1234"]
    with_nums = []
    for base in top[:4]:
        for s in plain_suffixes:
            with_nums.append(f"{base}{s}")

    candidates = top if top_only else (extended + with_nums)
    seen = set()
    result = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            result.append(c)
    return result


# ---------------------------------------------------------------------------
# Name search via DuckDuckGo site:venmo.com/u
# ---------------------------------------------------------------------------

def search_by_name(first: str, last: str, limit: int = 10) -> list[dict]:
    """
    Search for Venmo profiles by first + last name using two strategies:
      1. DuckDuckGo site:venmo.com/u "<first last>" — finds indexed public profiles.
      2. Username pattern guessing — tries common derived usernames directly.

    Returns a merged, de-duplicated list of profile dicts quickly by
    running both strategies concurrently.
    """
    results: list[dict] = []
    seen_usernames: set[str] = set()
    lock = threading.Lock()

    def ddg_worker():
        for r in _ddg_name_search(first, last, limit):
            u = (r.get("username") or "").lower()
            with lock:
                if u and u not in seen_usernames and len(results) < limit:
                    seen_usernames.add(u)
                    results.append(r)

    def probe_pattern(pattern: str) -> Optional[dict]:
        """Fetch one pattern; return profile if the account exists, else None."""
        profile = fetch_profile(pattern)
        if "error" in profile:
            return None
        profile["_source"] = "pattern_guess"
        return profile

    def pattern_worker():
        patterns = username_patterns(first, last, top_only=False)
        with ThreadPoolExecutor(max_workers=15) as pool:
            futures = {pool.submit(probe_pattern, p): p for p in patterns}
            for future in as_completed(futures):
                profile = future.result()
                if profile:
                    uname = (profile.get("username") or "").lower()
                    with lock:
                        if uname and uname not in seen_usernames and len(results) < limit:
                            seen_usernames.add(uname)
                            results.append(profile)

    def dash_number_worker():
        """
        Probe First-Last-N for N = 1, 2, 3, … in concurrent batches.
        Each batch of BATCH_SIZE numbers is fired in parallel; we stop
        when an entire batch returns zero hits (no more accounts exist
        beyond that point). Handles gaps from deleted accounts.
        """
        BATCH_SIZE = 10         # concurrent probes per round
        MAX_N      = 200        # absolute safety cap
        base       = f"{first.lower().strip()}-{last.lower().strip()}"
        n          = 1

        while n <= MAX_N:
            with lock:
                if len(results) >= limit:
                    return

            batch = list(range(n, min(n + BATCH_SIZE, MAX_N + 1)))
            n    += BATCH_SIZE

            batch_hits = 0
            with ThreadPoolExecutor(max_workers=BATCH_SIZE) as pool:
                futs = {pool.submit(fetch_profile, f"{base}-{i}"): i for i in batch}
                for fut in as_completed(futs):
                    profile = fut.result()
                    if "error" not in profile:
                        batch_hits += 1
                        profile["_source"] = "pattern_guess"
                        uname = (profile.get("username") or "").lower()
                        with lock:
                            if uname and uname not in seen_usernames and len(results) < limit:
                                seen_usernames.add(uname)
                                results.append(profile)

            if batch_hits == 0:
                return      # entire window was empty — no point going further

    t1 = threading.Thread(target=ddg_worker)
    t2 = threading.Thread(target=pattern_worker)
    t3 = threading.Thread(target=dash_number_worker)
    t1.start(); t2.start(); t3.start()
    t1.join(); t2.join(); t3.join()

    if results:
        return results

    # Check if we were rate-limited rather than just no matches
    probe = _fetch_api_profile("venmo")
    if probe.get("error") == "rate_limited":
        return [{"error": "Venmo is rate-limiting this IP — please wait a few minutes and try again."}]

    return [{"note": "No results found. Try a different spelling or add a session cookie for Venmo search."}]


def _ddg_name_search(first: str, last: str, limit: int) -> list[dict]:
    """
    Scrape DuckDuckGo HTML for:  site:venmo.com/u "First Last"
    Returns partial profile dicts (username + display_name + profile_url).
    """
    query = f'site:venmo.com/u "{first} {last}"'
    url   = "https://html.duckduckgo.com/html/"
    try:
        resp = SESSION.post(url, data={"q": query, "b": "", "kl": "us-en"}, timeout=15)
    except requests.RequestException as exc:
        return [{"error": f"DuckDuckGo request failed: {exc}"}]

    if resp.status_code != 200:
        return [{"error": f"DuckDuckGo returned HTTP {resp.status_code}"}]

    soup   = BeautifulSoup(resp.text, "html.parser")
    hits   = soup.select(".result__url, .result__a")
    results = []

    for tag in soup.select(".result"):
        link_tag  = tag.select_one(".result__a")
        url_tag   = tag.select_one(".result__url")
        snip_tag  = tag.select_one(".result__snippet")

        href      = link_tag["href"] if link_tag and link_tag.get("href") else ""
        url_text  = url_tag.get_text(strip=True) if url_tag else href
        snippet   = snip_tag.get_text(strip=True) if snip_tag else ""
        title     = link_tag.get_text(strip=True) if link_tag else ""

        # Extract username from URL like venmo.com/u/username
        username = _extract_username_from_url(href or url_text)
        if not username:
            continue

        results.append({
            "username":         username,
            "display_name":     title or f"{first} {last}",
            "profile_url":      f"https://venmo.com/u/{username}",
            "snippet":          snippet,
            "_source":          "duckduckgo",
        })
        if len(results) >= limit:
            break

    return results


def _extract_username_from_url(url: str) -> Optional[str]:
    """Pull the username out of a venmo.com/u/<username> URL or text."""
    import re
    m = re.search(r"venmo\.com/u/([A-Za-z0-9_\-\.]+)", url)
    if m:
        return m.group(1)
    # Also handle old-style venmo.com/<username>
    m2 = re.search(r"venmo\.com/([A-Za-z0-9_\-\.]+)(?:[/?]|$)", url)
    if m2 and m2.group(1) not in ("u", "business", "about", "blog", "legal", "help"):
        return m2.group(1)
    return None


# ---------------------------------------------------------------------------
# Search (keyword — requires cookie for full results)
# ---------------------------------------------------------------------------

def search_users(query: str, limit: int = 10) -> list[dict]:
    """Search Venmo for users matching *query* via the web search page."""
    url = "https://account.venmo.com/search"
    params = {"query": query, "searchType": "users", "pageSize": min(limit, 20)}
    try:
        resp = SESSION.get(url, params=params, timeout=15)
    except requests.RequestException as exc:
        return [{"error": str(exc)}]

    if resp.status_code != 200:
        return [{"error": f"HTTP {resp.status_code} — try adding a session cookie (see --help)"}]

    soup = BeautifulSoup(resp.text, "html.parser")
    next_data_tag = soup.find("script", id="__NEXT_DATA__")
    if not next_data_tag:
        return [{"error": "Could not parse search results (__NEXT_DATA__ missing)"}]

    try:
        data = json.loads(next_data_tag.string)
        pp = data.get("props", {}).get("pageProps", {})
        users_raw = (
            pp.get("users")
            or pp.get("searchResults", {}).get("users")
            or []
        )
        results = []
        for u in users_raw[:limit]:
            results.append({
                "username": u.get("username"),
                "display_name": u.get("displayName") or u.get("name"),
                "id": u.get("id"),
                "profile_picture_url": u.get("profilePictureUrl") or u.get("picture"),
                "profile_url": f"https://venmo.com/{u.get('username')}",
            })
        if not results:
            hint = "" if SESSION.cookies else " (tip: add a session cookie for better results)"
            return [{"note": f"No results returned{hint}."}]
        return results
    except (json.JSONDecodeError, KeyError) as exc:
        return [{"error": f"Parse error: {exc}"}]


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def print_profile(p: dict, fmt: str):
    if fmt == "json":
        print(json.dumps(p, indent=2))
        return

    if "error" in p:
        print(f"[ERROR] {p['error']}")
        return

    print("\n" + "=" * 60)
    print(f"  Venmo Profile: @{p.get('username', '?')}")
    print("=" * 60)
    _row("Display name",       p.get("display_name"))
    _row("First name",         p.get("first_name"))
    _row("Last name",          p.get("last_name"))
    _row("User ID",            p.get("id"))
    _row("Bio",                p.get("bio"))
    _row("Account type",       p.get("identity_type") or ("Business" if p.get("is_business") else None))
    _row("Active",             "No (deactivated)" if p.get("is_active") is False else None)
    _row("Member since",       p.get("date_joined"))
    _row("Friend count",       p.get("friend_count"))
    _row("Profile URL",        p.get("profile_url"))
    _row("Avatar",             p.get("profile_picture_url"))

    txns = p.get("recent_transactions", [])
    if txns:
        print(f"\n  Recent public transactions ({len(txns)}):")
        for t in txns:
            actor  = t.get("actor")  or "?"
            target = t.get("target") or "?"
            note   = t.get("note")   or "(no note)"
            date   = (t.get("date") or "")[:10]
            action = t.get("type")   or "paid"
            print(f"    [{date}] {actor} {action} {target}: \"{note}\"")
    else:
        print("\n  No public transactions visible.")

    if "note" in p:
        print(f"\n  ℹ {p['note']}")
    print()


def print_search_results(results: list[dict], fmt: str):
    if fmt == "json":
        print(json.dumps(results, indent=2))
        return

    if not results:
        print("No results found.")
        return

    print(f"\n{'='*60}")
    print(f"  Search results ({len(results)} found)")
    print(f"{'='*60}")
    for r in results:
        if "error" in r:
            print(f"  [ERROR] {r['error']}")
        elif "note" in r:
            print(f"  [NOTE] {r['note']}")
        else:
            print(f"  @{r.get('username','?')} — {r.get('display_name','?')}")
            print(f"    ID: {r.get('id','?')}  |  {r.get('profile_url','')}")
    print()


def _row(label: str, value):
    if value not in (None, "", False):
        print(f"  {label:<22} {value}")


def cookie_status() -> str:
    saved = load_saved_cookie()
    env   = os.environ.get("VENMO_COOKIE")
    if env:
        return f"active (VENMO_COOKIE env var, {len(env)} chars)"
    if saved:
        return f"active (saved in {CONFIG_PATH}, {len(saved)} chars)"
    return "not set — search will be limited"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="venmo_osint",
        description=(
            "OSINT tool for public Venmo profile data.\n\n"
            "Cookie sources (highest priority first):\n"
            "  --cookie flag  →  VENMO_COOKIE env var  →  ~/.venmo_osint config file\n\n"
            "To grab a cookie: log into venmo.com, open DevTools (F12) → Network tab,\n"
            "click any request to venmo.com, copy the 'Cookie:' request header value."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "-f", "--format", choices=["text", "json"], default="text",
        help="Output format (default: text)",
    )
    p.add_argument(
        "--cookie", metavar="COOKIE_STRING",
        help="Raw Cookie header string (e.g. 'venmo_device_id=abc; _venmoid=xyz')",
    )

    sub = p.add_subparsers(dest="command", required=True)

    # --- profile ---
    prof = sub.add_parser("profile", help="Look up one or more profiles by username")
    prof.add_argument("usernames", nargs="+", metavar="USERNAME")
    prof.add_argument(
        "--delay", type=float, default=1.0,
        help="Seconds between requests for multiple usernames (default: 1.0)",
    )

    # --- search ---
    srch = sub.add_parser("search", help="Search for users by keyword (cookie recommended)")
    srch.add_argument("query", metavar="QUERY")
    srch.add_argument("--limit", type=int, default=10, metavar="N")

    # --- name ---
    name = sub.add_parser("name", help="Search by first + last name (no cookie needed)")
    name.add_argument("first", metavar="FIRST")
    name.add_argument("last",  metavar="LAST")
    name.add_argument("--limit", type=int, default=10, metavar="N")
    name.add_argument("--full", action="store_true",
                      help="Fetch full profile for each result (slower)")

    # --- cookie management ---
    ck = sub.add_parser("cookie", help="Manage your saved session cookie")
    ck_sub = ck.add_subparsers(dest="cookie_cmd", required=True)

    ck_save = ck_sub.add_parser("save", help="Save a cookie to ~/.venmo_osint for future runs")
    ck_save.add_argument("value", metavar="COOKIE_STRING")

    ck_sub.add_parser("clear", help="Remove the saved cookie from ~/.venmo_osint")
    ck_sub.add_parser("status", help="Show whether a cookie is currently configured")

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()

    # --- cookie sub-commands don't need a session ---
    if args.command == "cookie":
        if args.cookie_cmd == "save":
            save_cookie(args.value)
        elif args.cookie_cmd == "clear":
            clear_cookie()
        elif args.cookie_cmd == "status":
            print(f"Cookie status: {cookie_status()}")
        return

    # Resolve and apply cookie for all other commands
    cookie = resolve_cookie(getattr(args, "cookie", None))
    if cookie:
        apply_cookie(cookie)

    if args.command == "profile":
        for i, username in enumerate(args.usernames):
            if i > 0:
                time.sleep(args.delay)
            profile = fetch_profile(username)
            print_profile(profile, args.format)

    elif args.command == "search":
        results = search_users(args.query, limit=args.limit)
        print_search_results(results, args.format)

    elif args.command == "name":
        results = search_by_name(args.first, args.last, limit=args.limit)
        if args.full:
            full_results = []
            for r in results:
                if "username" in r and "error" not in r and "note" not in r:
                    full_results.append(fetch_profile(r["username"]))
                    time.sleep(0.8)
                else:
                    full_results.append(r)
            results = full_results
        print_search_results(results, args.format)


if __name__ == "__main__":
    main()

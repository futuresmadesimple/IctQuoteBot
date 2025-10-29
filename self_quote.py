#!/usr/bin/env python3
"""
self_quote.py — Daily self-quote without reads.

- Picks ONE older tweet ID from posted.jsonl (your write-only log)
- Skips the N most recent posts (default 8) and prefers items older than MIN_AGE_HOURS
- Posts a quote-tweet with a short intro
Env knobs (optional):
  SELFQUOTE_SKIP_RECENT (int, default 8)
  SELFQUOTE_MIN_AGE_HOURS (int, default 36)
Requires env secrets: X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET
"""

from __future__ import annotations
import os, json, random
from pathlib import Path
from zoneinfo import ZoneInfo
from datetime import datetime
from dateutil.parser import parse as parse_dt
import tweepy

POSTED_JSONL = Path("posted.jsonl")
ET = ZoneInfo("America/New_York")

SKIP_RECENT = int(os.getenv("SELFQUOTE_SKIP_RECENT", "8"))
MIN_AGE_HOURS = int(os.getenv("SELFQUOTE_MIN_AGE_HOURS", "36"))

INTRO = [
    "Worth another read:",
    "Daily reminder:",
    "Save this one:",
]

def get_writer_client() -> tweepy.Client:
    ck  = os.getenv("X_API_KEY")
    cs  = os.getenv("X_API_SECRET")
    at  = os.getenv("X_ACCESS_TOKEN")
    ats = os.getenv("X_ACCESS_SECRET")  # NOTE: token *secret* name
    if not all([ck, cs, at, ats]):
        raise RuntimeError("Missing writer creds (X_API_KEY/SECRET + X_ACCESS_TOKEN/SECRET).")
    return tweepy.Client(
        consumer_key=ck,
        consumer_secret=cs,
        access_token=at,
        access_token_secret=ats,
        wait_on_rate_limit=False,
        bearer_token=os.getenv("X_BEARER_TOKEN"),  # optional
    )

def read_posted_jsonl() -> list[dict]:
    if not POSTED_JSONL.exists():
        return []
    rows: list[dict] = []
    for line in POSTED_JSONL.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
    return rows

def eligible_pool(rows: list[dict]) -> list[dict]:
    """Return rows excluding the most recent N and filtering by min age if available."""
    if len(rows) <= SKIP_RECENT:
        return []
    older = rows[:-SKIP_RECENT]
    if MIN_AGE_HOURS <= 0:
        return [r for r in older if str(r.get("id", "")).isdigit()]
    cutoff = datetime.now(ET).timestamp() - (MIN_AGE_HOURS * 3600)
    pool: list[dict] = []
    for r in older:
        tid = str(r.get("id", ""))
        if not tid.isdigit():
            continue
        et_str = r.get("et", "")
        try:
            ts = parse_dt(et_str).timestamp()
        except Exception:
            # if we can't parse, still allow it (it's old because it's not in the last N)
            pool.append(r)
            continue
        if ts <= cutoff:
            pool.append(r)
    return pool

def main() -> int:
    rows = read_posted_jsonl()
    pool = eligible_pool(rows)
    if not pool:
        print("Self-quote: not enough eligible history yet.")
        return 0

    pick = random.choice(pool)
    tid = str(pick["id"])
    intro = random.choice(INTRO)

    client = get_writer_client()
    resp = client.create_tweet(text=intro, quote_tweet_id=tid)
    print(f"Quoted id: {tid} -> {getattr(resp, 'data', {})}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

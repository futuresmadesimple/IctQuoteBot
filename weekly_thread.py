#!/usr/bin/env python3
"""
weekly_thread.py — Post one mini-thread from threads.txt.

- threads.txt is split into blocks by lines that are exactly '---'
- Each non-empty line inside a block becomes one tweet (max 5)
- Truncates each line to 280 chars (hard cap)
- Remembers last-used block in .thread_state.json and cycles next run
- Uses writer-only creds (no read endpoints)

Env (optional):
  THREADS_FILE           default: threads.txt
  THREAD_MAX_TWEETS      default: 5
  THREAD_STATE_FILE      default: .thread_state.json
"""

from __future__ import annotations
import os, json
from pathlib import Path
from typing import List
import tweepy

THREADS_FILE = Path(os.getenv("THREADS_FILE", "threads.txt"))
STATE_FILE   = Path(os.getenv("THREAD_STATE_FILE", ".thread_state.json"))
MAX_TWEETS   = int(os.getenv("THREAD_MAX_TWEETS", "5"))

def get_writer_client() -> tweepy.Client:
    ck  = os.getenv("X_API_KEY")
    cs  = os.getenv("X_API_SECRET")
    at  = os.getenv("X_ACCESS_TOKEN")
    ats = os.getenv("X_ACCESS_SECRET")
    if not all([ck, cs, at, ats]):
        raise RuntimeError("Missing writer creds (X_API_KEY/SECRET + X_ACCESS_TOKEN + X_ACCESS_SECRET).")
    return tweepy.Client(
        consumer_key=ck, consumer_secret=cs,
        access_token=at, access_token_secret=ats,
        wait_on_rate_limit=False,
        bearer_token=os.getenv("X_BEARER_TOKEN")  # optional
    )

def load_blocks(path: Path) -> List[List[str]]:
    if not path.exists():
        raise FileNotFoundError(f"{path} not found.")
    raw = path.read_text(encoding="utf-8")
    blocks: List[List[str]] = []
    for chunk in raw.split("\n---\n"):
        lines = [ln.strip() for ln in chunk.splitlines() if ln.strip()]
        if lines:
            # enforce 280 and cap per-thread tweet count
            lines = [ln[:280] for ln in lines][:MAX_TWEETS]
            blocks.append(lines)
    if not blocks:
        raise ValueError("No thread blocks found (use '---' separators).")
    return blocks

def load_state() -> dict:
    if STATE_FILE.exists():
        try: return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception: pass
    return {"idx": -1}

def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")

def next_index(n: int, state: dict) -> int:
    cur = int(state.get("idx", -1))
    return (cur + 1) % n

def post_thread(lines: List[str]) -> None:
    client = get_writer_client()
    first = client.create_tweet(text=lines[0])
    prev_id = str(first.data["id"])
    print(f"Thread first tweet id={prev_id}: {lines[0]}")
    for ln in lines[1:]:
        r = client.create_tweet(text=ln, in_reply_to_tweet_id=prev_id)
        prev_id = str(r.data["id"])
        print(f"…replied id={prev_id}: {ln}")

def main() -> int:
    blocks = load_blocks(THREADS_FILE)
    state = load_state()
    idx = next_index(len(blocks), state)
    lines = blocks[idx]
    print(f"Weekly Thread: using block {idx+1}/{len(blocks)} with {len(lines)} tweets.")
    post_thread(lines)
    state["idx"] = idx
    save_state(state)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

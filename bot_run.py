#!/usr/bin/env python3
"""
bot_run.py — Post-only bot (12/day), RANDOM block selection.

- `tweets.txt` is split into blocks by lines that are exactly `---`.
- When a block is posted OR judged a duplicate by the API, that entire block
  (and one adjacent separator) is removed from `tweets.txt`.
- Picks a **random block** each time a slot is due.
- Plans **12 random ET slots once per day** (07:00–22:00), with a +30 min posting window.
- State is stored in `.post_state.json` (planned slots, posted slots, simple log).
- Fix: the “Next:” display shows the next **future** slot, not the first unposted one.
"""
from __future__ import annotations
import os, json, random, subprocess, sys
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# ---- Config & paths ----
ET = ZoneInfo("America/New_York")
def now_et() -> datetime: return datetime.now(ET)

POSTED_FILE = Path("posted_tweets.txt")
TWEETS_FILE = Path(os.getenv("TWEETS_FILE", "tweets.txt"))
POST_STATE  = Path(os.getenv("POST_STATE_FILE", ".post_state.json"))
SLOTS_PER_DAY = int(os.getenv("SLOTS_PER_DAY", "6"))
START_HOUR    = int(os.getenv("START_HOUR", "6"))
END_HOUR      = int(os.getenv("END_HOUR", "23"))
WINDOW_MIN    = int(os.getenv("WINDOW_MIN", "40"))

# ---- Tweepy ensure & writer client ----
def _ensure_tweepy():
    try:
        import tweepy  # type: ignore
        return tweepy
    except ModuleNotFoundError:
        print("tweepy not found — installing...", flush=True)
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "tweepy>=4.14.0"])
        import tweepy  # type: ignore
        return tweepy

def get_writer_client():
    tweepy = _ensure_tweepy()
    ck  = os.getenv("X_API_KEY")
    cs  = os.getenv("X_API_SECRET")
    at  = os.getenv("X_ACCESS_TOKEN")
    ats = os.getenv("X_ACCESS_SECRET")
    if not all([ck, cs, at, ats]):
        raise RuntimeError("Missing writer creds (X_API_KEY/SECRET + X_ACCESS_TOKEN/SECRET).")
    return tweepy.Client(consumer_key=ck, consumer_secret=cs, access_token=at, access_token_secret=ats, wait_on_rate_limit=False)

# ---- File IO helpers ----
def read_lines(path: Path) -> List[str]:
    if not path.exists():
        raise FileNotFoundError(f"{path} not found.")
    return path.read_text(encoding="utf-8").splitlines()

def write_lines(path: Path, lines: List[str]) -> None:
    text = "\n".join(lines).rstrip() + ("\n" if lines else "")
    path.write_text(text, encoding="utf-8")

def append_posted(raw_block: List[str], *, status: str, tweet_id: Optional[str] = None) -> None:
    ts = now_et().strftime("%Y-%m-%d %H:%M:%S %Z")
    with POSTED_FILE.open("a", encoding="utf-8") as f:
        header = f"# {ts} | {status}" + (f" | id={tweet_id}" if tweet_id else "")
        f.write(header + "\n")
        for line in raw_block:
            f.write(line)
        if not (len(raw_block) and raw_block[-1].strip() == "---"):
            f.write("---\n")

def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

# ---- tweets.txt blocks ----
def load_blocks(path: Path) -> List[Dict[str, object]]:
    lines = read_lines(path)
    blocks: List[Dict[str, object]] = []
    buf: List[str] = []

    def flush():
        if not buf: return
        normalized = " ".join(s.strip() for s in buf if s.strip())
        if normalized:
            blocks.append({"text": normalized, "raw": buf.copy()})
        buf.clear()

    for ln in lines:
        if ln.strip() == "---":
            flush()
        else:
            buf.append(ln)
    flush()
    if not blocks:
        raise ValueError("No tweet blocks found in tweets.txt (use '---' separators).")
    return blocks

def delete_block(path: Path, raw_block: List[str]) -> None:
    lines = read_lines(path)
    n, m = len(lines), len(raw_block)
    start_idx = -1
    for i in range(0, n - m + 1):
        if all(lines[i+k] == raw_block[k] for k in range(m)):
            start_idx = i; break
    if start_idx == -1:
        print("Warning: block not found; nothing deleted."); return
    del_start, del_end = start_idx, start_idx + m
    if del_start - 1 >= 0 and lines[del_start - 1].strip() == "---":
        del_start -= 1
    elif del_end < len(lines) and lines[del_end].strip() == "---":
        del_end += 1
    write_lines(path, lines[:del_start] + lines[del_end:])

# ---- State helpers (PERSISTENT daily plan) ----
def today_et() -> str:
    return datetime.now(ET).date().isoformat()

def load_state() -> dict:
    if POST_STATE.exists():
        return json.loads(POST_STATE.read_text(encoding="utf-8"))
    return {}

def save_state(state: dict) -> None:
    POST_STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")

def ensure_plan(state: dict | None = None) -> dict:
    state = state or load_state()
    t = today_et()
    planned = state.get("planned") or []
    if state.get("date") != t or not planned:
        state = {
            "date": t,
            "planned": plan_slots_for_today(),  # uses START_HOUR/END_HOUR/SLOTS_PER_DAY
            "posted": [],
            "log": state.get("log", []),
        }
        save_state(state)
        print(f"Planned (12/day): {state['planned']} | Posted: {state['posted']}")
    else:
        print(f"Using existing plan: {state['planned']} | Posted: {state['posted']}")
    return state

# ---- Planning ----
def _rand_minute_between(start: datetime, end: datetime) -> datetime:
    delta_min = max(1, int((end - start).total_seconds() // 60))
    return start + timedelta(minutes=random.randrange(delta_min))

def plan_slots_for_today(min_gap_minutes: int = 30) -> List[str]:
    """Plan SLOTS_PER_DAY random ET times with a hard minimum gap between any two times."""
    today = now_et().date()
    start = datetime(today.year, today.month, today.day, START_HOUR, 0, tzinfo=ET)
    end   = datetime(today.year, today.month, today.day, END_HOUR, 59, tzinfo=ET)

    span_minutes = int((end - start).total_seconds() // 60) + 1  # inclusive
    max_slots = (span_minutes // min_gap_minutes) + 1
    if SLOTS_PER_DAY > max_slots:
        raise ValueError(
            f"Window {START_HOUR:02d}:00–{END_HOUR:02d}:59 ET too narrow for "
            f"{SLOTS_PER_DAY} slots at {min_gap_minutes}-minute gaps (max {max_slots}). "
            "Widen the window or reduce SLOTS_PER_DAY."
        )

    # Build minute-resolution candidate list
    candidates = [start + timedelta(minutes=i) for i in range(span_minutes)]
    picks: List[datetime] = []

    # Randomly pick times; after each pick, remove all candidates within ±min_gap_minutes
    while candidates and len(picks) < SLOTS_PER_DAY:
        t = candidates.pop(random.randrange(len(candidates)))
        t = t.replace(second=0, microsecond=0)
        picks.append(t)
        cutoff = timedelta(minutes=min_gap_minutes)
        candidates = [c for c in candidates if abs(c - t) >= cutoff]

    # Should always reach SLOTS_PER_DAY given the feasibility check above
    return sorted(dt.strftime("%H:%M") for dt in picks)

def find_due_slot(state: dict) -> Optional[str]:
    now = now_et()
    for slot in state.get("planned", []):
        if slot in state.get("posted", []): continue
        slot_dt = datetime.fromisoformat(state["date"] + f" {slot}:00").replace(tzinfo=ET)
        if slot_dt <= now <= slot_dt + timedelta(minutes=WINDOW_MIN):
            return slot
    return None

def next_future_slot(state: dict) -> Optional[str]:
    """Earliest unposted slot that is still in the future (fix for naive 'Next:')."""
    now = now_et()
    def to_dt(s: str):
        return datetime.fromisoformat(state["date"] + f" {s}:00").replace(tzinfo=ET)
    future = [s for s in state.get("planned", []) if s not in state.get("posted", []) and to_dt(s) > now]
    return min(future, key=to_dt) if future else None

# ---- Posting ----
def post_to_x(text: str) -> Optional[str]:
    import tweepy
    client = get_writer_client()
    try:
        resp = client.create_tweet(text=text)
        return (getattr(resp, "data", {}) or {}).get("id")
    except tweepy.Forbidden as e:
        msg = str(e).lower()
        if "duplicate content" in msg or "duplicate" in msg:
            print("Duplicate content — deleting this block and picking another at random.")
            return "DUPLICATE"
        print(f"Post failed (403): {e}")
        return None
    except Exception as e:
        print(f"Post failed (unexpected): {e}")
        return None

def post_random_block(state: dict, blocks: List[Dict[str, object]]) -> Optional[str]:
    """Pick a random block to post. On duplicate, log it and try another at random."""
    if not blocks:
        return None

    while blocks:
        idx = random.randrange(len(blocks))
        blk = blocks[idx]
        text = str(blk["text"])
        raw = list(blk["raw"])

        print(f"Trying RANDOM block #{idx+1}/{len(blocks)}: {text[:120]}{'…' if len(text)>120 else ''}")
        res = post_to_x(text)

        # DUPLICATE → log to posted_tweets.txt, remove from source, keep looping
        if res == "DUPLICATE":
            append_posted(raw, status="DUPLICATE")
            delete_block(TWEETS_FILE, raw)
            del blocks[idx]
            continue

        # SUCCESS → log to posted_tweets.txt with tweet id, remove from source, record in state, exit
        if isinstance(res, str) and res.isdigit():
            append_posted(raw, status="POSTED", tweet_id=res)
            delete_block(TWEETS_FILE, raw)
            del blocks[idx]
            state.setdefault("log", []).append({"time": now_et().isoformat(), "text": text, "id": res})
            save_state(state)
            return res

        # Any other failure → stop (don’t burn through content)
        return None

    return None

# ---- Main ----
def main():
    random.seed()
    blocks = load_blocks(TWEETS_FILE)
    state = ensure_plan(load_state())

    due = find_due_slot(state)
    if not due:
        upcoming = next_future_slot(state)
        print(f"No slot due. Next: {upcoming or 'none today'}. Planned: {state['planned']} | Posted: {state['posted']}")
        return

    print(f"Slot {due} is due (window +{WINDOW_MIN}m). Posting…")
    tweet_id = post_random_block(state, blocks)
    if tweet_id:
        state["posted"].append(due); save_state(state); print(f"Posted OK: {tweet_id}")
    else:
        print("No tweet posted this run.")

if __name__ == "__main__":
    main()

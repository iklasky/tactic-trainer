"""
Fetch most recent N games (with PGN) for a set of Chess.com usernames.

Outputs a JSON file containing, per user:
  - games: list of raw game objects from the Chess.com API (includes 'pgn')

Usage:
  python fetch_recent_v5.py --users k2f4x key_kay jtkms --n 100 --out fetched_games_v5.json
"""

from __future__ import annotations

import argparse
import json
import time
from typing import Dict, List

import requests


USER_AGENT = "TacticTrainer/1.0 (Contact: github.com/iklasky/tactic-trainer)"


def fetch_recent_games(username: str, n: int, sleep_sec: float = 0.25) -> List[Dict]:
    headers = {"User-Agent": USER_AGENT}
    archives_url = f"https://api.chess.com/pub/player/{username}/games/archives"
    r = requests.get(archives_url, headers=headers, timeout=30)
    r.raise_for_status()
    archives = r.json().get("archives", [])
    if not archives:
        return []

    games: List[Dict] = []
    # Walk from most recent archive backwards until we have >= n games
    for archive_url in reversed(archives):
        if len(games) >= n:
            break
        rr = requests.get(archive_url, headers=headers, timeout=30)
        if rr.status_code != 200:
            continue
        games.extend(rr.json().get("games", []))
        time.sleep(sleep_sec)

    # Keep the most recent n games
    return games[-n:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", nargs="+", required=True)
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--out", default="fetched_games_v5.json")
    ap.add_argument("--sleep", type=float, default=0.25)
    args = ap.parse_args()

    out: Dict[str, Dict] = {"version": "v5", "source": "chess.com api", "users": {}}

    for u in args.users:
        print(f"\n📥 Fetching {args.n} most recent games for {u}...", flush=True)
        games = fetch_recent_games(u, args.n, sleep_sec=args.sleep)
        with_pgn = sum(1 for g in games if g.get("pgn"))
        print(f"✅ {u}: fetched {len(games)} games ({with_pgn} with PGN)", flush=True)
        out["users"][u] = {
            "requested": args.n,
            "fetched": len(games),
            "with_pgn": with_pgn,
            "games": games,
        }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f)

    print(f"\n💾 Saved to {args.out}", flush=True)


if __name__ == "__main__":
    main()



"""
Chess.com API client — fetch recent games for a username.

Returns games in the manifest-ready format: [{url, pgn}, ...]
This is the ONLY place that knows about the chess.com API.
To switch to a different data source later, swap this module out
and keep returning the same [{url, pgn}] shape.
"""

from __future__ import annotations

import time
from typing import Dict, List

import requests

USER_AGENT = "TacticTrainer/1.0 (Contact: github.com/iklasky/tactic-trainer)"
_TIMEOUT = 30


def fetch_recent_games(username: str, n: int = 500) -> List[Dict[str, str]]:
    """
    Fetch the most recent `n` games (with PGN) for `username`.

    Returns a list of dicts with at least:
        {"url": "<chess.com game URL>", "pgn": "<PGN string>"}
    Skips games without PGN.
    """
    headers = {"User-Agent": USER_AGENT}

    archives_url = f"https://api.chess.com/pub/player/{username}/games/archives"
    r = requests.get(archives_url, headers=headers, timeout=_TIMEOUT)
    r.raise_for_status()
    archives = r.json().get("archives", [])
    if not archives:
        return []

    raw_games: list = []
    for archive_url in reversed(archives):
        if len(raw_games) >= n:
            break
        rr = requests.get(archive_url, headers=headers, timeout=_TIMEOUT)
        if rr.status_code != 200:
            continue
        raw_games.extend(rr.json().get("games", []))
        time.sleep(0.25)

    raw_games = raw_games[-n:]

    results: List[Dict[str, str]] = []
    for g in raw_games:
        pgn = g.get("pgn")
        url = g.get("url", "")
        if pgn and url:
            results.append({"url": url, "pgn": pgn})

    return results

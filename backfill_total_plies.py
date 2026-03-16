"""
One-time backfill: populate total_plies for existing tt_games rows.

Fetches PGNs from chess.com, counts plies, and updates the column.
Run once after adding the total_plies column:

    export DATABASE_URL='...'
    python3 backfill_total_plies.py
"""
from __future__ import annotations

import io
import chess.pgn

import chesscom
from db import get_conn, ensure_schema


def count_plies(pgn_string: str) -> int:
    game = chess.pgn.read_game(io.StringIO(pgn_string))
    if not game:
        return 0
    node = game
    count = 0
    while node.variations:
        node = node.variations[0]
        count += 1
    return count


def main() -> None:
    ensure_schema()
    conn = get_conn()

    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT username FROM tt_games WHERE total_plies IS NULL"
        )
        usernames = [row[0] for row in cur.fetchall()]

    if not usernames:
        print("Nothing to backfill — all games already have total_plies.")
        return

    for username in usernames:
        print(f"\n{'='*60}")
        print(f"Backfilling total_plies for: {username}")

        with conn.cursor() as cur:
            cur.execute(
                "SELECT game_url FROM tt_games WHERE username=%s AND total_plies IS NULL",
                (username,),
            )
            urls_needing_backfill = {row[0] for row in cur.fetchall()}

        print(f"  {len(urls_needing_backfill)} games need backfill")

        games = chesscom.fetch_recent_games(username, n=1000)
        pgn_by_url = {g["url"]: g["pgn"] for g in games}

        updated = 0
        skipped = 0
        with conn.cursor() as cur:
            for url in urls_needing_backfill:
                pgn_string = pgn_by_url.get(url)
                if not pgn_string:
                    skipped += 1
                    continue
                plies = count_plies(pgn_string)
                cur.execute(
                    "UPDATE tt_games SET total_plies=%s, updated_at=NOW() WHERE username=%s AND game_url=%s",
                    (plies, username, url),
                )
                updated += 1

        conn.commit()
        print(f"  Updated: {updated}, Skipped (PGN not found): {skipped}")

    conn.close()
    print(f"\nDone!")


if __name__ == "__main__":
    main()

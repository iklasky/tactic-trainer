"""
One-time cleanup script: remove missed opportunities where the player
followed the engine PV but the opponent deviated first.

For each missed opportunity with PV data, this script fetches the actual
game PGN from chess.com, replays the moves, and compares the player's
actual moves against the engine PV. If the player matched the PV for
all their turns until the opponent deviated, the opportunity is deleted
(it wasn't really missed).

Run:
  export DATABASE_URL='postgres://...'
  python3 cleanup_pv_rule.py
"""
from __future__ import annotations
import os, sys, time
from collections import defaultdict

import chess, chess.pgn, io, requests, psycopg2

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    print("ERROR: set DATABASE_URL env var")
    sys.exit(1)

HEADERS = {"User-Agent": "TacticTrainer/1.0"}


def get_conn():
    return psycopg2.connect(DATABASE_URL)


def player_followed_pv(pv_moves, remaining_moves):
    if len(pv_moves) < 2 or len(remaining_moves) < 2:
        return False
    for pi in range(min(len(pv_moves), len(remaining_moves))):
        actual_uci = remaining_moves[pi].uci()
        engine_uci = pv_moves[pi]
        is_player_turn = (pi % 2 == 0)
        if actual_uci != engine_uci:
            return not is_player_turn
    return False


def fetch_game_pgns(username, game_urls_needed):
    """Fetch PGNs from chess.com for the given URLs."""
    resp = requests.get(
        f"https://api.chess.com/pub/player/{username}/games/archives",
        headers=HEADERS,
    )
    archives = resp.json().get("archives", [])
    found = {}

    for arch_url in reversed(archives[-12:]):
        if len(found) >= len(game_urls_needed):
            break
        try:
            resp = requests.get(arch_url, headers=HEADERS)
            time.sleep(0.3)
            games = resp.json().get("games", [])
            for g in games:
                url = g.get("url", "")
                if url in game_urls_needed and url not in found:
                    found[url] = g.get("pgn", "")
        except Exception:
            continue

    return found


def main():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT o.username, o.game_url, o.opponent_move_ply_index,
               o.pv_moves, o.player_color, o.event_index
        FROM tt_opportunities o
        WHERE o.converted_actual = 0
          AND o.pv_moves IS NOT NULL
          AND o.pv_moves != ''
        ORDER BY o.username, o.game_url, o.opponent_move_ply_index
    """)
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]
    missed = [dict(zip(cols, r)) for r in rows]
    print(f"Total missed opportunities to check: {len(missed)}")

    by_user_game = defaultdict(list)
    for m in missed:
        by_user_game[(m["username"], m["game_url"])].append(m)

    users = sorted(set(m["username"] for m in missed))
    to_delete = []

    for user in users:
        user_games = {k: v for k, v in by_user_game.items() if k[0] == user}
        game_urls = set(k[1] for k in user_games)

        print(f"\n{user}: fetching {len(game_urls)} games...")
        pgn_map = fetch_game_pgns(user, game_urls)
        print(f"  found {len(pgn_map)}/{len(game_urls)}")

        user_affected = 0
        for (uname, gurl), opps in user_games.items():
            pgn_str = pgn_map.get(gurl)
            if not pgn_str:
                continue

            game = chess.pgn.read_game(io.StringIO(pgn_str))
            if not game:
                continue
            all_moves = list(game.mainline_moves())

            for opp in opps:
                ply_idx = opp["opponent_move_ply_index"]
                pv_str = opp["pv_moves"]
                if not pv_str:
                    continue
                pv = pv_str.split("|")
                remaining = all_moves[ply_idx + 1:]

                if player_followed_pv(pv, remaining):
                    to_delete.append((opp["username"], opp["game_url"], opp["event_index"]))
                    user_affected += 1

        print(f"  {user_affected} opportunities to remove")

    print(f"\nTotal to delete: {len(to_delete)}")

    if to_delete:
        with conn.cursor() as dcur:
            for username, game_url, event_index in to_delete:
                dcur.execute("""
                    DELETE FROM tt_opportunities
                    WHERE username = %s AND game_url = %s AND event_index = %s
                """, (username, game_url, event_index))
        conn.commit()
        print(f"Deleted {len(to_delete)} rows")

    cur.execute("""
        SELECT username,
               COUNT(*) as total,
               SUM(CASE WHEN converted_actual = 0 THEN 1 ELSE 0 END) as missed
        FROM tt_opportunities
        GROUP BY username
        ORDER BY username
    """)
    print("\nPer-user remaining missed opportunities:")
    for row in cur.fetchall():
        print(f"  {row[0]}: {row[2]} missed / {row[1]} total")

    conn.close()


if __name__ == "__main__":
    main()

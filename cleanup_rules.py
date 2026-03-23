"""
One-time cleanup script to apply the resignation-conversion and
overlap-exclusion rules to existing tt_opportunities data.

1. Resignation rule: delete opportunities where converted_actual=0
   but the player won and the game ended before the engine's
   conversion horizon (opponent resigned during engine line).

2. Overlap rule: for each game, sort opportunities by ply index.
   If an opportunity's ply falls within a previous opportunity's
   conversion window (owner_ply + t_turns_engine), delete it.

Run:
  export DATABASE_URL='<your sevalla db url>'
  python3 cleanup_rules.py
"""
from __future__ import annotations
import os, sys

import psycopg2

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    print("ERROR: set DATABASE_URL env var")
    sys.exit(1)


def get_conn():
    return psycopg2.connect(DATABASE_URL)


def apply_resignation_rule(conn) -> int:
    """
    Delete missed opportunities where:
    - converted_actual = 0
    - player won (game_result matches player_color)
    - remaining plies from opportunity to game end < t_turns_engine
    """
    with conn.cursor() as cur:
        cur.execute("""
            DELETE FROM tt_opportunities o
            USING tt_games g
            WHERE o.username = g.username
              AND o.game_url = g.game_url
              AND o.converted_actual = 0
              AND g.total_plies IS NOT NULL
              AND o.t_turns_engine IS NOT NULL
              AND (
                  (o.player_color = 'white' AND g.game_result = '1-0')
               OR (o.player_color = 'black' AND g.game_result = '0-1')
              )
              AND (g.total_plies - (o.opponent_move_ply_index + 1)) < o.t_turns_engine
        """)
        deleted = cur.rowcount
    conn.commit()
    return deleted


def apply_overlap_rule(conn) -> int:
    """
    For each (username, game_url), sort opportunities by ply index.
    If opportunity B's ply <= opportunity A's ply + t_turns_engine
    (A comes first), delete B.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT username, game_url, opponent_move_ply_index,
                   t_turns_engine, event_index
            FROM tt_opportunities
            ORDER BY username, game_url, opponent_move_ply_index
        """)
        rows = cur.fetchall()

    to_delete = []
    prev_key = None
    active_end_ply = -1

    for username, game_url, ply, t_eng, event_index in rows:
        key = (username, game_url)
        if key != prev_key:
            prev_key = key
            active_end_ply = -1

        if ply <= active_end_ply:
            to_delete.append((username, game_url, event_index))
        else:
            active_end_ply = ply + (t_eng or 0)

    deleted = 0
    if to_delete:
        with conn.cursor() as cur:
            for username, game_url, event_index in to_delete:
                cur.execute("""
                    DELETE FROM tt_opportunities
                    WHERE username = %s AND game_url = %s AND event_index = %s
                """, (username, game_url, event_index))
                deleted += cur.rowcount
        conn.commit()

    return deleted


def apply_endgame_hold3_rule(conn) -> int:
    """
    Delete missed opportunities where the game ended within 3 plies
    of the opportunity, making the hold3 conversion check unreliable.
    The analyzer fix (relaxing hold3 at end-of-game) handles this going
    forward, but existing data needs cleanup.
    """
    with conn.cursor() as cur:
        cur.execute("""
            DELETE FROM tt_opportunities o
            USING tt_games g
            WHERE o.username = g.username
              AND o.game_url = g.game_url
              AND o.converted_actual = 0
              AND g.total_plies IS NOT NULL
              AND (g.total_plies - (o.opponent_move_ply_index + 1)) < 3
        """)
        deleted = cur.rowcount
    conn.commit()
    return deleted


def main():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM tt_opportunities")
            total_before = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM tt_opportunities WHERE converted_actual = 0")
            missed_before = cur.fetchone()[0]

        print(f"Before cleanup:")
        print(f"  Total opportunities: {total_before}")
        print(f"  Missed (converted_actual=0): {missed_before}")
        print()

        print("Applying resignation rule...")
        resign_deleted = apply_resignation_rule(conn)
        print(f"  Deleted {resign_deleted} resignation-affected rows")

        print("Applying overlap rule...")
        overlap_deleted = apply_overlap_rule(conn)
        print(f"  Deleted {overlap_deleted} overlap rows")

        print("Applying end-of-game hold3 rule...")
        endgame_deleted = apply_endgame_hold3_rule(conn)
        print(f"  Deleted {endgame_deleted} end-of-game rows")

        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM tt_opportunities")
            total_after = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM tt_opportunities WHERE converted_actual = 0")
            missed_after = cur.fetchone()[0]

        print()
        print(f"After cleanup:")
        print(f"  Total opportunities: {total_after}")
        print(f"  Missed (converted_actual=0): {missed_after}")
        print(f"  Total removed: {total_before - total_after}")
        print(f"  Missed removed: {missed_before - missed_after}")

        # Per-user breakdown
        with conn.cursor() as cur:
            cur.execute("""
                SELECT username,
                       COUNT(*) as total,
                       SUM(CASE WHEN converted_actual = 0 THEN 1 ELSE 0 END) as missed
                FROM tt_opportunities
                GROUP BY username
                ORDER BY username
            """)
            print()
            print("Per-user remaining missed opportunities:")
            for row in cur.fetchall():
                print(f"  {row[0]}: {row[2]} missed / {row[1]} total")

    finally:
        conn.close()


if __name__ == "__main__":
    main()

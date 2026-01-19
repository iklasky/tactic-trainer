"""db_import.py

One-time (idempotent) importer that loads *both*:
- games (from fetched_games_v5.json) as record_kind='game'
- opportunities (from analysis_results_v5.fixed4.csv) as record_kind='opportunity'

into a single Postgres table: tt_records

Run (recommended):
  export DATABASE_URL='postgresql://USER:PASSWORD@HOST:5432/DBNAME'
  python3 db_import.py

Optional overrides:
  TT_ANALYSIS_CSV=analysis_results_v5.fixed4.csv
  TT_FETCHED_GAMES_JSON=fetched_games_v5.json
"""

import csv
import json
import os
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

import psycopg2
import psycopg2.extras

from db import get_conn
from db_schema import CREATE_SQL


def _parse_end_time(value: str) -> Optional[datetime]:
    if not value:
        return None
    value = str(value).strip()
    for fmt in ("%Y.%m.%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except Exception:
            pass
    return None


def load_games_rows(fetched_games_path: str) -> List[Dict[str, Any]]:
    with open(fetched_games_path, "r") as f:
        data = json.load(f)

    games = data.get("games", [])
    users = [u.lower() for u in data.get("users", [])]

    rows: List[Dict[str, Any]] = []

    for g in games:
        game_url = g.get("url") or ""
        if not game_url:
            continue

        white = (g.get("white") or {}).get("username", "")
        black = (g.get("black") or {}).get("username", "")
        white_l = white.lower()
        black_l = black.lower()

        for u in users:
            if white_l == u or black_l == u:
                opponent = black if white_l == u else white
                player_color = "white" if white_l == u else "black"

                rows.append(
                    {
                        "record_kind": "game",
                        "username": u,
                        "game_url": game_url,
                        "game_index": None,
                        "event_index": None,
                        "opponent": opponent,
                        "white_player": white,
                        "black_player": black,
                        "player_color": player_color,
                        "time_control": str(g.get("time_control") or ""),
                        "game_result": "",
                        "end_time": None,
                    }
                )
                break

    return rows


def load_opportunity_rows(csv_path: str) -> Iterable[Dict[str, Any]]:
    with open(csv_path, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            yield {
                "record_kind": "opportunity",
                "username": (row.get("username") or "").lower(),
                "game_url": row.get("game_url") or "",
                "game_index": int(row["game_index"]) if row.get("game_index") else None,
                "event_index": int(row["event_index"]) if row.get("event_index") else None,
                "white_player": row.get("white_player"),
                "black_player": row.get("black_player"),
                "player_color": row.get("player_color"),
                "time_control": row.get("time_control"),
                "game_result": row.get("game_result"),
                "end_time": _parse_end_time(row.get("end_time") or ""),
                "opportunity_kind": row.get("opportunity_kind"),
                "opportunity_cp": int(float(row["opportunity_cp"])) if row.get("opportunity_cp") else None,
                "mate_in": int(float(row["mate_in"])) if row.get("mate_in") else None,
                "target_pawns": int(float(row["target_pawns"])) if row.get("target_pawns") else None,
                "t_turns_engine": int(float(row["t_turns_engine"])) if row.get("t_turns_engine") else None,
                "converted_actual": int(float(row["converted_actual"])) if row.get("converted_actual") else None,
                "t_turns_actual": int(float(row["t_turns_actual"])) if row.get("t_turns_actual") else None,
                "opponent_move_ply_index": int(float(row["opponent_move_ply_index"])) if row.get("opponent_move_ply_index") else None,
                "opponent_move_san": row.get("opponent_move_san"),
                "opponent_move_uci": row.get("opponent_move_uci"),
                "best_reply_san": row.get("best_reply_san"),
                "best_reply_uci": row.get("best_reply_uci"),
                "fen_before": row.get("fen_before"),
                "fen_after": row.get("fen_after"),
                "pv_moves": row.get("pv_moves"),
                "pv_evals": row.get("pv_evals"),
                "eval_before": int(float(row["eval_before"])) if row.get("eval_before") else None,
                "converted_by_resignation": int(float(row["converted_by_resignation"])) if row.get("converted_by_resignation") else 0,
                "excluded_overlap": int(float(row["excluded_overlap"])) if row.get("excluded_overlap") else 0,
                "overlap_owner_ply": int(float(row["overlap_owner_ply"])) if row.get("overlap_owner_ply") else None,
                "overlap_owner_event": int(float(row["overlap_owner_event"])) if row.get("overlap_owner_event") else None,
            }


def chunked(it: Iterable[Dict[str, Any]], n: int) -> Iterable[List[Dict[str, Any]]]:
    buf: List[Dict[str, Any]] = []
    for x in it:
        buf.append(x)
        if len(buf) >= n:
            yield buf
            buf = []
    if buf:
        yield buf


def import_all():
    csv_path = os.environ.get("TT_ANALYSIS_CSV", "analysis_results_v5.fixed4.csv")
    fetched_games_path = os.environ.get("TT_FETCHED_GAMES_JSON", "fetched_games_v5.json")

    conn = get_conn()
    conn.autocommit = False

    try:
        with conn.cursor() as cur:
            cur.execute(CREATE_SQL)
        conn.commit()

        # Games
        games = load_games_rows(fetched_games_path)
        if games:
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(
                    cur,
                    """
                    INSERT INTO tt_records (
                      record_kind, username, game_url, game_index, event_index,
                      opponent, white_player, black_player, player_color, time_control, game_result, end_time,
                      updated_at
                    ) VALUES %s
                    ON CONFLICT ON CONSTRAINT tt_records_game_uq DO UPDATE SET
                      opponent = EXCLUDED.opponent,
                      white_player = EXCLUDED.white_player,
                      black_player = EXCLUDED.black_player,
                      player_color = EXCLUDED.player_color,
                      time_control = EXCLUDED.time_control,
                      game_result = EXCLUDED.game_result,
                      end_time = EXCLUDED.end_time,
                      updated_at = NOW()
                    """,
                    [
                        (
                            g["record_kind"],
                            g["username"],
                            g["game_url"],
                            g.get("game_index"),
                            g.get("event_index"),
                            g.get("opponent"),
                            g.get("white_player"),
                            g.get("black_player"),
                            g.get("player_color"),
                            g.get("time_control"),
                            g.get("game_result"),
                            g.get("end_time"),
                        )
                        for g in games
                    ],
                )
            conn.commit()
            print(f"Imported/updated {len(games)} game rows")

        # Opportunities
        inserted = 0
        for batch in chunked(load_opportunity_rows(csv_path), 250):
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(
                    cur,
                    """
                    INSERT INTO tt_records (
                      record_kind, username, game_url, game_index, event_index,
                      white_player, black_player, player_color, time_control, game_result, end_time,
                      opportunity_kind, opportunity_cp, mate_in, target_pawns, t_turns_engine,
                      converted_actual, t_turns_actual,
                      opponent_move_ply_index, opponent_move_san, opponent_move_uci,
                      best_reply_san, best_reply_uci,
                      fen_before, fen_after,
                      pv_moves, pv_evals, eval_before,
                      converted_by_resignation, excluded_overlap, overlap_owner_ply, overlap_owner_event,
                      updated_at
                    ) VALUES %s
                    ON CONFLICT ON CONSTRAINT tt_records_opp_uq DO UPDATE SET
                      game_index = EXCLUDED.game_index,
                      white_player = EXCLUDED.white_player,
                      black_player = EXCLUDED.black_player,
                      player_color = EXCLUDED.player_color,
                      time_control = EXCLUDED.time_control,
                      game_result = EXCLUDED.game_result,
                      end_time = EXCLUDED.end_time,
                      opportunity_kind = EXCLUDED.opportunity_kind,
                      opportunity_cp = EXCLUDED.opportunity_cp,
                      mate_in = EXCLUDED.mate_in,
                      target_pawns = EXCLUDED.target_pawns,
                      t_turns_engine = EXCLUDED.t_turns_engine,
                      converted_actual = EXCLUDED.converted_actual,
                      t_turns_actual = EXCLUDED.t_turns_actual,
                      opponent_move_ply_index = EXCLUDED.opponent_move_ply_index,
                      opponent_move_san = EXCLUDED.opponent_move_san,
                      opponent_move_uci = EXCLUDED.opponent_move_uci,
                      best_reply_san = EXCLUDED.best_reply_san,
                      best_reply_uci = EXCLUDED.best_reply_uci,
                      fen_before = EXCLUDED.fen_before,
                      fen_after = EXCLUDED.fen_after,
                      pv_moves = EXCLUDED.pv_moves,
                      pv_evals = EXCLUDED.pv_evals,
                      eval_before = EXCLUDED.eval_before,
                      converted_by_resignation = EXCLUDED.converted_by_resignation,
                      excluded_overlap = EXCLUDED.excluded_overlap,
                      overlap_owner_ply = EXCLUDED.overlap_owner_ply,
                      overlap_owner_event = EXCLUDED.overlap_owner_event,
                      updated_at = NOW()
                    """,
                    [
                        (
                            r["record_kind"],
                            r["username"],
                            r["game_url"],
                            r.get("game_index"),
                            r.get("event_index"),
                            r.get("white_player"),
                            r.get("black_player"),
                            r.get("player_color"),
                            r.get("time_control"),
                            r.get("game_result"),
                            r.get("end_time"),
                            r.get("opportunity_kind"),
                            r.get("opportunity_cp"),
                            r.get("mate_in"),
                            r.get("target_pawns"),
                            r.get("t_turns_engine"),
                            r.get("converted_actual"),
                            r.get("t_turns_actual"),
                            r.get("opponent_move_ply_index"),
                            r.get("opponent_move_san"),
                            r.get("opponent_move_uci"),
                            r.get("best_reply_san"),
                            r.get("best_reply_uci"),
                            r.get("fen_before"),
                            r.get("fen_after"),
                            r.get("pv_moves"),
                            r.get("pv_evals"),
                            r.get("eval_before"),
                            r.get("converted_by_resignation"),
                            r.get("excluded_overlap"),
                            r.get("overlap_owner_ply"),
                            r.get("overlap_owner_event"),
                        )
                        for r in batch
                    ],
                )
            conn.commit()
            inserted += len(batch)
            print(f"Imported/updated {inserted} opportunity rows...", flush=True)

        print("Done.")

    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    import_all()

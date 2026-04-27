"""
AWS Batch array worker — tactic-trainer chess analysis.

Each array child:
  1. Reads AWS_BATCH_JOB_ARRAY_INDEX to pick its game slot
  2. Downloads the job manifest from S3
  3. Analyzes exactly ONE game with ChessAnalyzerV5 + Stockfish
  4. Writes results to Postgres (tt_games + tt_opportunities) via upsert
  5. Atomically updates progress in tt_jobs

MANIFEST CONTRACT  (s3://<bucket>/manifests/<job_id>.json)
{
  "job_id":   "<uuid>",
  "username": "<chess.com username>",
  "games": [
    {"url": "https://www.chess.com/game/live/...", "pgn": "<PGN string>"},
    ...
  ]
}

REQUIRED ENVIRONMENT VARIABLES
  JOB_ID                     unique ID for this analysis run (UUID)
  MANIFEST_S3_URI            s3://bucket/manifests/{job_id}.json
  AWS_BATCH_JOB_ARRAY_INDEX  injected by AWS Batch (0-indexed slot)
  DATABASE_URL               injected from Secrets Manager by Fargate
  STOCKFISH_PATH             (optional) path to stockfish binary
"""

from __future__ import annotations

import io
import json
import os
import sys
import traceback
from datetime import datetime, timezone

import boto3
import chess.pgn

import config
from chess_analyzer_v5 import ChessAnalyzerV5
from db import get_conn

# ── Env ────────────────────────────────────────────────────────────────────
JOB_ID          = os.environ["JOB_ID"]
MANIFEST_S3_URI = os.environ["MANIFEST_S3_URI"]
ARRAY_INDEX     = int(os.environ.get("AWS_BATCH_JOB_ARRAY_INDEX", "0"))


# ── Helpers ────────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] slot={ARRAY_INDEX} job={JOB_ID[:8]} {msg}", flush=True)


def _parse_s3_uri(uri: str):
    without_scheme = uri[len("s3://"):]
    bucket, _, key = without_scheme.partition("/")
    return bucket, key


def download_manifest(uri: str) -> dict:
    bucket, key = _parse_s3_uri(uri)
    s3 = boto3.client("s3")
    resp = s3.get_object(Bucket=bucket, Key=key)
    return json.loads(resp["Body"].read())


# ── DB helpers ─────────────────────────────────────────────────────────────

def mark_game_done(conn, *, failed: bool = False) -> dict:
    """
    Atomically increment games_done or games_failed for this job.
    If all games are accounted for, set status -> 'completed'.
    """
    col = "games_failed" if failed else "games_done"
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE tt_jobs
               SET {col}  = {col} + 1,
                   status = CASE
                                WHEN games_done + games_failed + 1 >= total_games
                                    THEN 'completed'
                                WHEN status = 'pending'
                                    THEN 'running'
                                ELSE status
                            END,
                   updated_at = NOW()
             WHERE job_id = %s
         RETURNING games_done, games_failed, total_games, status
            """,
            (JOB_ID,),
        )
        row = cur.fetchone()
    conn.commit()
    if row is None:
        return {}
    return {
        "games_done":   row[0],
        "games_failed": row[1],
        "total_games":  row[2],
        "status":       row[3],
    }


def _count_plies(pgn_obj: chess.pgn.Game) -> int:
    """Count the total number of half-moves (plies) in a game."""
    node = pgn_obj
    count = 0
    while node.variations:
        node = node.variations[0]
        count += 1
    return count


def upsert_game_record(cur, username: str, game_url: str, game_index: int,
                        pgn_obj: chess.pgn.Game, *,
                        analysis_truncated: bool = False,
                        rules: str = "chess") -> None:
    headers  = pgn_obj.headers
    white    = headers.get("White", "")
    black    = headers.get("Black", "")
    color    = "white" if white.lower() == username.lower() else "black"
    opponent = black if color == "white" else white
    end_time_raw = (headers.get("UTCDate", "") + " " + headers.get("UTCTime", "")).strip()
    total_plies = _count_plies(pgn_obj)
    elo_header = headers.get("WhiteElo") if color == "white" else headers.get("BlackElo")
    try:
        player_elo = int(elo_header) if elo_header else None
    except (ValueError, TypeError):
        player_elo = None

    cur.execute(
        """
        INSERT INTO tt_games (
            username, game_url, game_index,
            white_player, black_player, player_color,
            time_control, game_result, end_time, opponent,
            total_plies, player_elo, rules, analysis_truncated
        ) VALUES (
            %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s
        )
        ON CONFLICT ON CONSTRAINT tt_games_uq
        DO UPDATE SET
            game_index         = EXCLUDED.game_index,
            player_color       = EXCLUDED.player_color,
            time_control       = EXCLUDED.time_control,
            game_result        = EXCLUDED.game_result,
            end_time           = EXCLUDED.end_time,
            opponent           = EXCLUDED.opponent,
            total_plies        = EXCLUDED.total_plies,
            player_elo         = EXCLUDED.player_elo,
            rules              = EXCLUDED.rules,
            analysis_truncated = EXCLUDED.analysis_truncated,
            updated_at         = NOW()
        """,
        (
            username, game_url, game_index,
            white, black, color,
            headers.get("TimeControl", ""),
            headers.get("Result", ""),
            end_time_raw or None,
            opponent,
            total_plies,
            player_elo,
            rules or "chess",
            analysis_truncated,
        ),
    )


def upsert_opportunity(cur, opp: dict, game_index: int, event_index: int) -> None:
    end_time_raw = opp.get("end_time") or None
    cur.execute(
        """
        INSERT INTO tt_opportunities (
            username, game_url, game_index, event_index,
            white_player, black_player, player_color, time_control,
            game_result, end_time, opportunity_kind, opportunity_cp,
            mate_in, target_pawns, t_turns_engine, converted_actual,
            conversion_method,
            t_turns_actual, opponent_move_ply_index, opponent_move_san,
            opponent_move_uci, best_reply_san, best_reply_uci,
            fen_before, fen_after, pv_moves, pv_evals, eval_before
        ) VALUES (
            %(username)s, %(game_url)s, %(game_index)s, %(event_index)s,
            %(white_player)s, %(black_player)s, %(player_color)s, %(time_control)s,
            %(game_result)s, %(end_time)s, %(opportunity_kind)s, %(opportunity_cp)s,
            %(mate_in)s, %(target_pawns)s, %(t_turns_engine)s, %(converted_actual)s,
            %(conversion_method)s,
            %(t_turns_actual)s, %(opponent_move_ply_index)s, %(opponent_move_san)s,
            %(opponent_move_uci)s, %(best_reply_san)s, %(best_reply_uci)s,
            %(fen_before)s, %(fen_after)s, %(pv_moves)s, %(pv_evals)s, %(eval_before)s
        )
        ON CONFLICT ON CONSTRAINT tt_opportunities_uq
        DO UPDATE SET
            opportunity_kind       = EXCLUDED.opportunity_kind,
            opportunity_cp         = EXCLUDED.opportunity_cp,
            mate_in                = EXCLUDED.mate_in,
            target_pawns           = EXCLUDED.target_pawns,
            t_turns_engine         = EXCLUDED.t_turns_engine,
            converted_actual       = EXCLUDED.converted_actual,
            conversion_method      = EXCLUDED.conversion_method,
            t_turns_actual         = EXCLUDED.t_turns_actual,
            best_reply_san         = EXCLUDED.best_reply_san,
            best_reply_uci         = EXCLUDED.best_reply_uci,
            pv_moves               = EXCLUDED.pv_moves,
            pv_evals               = EXCLUDED.pv_evals,
            eval_before            = EXCLUDED.eval_before,
            updated_at             = NOW()
        """,
        {
            **opp,
            "game_index":  game_index,
            "event_index": event_index,
            "end_time":    end_time_raw,
        },
    )


# ── Main ───────────────────────────────────────────────────────────────────

def main() -> None:
    log("starting")

    log(f"downloading manifest from {MANIFEST_S3_URI}")
    manifest = download_manifest(MANIFEST_S3_URI)

    username = manifest["username"]
    games    = manifest["games"]
    total    = len(games)

    if ARRAY_INDEX >= total:
        log(f"slot {ARRAY_INDEX} >= total games {total} — nothing to do, exiting cleanly")
        return

    game_entry = games[ARRAY_INDEX]
    game_url   = game_entry["url"]
    pgn_string = game_entry["pgn"]
    game_rules = game_entry.get("rules") or "chess"

    log(f"game {ARRAY_INDEX + 1}/{total}: {game_url}")

    analyzer = ChessAnalyzerV5()
    try:
        opportunities, truncated = analyzer.analyze_game(pgn_string, username)
        # The analyzer sets game_url from the PGN "Site" header which is just
        # "Chess.com" -- override with the actual URL from the manifest.
        for opp in opportunities:
            opp["game_url"] = game_url
    except Exception as exc:
        log(f"ERROR during analysis of {game_url}: {exc}")
        traceback.print_exc()
        conn = get_conn()
        try:
            mark_game_done(conn, failed=True)
        finally:
            conn.close()
        sys.exit(1)

    if truncated:
        log(f"analysis TRUNCATED (timeout) for {game_url} — saving {len(opportunities)} partial opportunities")
    else:
        log(f"found {len(opportunities)} opportunities for {game_url}")

    conn = get_conn()
    try:
        pgn_obj = chess.pgn.read_game(io.StringIO(pgn_string))

        with conn.cursor() as cur:
            if pgn_obj:
                upsert_game_record(
                    cur, username, game_url, ARRAY_INDEX, pgn_obj,
                    analysis_truncated=truncated,
                    rules=game_rules,
                )

            for event_idx, opp in enumerate(opportunities):
                upsert_opportunity(cur, opp, ARRAY_INDEX, event_idx)

        conn.commit()
        log(f"wrote 1 game + {len(opportunities)} opportunities for {game_url}")

        progress = mark_game_done(conn, failed=False)
        log(
            f"progress: {progress.get('games_done')}/{progress.get('total_games')} done "
            f"({progress.get('games_failed')} failed) status={progress.get('status')}"
        )

    except Exception as exc:
        conn.rollback()
        log(f"FATAL DB error for {game_url}: {exc}")
        traceback.print_exc()
        try:
            mark_game_done(conn, failed=True)
        except Exception:
            pass
        conn.close()
        sys.exit(1)
    finally:
        conn.close()

    log(f"done: {game_url}")


if __name__ == "__main__":
    main()

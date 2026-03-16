CREATE_SQL = """
-- ── Job tracking table ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tt_jobs (
  job_id           TEXT        PRIMARY KEY,
  username         TEXT        NOT NULL,
  batch_job_id     TEXT,
  manifest_s3_uri  TEXT        NOT NULL,
  status           TEXT        NOT NULL DEFAULT 'pending',
  total_games      INTEGER     NOT NULL,
  games_done       INTEGER     NOT NULL DEFAULT 0,
  games_failed     INTEGER     NOT NULL DEFAULT 0,
  created_at       TIMESTAMP   NOT NULL DEFAULT NOW(),
  updated_at       TIMESTAMP   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS tt_jobs_username_idx ON tt_jobs (username);

-- ── Games table ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tt_games (
  username         TEXT        NOT NULL,
  game_url         TEXT        NOT NULL,
  game_index       INTEGER,
  opponent         TEXT,
  white_player     TEXT,
  black_player     TEXT,
  player_color     TEXT,
  time_control     TEXT,
  game_result      TEXT,
  end_time         TIMESTAMP,
  total_plies      INTEGER,
  player_elo       INTEGER,
  analysis_truncated BOOLEAN   NOT NULL DEFAULT FALSE,
  created_at       TIMESTAMP   NOT NULL DEFAULT NOW(),
  updated_at       TIMESTAMP   NOT NULL DEFAULT NOW(),

  CONSTRAINT tt_games_uq UNIQUE (username, game_url)
);

CREATE INDEX IF NOT EXISTS tt_games_username_idx ON tt_games (username);

-- ── Opportunities table ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tt_opportunities (
  username                TEXT    NOT NULL,
  game_url                TEXT    NOT NULL,
  game_index              INTEGER,
  event_index             INTEGER NOT NULL,
  opportunity_kind        TEXT,
  opportunity_cp          INTEGER,
  mate_in                 INTEGER,
  target_pawns            INTEGER,
  t_turns_engine          INTEGER,
  converted_actual        INTEGER,
  t_turns_actual          INTEGER,
  opponent_move_ply_index INTEGER,
  opponent_move_san       TEXT,
  opponent_move_uci       TEXT,
  best_reply_san          TEXT,
  best_reply_uci          TEXT,
  fen_before              TEXT,
  fen_after               TEXT,
  pv_moves                TEXT,
  pv_evals                TEXT,
  eval_before             INTEGER,
  white_player            TEXT,
  black_player            TEXT,
  player_color            TEXT,
  time_control            TEXT,
  game_result             TEXT,
  end_time                TIMESTAMP,
  created_at              TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at              TIMESTAMP NOT NULL DEFAULT NOW(),

  CONSTRAINT tt_opportunities_uq UNIQUE (username, game_url, event_index)
);

CREATE INDEX IF NOT EXISTS tt_opps_username_idx ON tt_opportunities (username);
CREATE INDEX IF NOT EXISTS tt_opps_game_url_idx ON tt_opportunities (username, game_url);
"""


MIGRATE_SQL = """
-- Drop old table if it exists (safe because new tables are created above)
DROP TABLE IF EXISTS tt_records;

-- Add total_plies column if it doesn't exist yet
ALTER TABLE tt_games ADD COLUMN IF NOT EXISTS total_plies INTEGER;

-- Add player_elo column if it doesn't exist yet
ALTER TABLE tt_games ADD COLUMN IF NOT EXISTS player_elo INTEGER;
"""

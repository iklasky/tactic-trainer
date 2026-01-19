CREATE_SQL = """
CREATE TABLE IF NOT EXISTS tt_records (
  record_kind TEXT NOT NULL CHECK (record_kind IN ('game','opportunity')),
  username TEXT NOT NULL,
  game_url TEXT NOT NULL,
  game_index INTEGER,
  event_index INTEGER,

  -- game-only fields
  opponent TEXT,
  white_player TEXT,
  black_player TEXT,
  player_color TEXT,
  time_control TEXT,
  game_result TEXT,
  end_time TIMESTAMP,

  -- opportunity fields (nullable for game rows)
  opportunity_kind TEXT,
  opportunity_cp INTEGER,
  mate_in INTEGER,
  target_pawns INTEGER,
  t_turns_engine INTEGER,
  converted_actual INTEGER,
  t_turns_actual INTEGER,
  opponent_move_ply_index INTEGER,
  opponent_move_san TEXT,
  opponent_move_uci TEXT,
  best_reply_san TEXT,
  best_reply_uci TEXT,
  fen_before TEXT,
  fen_after TEXT,
  pv_moves TEXT,
  pv_evals TEXT,
  eval_before INTEGER,
  converted_by_resignation INTEGER,
  excluded_overlap INTEGER,
  overlap_owner_ply INTEGER,
  overlap_owner_event INTEGER,

  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS tt_records_game_uq
  ON tt_records (username, game_url)
  WHERE record_kind = 'game';

CREATE UNIQUE INDEX IF NOT EXISTS tt_records_opp_uq
  ON tt_records (username, game_url, event_index)
  WHERE record_kind = 'opportunity';
"""



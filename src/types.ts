export interface ErrorEvent {
  delta_cp: number;
  t_plies: number;
  t_plies_raw?: number;
  ply_index: number;
  move_san: string;
  move_uci: string;
  best_move_uci: string;
  best_move_san: string;
  fen: string;
  fen_after: string;
  pv_moves: string[];
  pv_evals: number[];
  eval_before: number;
  game_url: string;
  converted_actual: number; // 1 if converted, 0 if missed
  opportunity_kind?: 'cp' | 'mate';
  mate_in?: number;
}

export interface HistogramData {
  delta_bins: string[];
  t_bins: string[];
  counts: number[][];
}

export interface AnalysisResult {
  username: string;
  errors: ErrorEvent[];
  histogram: HistogramData;
  total_errors: number;
  missed_count: number;
  converted_count: number;
  games_analyzed: number;
  source: string;
  timestamp: string;
}

export interface GamesData {
  username: string;
  total_games: number;
  games: any[];
}


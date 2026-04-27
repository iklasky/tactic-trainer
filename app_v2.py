"""
Flask backend for Tactic Trainer (CSV-based).
Serves pre-computed missed opportunity analysis from CSV.
"""

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import pandas as pd
import json
import os
import random
import config
from datetime import datetime
from typing import Optional, List, Dict, Any
import traceback

import db as tt_db
import chesscom

try:
    import batch as tt_batch
    _batch_available = True
except Exception:
    _batch_available = False

# If DB is configured, ensure schema exists so tables show up immediately.
try:
    if tt_db.db_enabled():
        tt_db.ensure_schema()
except Exception as e:
    # Don't crash the web process just because DB isn't reachable at boot.
    print(f"[WARN] DB schema ensure failed: {e}", flush=True)

app = Flask(__name__, static_folder='dist')
CORS(app)

# Cache for CSV data
analysis_cache = None
analysis_cache_time = None

# Cache for total games count
total_games_cache = None

# Cache for game ELO data: game_url → {player: elo}
game_elo_cache = None


def load_total_games_from_json():
    """Load total games count per user from fetched_games_v5.json."""
    global total_games_cache
    
    if total_games_cache is not None:
        return total_games_cache
    
    try:
        with open('fetched_games_v5.json', 'r') as f:
            data = json.load(f)
        
        users = data.get('users', [])
        games = data.get('games', [])
        
        # Count games per user
        user_counts = {user.lower(): 0 for user in users}
        
        for game_data in games:
            white_username = game_data.get('white', {}).get('username', '').lower()
            black_username = game_data.get('black', {}).get('username', '').lower()
            
            for user in user_counts.keys():
                if white_username == user or black_username == user:
                    user_counts[user] += 1
                    break  # Only count once per game
        
        total_games_cache = user_counts
        return user_counts
    except Exception as e:
        print(f"Error loading total games: {e}")
        return {}


def load_game_elo_data():
    """
    Load ELO data for all games from fetched_games_v5.json.
    Returns: dict mapping game_url → {username: elo}
    """
    global game_elo_cache
    
    if game_elo_cache is not None:
        return game_elo_cache
    
    try:
        import chess.pgn
        import io
        
        with open('fetched_games_v5.json', 'r') as f:
            data = json.load(f)
        
        users_data = data.get('users', {})
        elo_map = {}
        
        for username, user_data in users_data.items():
            games = user_data.get('games', [])
            
            for game_data in games:
                pgn_text = game_data.get('pgn', '')
                if not pgn_text:
                    continue
                
                # Parse PGN headers
                pgn_io = io.StringIO(pgn_text)
                game = chess.pgn.read_game(pgn_io)
                
                if not game:
                    continue
                
                game_url = game.headers.get('Link', '')
                white_player = game.headers.get('White', '').lower()
                black_player = game.headers.get('Black', '').lower()
                white_elo = game.headers.get('WhiteElo', '0')
                black_elo = game.headers.get('BlackElo', '0')
                
                if game_url and game_url not in elo_map:
                    elo_map[game_url] = {}
                
                if game_url:
                    try:
                        elo_map[game_url][white_player] = int(white_elo)
                    except (ValueError, TypeError):
                        elo_map[game_url][white_player] = 0
                    
                    try:
                        elo_map[game_url][black_player] = int(black_elo)
                    except (ValueError, TypeError):
                        elo_map[game_url][black_player] = 0
        
        game_elo_cache = elo_map
        print(f"✓ Loaded ELO data for {len(elo_map)} games", flush=True)
        return elo_map
        
    except Exception as e:
        print(f"Error loading ELO data: {e}", flush=True)
        return {}


def _db_fetchall(query: str, params: Optional[tuple] = None) -> List[Dict[str, Any]]:
    with tt_db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(query, params or ())
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def _db_count_games_for_user(username: str) -> int:
    rows = _db_fetchall(
        "SELECT COUNT(*) AS n FROM tt_games WHERE username=%s",
        (username.lower(),),
    )
    return int(rows[0]["n"]) if rows else 0


def _db_get_total_player_moves(username: str) -> int:
    """Sum player moves across all games.  Player moves ≈ ceil(total_plies/2) for white,
    floor(total_plies/2) for black."""
    rows = _db_fetchall(
        """
        SELECT COALESCE(SUM(
            CASE WHEN player_color = 'white'
                 THEN (total_plies + 1) / 2
                 ELSE total_plies / 2
            END
        ), 0) AS total_moves
        FROM tt_games
        WHERE username = %s AND total_plies IS NOT NULL
        """,
        (username.lower(),),
    )
    return int(rows[0]["total_moves"]) if rows else 0


def _db_get_games_for_timeseries(username: str) -> list:
    """Return games with move counts, ELO, and end times, ordered chronologically."""
    return _db_fetchall(
        """
        SELECT game_url, player_color, total_plies, end_time, player_elo,
               time_control,
               COALESCE(rules, 'chess') AS rules
          FROM tt_games
         WHERE username = %s AND total_plies IS NOT NULL
         ORDER BY end_time ASC NULLS LAST
        """,
        (username.lower(),),
    )


def _db_get_analyzed_urls(username: str) -> set:
    """Return the set of game_urls already analysed for this user."""
    rows = _db_fetchall(
        "SELECT game_url FROM tt_games WHERE username=%s",
        (username.lower(),),
    )
    return {r["game_url"] for r in rows}


def _db_load_opportunities(username_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    params: List[Any] = []
    where: List[str] = []
    if username_filter:
        where.append("username=%s")
        params.append(username_filter.lower())

    where_clause = ("WHERE " + " AND ".join(where)) if where else ""

    q = f"""
        SELECT
          username, game_url, game_index, event_index,
          opportunity_kind, opportunity_cp, mate_in, target_pawns,
          t_turns_engine, converted_actual, conversion_method, t_turns_actual,
          opponent_move_ply_index, opponent_move_san, opponent_move_uci,
          best_reply_san, best_reply_uci,
          fen_before, fen_after,
          pv_moves, pv_evals, eval_before,
          white_player, black_player, player_color, time_control, game_result, end_time
        FROM tt_opportunities
        {where_clause}
        ORDER BY username, game_index, event_index
    """
    return _db_fetchall(q, tuple(params))


def load_analysis_from_csv(csv_path='analysis_results.csv'):
    """Load pre-computed missed opportunity analysis from CSV."""
    global analysis_cache, analysis_cache_time
    
    # Return cached data if available and file hasn't changed
    if analysis_cache is not None:
        file_mtime = os.path.getmtime(csv_path)
        if analysis_cache_time == file_mtime:
            return analysis_cache
    
    # Load CSV
    df = pd.read_csv(csv_path)
    
    # Convert to structured format
    opportunities = []
    for _, row in df.iterrows():
        # Parse pv_evals from pipe-separated string to list of floats
        pv_evals = []
        if pd.notna(row.get('pv_evals', '')) and row['pv_evals']:
            try:
                pv_evals = [float(e) for e in str(row['pv_evals']).split('|') if e]
            except:
                pass
        
        # Get eval_before (default to 0 if not available)
        eval_before = 0
        if pd.notna(row.get('eval_before', '')):
            try:
                eval_before = float(row['eval_before'])
            except:
                pass
        
        opp = {
            # Map new columns to match frontend expectations
            'delta_cp': int(row['opportunity_cp']),  # Frontend still uses delta_cp
            't_plies': int(row['t_turns_engine']),   # Frontend still uses t_plies
            'ply_index': int(row['opponent_move_ply_index']),
            'move_san': row['opponent_move_san'],
            'move_uci': row['opponent_move_uci'],
            'best_move_uci': row['best_reply_uci'],
            'best_move_san': row['best_reply_san'],
            'fen': row['fen_before'],
            'fen_after': row['fen_after'],
            'pv_moves': row['pv_moves'].split('|') if pd.notna(row['pv_moves']) and row['pv_moves'] else [],
            'pv_evals': pv_evals,  # NEW: Evals at each PV position
            'eval_before': eval_before,  # NEW: Eval before opponent's mistake
            'game_url': row['game_url'],
            # Additional opportunity-specific fields
            'opportunity_cp': int(row['opportunity_cp']),
            'target_pawns': int(row['target_pawns']),
            'converted_actual': int(row['converted_actual']),
            'conversion_method': row.get('conversion_method') or ('missed' if int(row['converted_actual']) == 0 else 'actual'),
        }
        opportunities.append(opp)
    
    analysis_cache = {
        'username': df.iloc[0]['username'] if len(df) > 0 else 'Unknown',
        'errors': opportunities,  # Frontend still calls them errors
        'total_errors': len(opportunities),
        'games_analyzed': df['game_index'].nunique() if len(df) > 0 else 0
    }
    analysis_cache_time = os.path.getmtime(csv_path)
    
    return analysis_cache


def load_test_games():
    """Load test games from JSON file."""
    json_path = os.path.join(os.path.dirname(__file__), 'test_games.json')
    with open(json_path, 'r') as f:
        data = json.load(f)
    return data


def calculate_material_diff_from_fen(fen: str) -> int:
    """
    Calculate material difference from FEN string.
    Returns positive if White is ahead, negative if Black is ahead.
    """
    piece_values = {
        'P': 1, 'N': 3, 'B': 3, 'R': 5, 'Q': 9,
        'p': -1, 'n': -3, 'b': -3, 'r': -5, 'q': -9
    }
    
    # Extract piece placement (first part of FEN)
    pieces = fen.split()[0]
    
    material = 0
    for char in pieces:
        if char in piece_values:
            material += piece_values[char]
    
    return material


def compute_histogram(errors: list) -> dict:
    """
    Compute 2D histogram for visualization.
    Bins:
      - opportunity_cp: 100-299, 300-799, 800+ (mate is included in 800+)
      - t_turns: 1-3, 5-7, 9+
    """
    delta_bins = [100, 300, 800, float('inf')]
    delta_labels = ['100-299', '300-799', '800+']

    t_bins = [1, 4, 8, float('inf')]
    t_labels = ['1-3', '5-7', '9+']

    histogram = {
        'delta_bins': delta_labels,
        't_bins': t_labels,
        'counts': [[0 for _ in t_labels] for _ in delta_labels]
    }

    for error in errors:
        is_mate = error.get('opportunity_kind') == 'mate'
        delta_cp = 1000 if is_mate else error['delta_cp']

        if delta_cp < 100:
            continue

        delta_idx = None
        for idx in range(len(delta_bins) - 1):
            if delta_cp >= delta_bins[idx] and delta_cp < delta_bins[idx + 1]:
                delta_idx = idx
                break
        if delta_idx is None:
            delta_idx = len(delta_labels) - 1

        t_plies = error['t_plies']
        t_idx = None
        for idx in range(len(t_bins) - 1):
            if t_plies >= t_bins[idx] and t_plies < t_bins[idx + 1]:
                t_idx = idx
                break
        if t_idx is None:
            t_idx = len(t_labels) - 1

        histogram['counts'][delta_idx][t_idx] += 1

    return histogram


@app.route('/')
def serve_index():
    """Serve the frontend."""
    return send_from_directory(app.static_folder, 'index.html')


@app.route('/<path:path>')
def serve_static(path):
    """Serve static files."""
    return send_from_directory(app.static_folder, path)


@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    csv_exists = os.path.exists('analysis_results.csv')
    
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'mode': 'missed-opportunities (DB)' if tt_db.db_enabled() else 'missed-opportunities (CSV)',
        'db_enabled': tt_db.db_enabled(),
        'csv_available': csv_exists,
        'config': {
            'delta_cutoff_cp': config.DELTA_CUTOFF_CP,
            'max_horizon_plies': config.MAX_HORIZON_PLIES,
            'stockfish_depth': config.STOCKFISH_DEPTH
        }
    })


@app.route('/api/games', methods=['GET'])
def get_games():
    """Get list of available games."""
    try:
        data = load_test_games()
        
        username = data.get('username', 'Unknown')
        total_games = data.get('total_games', 0)
        games = data.get('games', [])
        
        # Extract game summaries (first 10)
        game_summaries = []
        for game in games[:10]:
            game_summaries.append({
                'url': game.get('url', ''),
                'time_control': game.get('time_control', ''),
                'end_time': game.get('end_time', 0),
                'white': game.get('white', {}).get('username', ''),
                'black': game.get('black', {}).get('username', ''),
            })
        
        return jsonify({
            'username': username,
            'total_games': total_games,
            'games': game_summaries
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/players', methods=['GET'])
def get_players():
    """
    Get list of available players from CSV.
    """
    try:
        # Prefer DB if configured
        if tt_db.db_enabled():
            rows = _db_load_opportunities(username_filter=None)
            if not rows:
                return jsonify({'players': []}), 200

            # material filter + convert to minimal opp objects
            by_user: Dict[str, List[Dict[str, Any]]] = {}
            games_by_user: Dict[str, set] = {}

            for r in rows:
                username = (r.get("username") or "").lower()
                fen_before = r.get("fen_before") or ""
                if fen_before:
                    try:
                        if abs(calculate_material_diff_from_fen(fen_before)) >= 9:
                            continue
                    except Exception:
                        # if fen parse fails, keep row (safer than dropping everything)
                        pass

                game_url = r.get("game_url") or ""
                games_by_user.setdefault(username, set()).add(game_url)

                kind = r.get("opportunity_kind") or "cp"
                if kind == "mate":
                    delta_cp = 1000
                else:
                    try:
                        delta_cp = int(r.get("opportunity_cp") or 0)
                    except Exception:
                        delta_cp = 0

                try:
                    t_engine_raw = int(r.get("t_turns_engine") or 0)
                except Exception:
                    t_engine_raw = 0
                t_engine_display = t_engine_raw

                try:
                    converted_actual = int(r.get("converted_actual") or 0)
                except Exception:
                    converted_actual = 0

                by_user.setdefault(username, []).append(
                    {
                        "delta_cp": delta_cp,
                        "t_plies": t_engine_display,
                        "converted_actual": converted_actual,
                        "opportunity_kind": kind,
                    }
                )

            players = []
            for username, opps in sorted(by_user.items()):
                # missed histogram count (exactly what's displayed)
                missed_opps = [o for o in opps if o.get("converted_actual") == 0]
                missed_histogram = compute_histogram(missed_opps)
                missed_count = sum(sum(row) for row in missed_histogram["counts"])
                missed_count -= missed_histogram["counts"][0][2]  # exclude 100-299cp, 9+ moves

                # total games: prefer tt_games count, fallback to distinct game_url in opportunities
                total_games = _db_count_games_for_user(username)
                if total_games == 0:
                    total_games = len(games_by_user.get(username, set()))

                players.append(
                    {
                        "username": username,
                        "opportunities": missed_count,
                        "games": total_games,
                    }
                )

            return jsonify({"players": players})

        csv_path = 'analysis_results_v5.fixed4.csv'
        
        if not os.path.exists(csv_path):
            return jsonify({'players': []}), 200
        
        df = pd.read_csv(csv_path)
        
        # Filter out overlapping opportunities
        if 'excluded_overlap' in df.columns:
            df = df[df['excluded_overlap'] != 1]
        
        # Filter out opportunities with material imbalance >= 9
        df['material_diff'] = df['fen_before'].apply(lambda fen: abs(calculate_material_diff_from_fen(fen)))
        df = df[df['material_diff'] < 9]
        df = df.drop(columns=['material_diff'])  # Remove temporary column
        
        # Load total games count from fetched_games_v5.json
        total_games_map = load_total_games_from_json()
        
        # Get unique usernames and their stats
        players = []
        for username in df['username'].unique():
            user_data = df[df['username'] == username]
            
            # Convert user data to opportunities format for histogram calculation
            user_opportunities = []
            for _, row in user_data.iterrows():
                # Calculate material differential at the time of opponent's mistake
                # Filter out opportunities where material imbalance >= 9 points
                material_diff = calculate_material_diff_from_fen(row['fen_before'])
                if abs(material_diff) >= 9:
                    continue  # Skip this opportunity - too much material imbalance
                
                t_engine_raw = int(row['t_turns_engine'])
                t_engine_display = t_engine_raw
                
                # For mate opportunities, opportunity_cp might be NaN
                # For mate, we use a high value for histogram purposes
                if row['opportunity_kind'] == 'mate':
                    delta_cp = 1000  # Treat mate as very high value
                else:
                    delta_cp = int(row['opportunity_cp']) if pd.notna(row['opportunity_cp']) else 0
                
                user_opportunities.append({
                    'delta_cp': delta_cp,
                    't_plies': t_engine_display,
                    'converted_actual': int(row['converted_actual']),
                    'conversion_method': row.get('conversion_method') or ('missed' if int(row['converted_actual']) == 0 else 'actual'),
                })
            
            # Filter to missed opportunities and compute histogram
            missed_opps = [opp for opp in user_opportunities if opp['converted_actual'] == 0]
            missed_histogram = compute_histogram(missed_opps)
            
            # Count from histogram (exactly what's displayed)
            missed_count = sum(sum(row) for row in missed_histogram['counts'])
            
            # Get total games from JSON file
            total_games = total_games_map.get(username.lower(), 0)
            
            players.append({
                'username': username,
                'opportunities': missed_count,
                'games': total_games
            })
        
        return jsonify({'players': players})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/analysis', methods=['GET'])
def get_analysis():
    """
    Get pre-computed missed opportunity analysis from CSV.
    Optional query params:
    - username: filter by specific player
    - min_elo: minimum ELO rating (default 0)
    - max_elo: maximum ELO rating (default 3000)
    """
    try:
        csv_path = 'analysis_results_v5.fixed4.csv'
        username_filter = request.args.get('username', None)
        min_elo = int(request.args.get('min_elo', 0))
        max_elo = int(request.args.get('max_elo', 3000))

        # Prefer DB if configured
        if tt_db.db_enabled():
            rows = _db_load_opportunities(username_filter=username_filter)
            if not rows:
                return jsonify({
                    'username': username_filter or 'All Players',
                    'errors': [],
                    'histogram': {'delta_bins': [], 't_bins': [], 'counts': []},
                    'total_errors': 0,
                    'missed_count': 0,
                    'converted_count': 0,
                    'games_analyzed': 0,
                    'total_games_analyzed': 0,
                    'total_opportunities': 0,
                    'total_player_moves': 0,
                    'games_with_moves': [],
                    'source': 'missed-opportunities',
                    'timestamp': datetime.now().isoformat()
                })

            opportunities: List[Dict[str, Any]] = []
            games_seen = set()

            for r in rows:
                fen_before = r.get("fen_before") or ""
                if fen_before:
                    try:
                        if abs(calculate_material_diff_from_fen(fen_before)) >= 9:
                            continue
                    except Exception:
                        pass

                # Parse PV
                pv_moves_list = (r.get("pv_moves") or "").split("|") if r.get("pv_moves") else []
                pv_evals_raw = (r.get("pv_evals") or "").split("|") if r.get("pv_evals") else []
                pv_evals: List[float] = []
                for e in pv_evals_raw:
                    e = str(e).strip()
                    if not e:
                        continue
                    try:
                        pv_evals.append(float(e))
                    except Exception:
                        continue

                try:
                    eval_before = float(r.get("eval_before") or 0)
                except Exception:
                    eval_before = 0

                try:
                    t_engine_raw = int(r.get("t_turns_engine") or 0)
                except Exception:
                    t_engine_raw = 0
                t_engine_display = t_engine_raw

                # Keep PV moves up to raw so navigation reaches actualization
                if t_engine_raw and pv_moves_list:
                    pv_moves_list = pv_moves_list[:t_engine_raw]
                if t_engine_raw and pv_evals:
                    pv_evals = pv_evals[:t_engine_raw]

                kind = r.get("opportunity_kind") or "cp"
                if kind == "mate":
                    delta_cp = 1000
                    mate_in = int(r.get("mate_in")) if r.get("mate_in") is not None else None
                else:
                    delta_cp = int(r.get("opportunity_cp") or 0)
                    mate_in = None

                opp = {
                    'delta_cp': delta_cp,
                    't_plies': t_engine_display,
                    'ply_index': int(r.get("opponent_move_ply_index") or 0),
                    'move_san': r.get("opponent_move_san") or "",
                    'move_uci': r.get("opponent_move_uci") or "",
                    'best_move_uci': r.get("best_reply_uci") or "",
                    'best_move_san': r.get("best_reply_san") or "",
                    'fen': r.get("fen_before") or "",
                    'fen_after': r.get("fen_after") or "",
                    'pv_moves': pv_moves_list,
                    'pv_evals': pv_evals,
                    'eval_before': eval_before,
                    'game_url': r.get("game_url") or "",
                    'opportunity_cp': delta_cp,
                    'opportunity_kind': kind,
                    'mate_in': mate_in,
                    'target_pawns': int(r.get("target_pawns") or 0),
                    'converted_actual': int(r.get("converted_actual") or 0),
                    'conversion_method': r.get("conversion_method") or ('missed' if int(r.get("converted_actual") or 0) == 0 else 'actual'),
                    't_plies_raw': t_engine_raw,
                    't_turns_actual': None,
                    't_turns_actual_raw': r.get("t_turns_actual"),
                    '_username': r.get("username") or "",
                }

                opportunities.append(opp)
                games_seen.add(r.get("game_url") or "")

            # Filter by ELO if specified
            if min_elo > 0 or max_elo < 3000:
                db_elo_rows = _db_fetchall(
                    "SELECT username, game_url, player_elo FROM tt_games WHERE player_elo IS NOT NULL"
                )
                db_elo_map: Dict[str, Dict[str, int]] = {}
                for er in db_elo_rows:
                    gu = er.get("game_url", "")
                    un = er.get("username", "").lower()
                    elo = er.get("player_elo")
                    if gu and elo is not None:
                        db_elo_map.setdefault(gu, {})[un] = int(elo)

                filtered_opps = []
                for opp in opportunities:
                    game_url = opp['game_url']
                    opp_user = opp.get('_username', '').lower()

                    if game_url in db_elo_map:
                        player_elo = None
                        if opp_user and opp_user in db_elo_map[game_url]:
                            player_elo = db_elo_map[game_url][opp_user]
                        else:
                            for u_elo in db_elo_map[game_url].values():
                                player_elo = u_elo
                                break

                        if player_elo is not None and min_elo <= player_elo <= max_elo:
                            filtered_opps.append(opp)

                opportunities = filtered_opps

            opportunities_in_histogram = [opp for opp in opportunities if opp['delta_cp'] >= 100]
            histogram_data = compute_histogram(opportunities_in_histogram)
            missed_opportunities = [opp for opp in opportunities_in_histogram if opp['converted_actual'] == 0]
            missed_histogram = compute_histogram(missed_opportunities)
            missed_count_in_histogram = sum(sum(row) for row in missed_histogram['counts'])
            total_count_in_histogram = sum(sum(row) for row in histogram_data['counts'])

            current_username = (username_filter or (opportunities[0].get("username") if opportunities else "all")) or ""
            total_games_analyzed = 0
            total_player_moves = 0
            games_with_moves: List[Dict[str, Any]] = []
            if username_filter:
                total_games_analyzed = _db_count_games_for_user(username_filter)
                if total_games_analyzed == 0:
                    total_games_analyzed = len(games_seen)
                total_player_moves = _db_get_total_player_moves(username_filter)
                games_with_moves = _db_get_games_for_timeseries(username_filter)
                for g in games_with_moves:
                    plies = g.get("total_plies") or 0
                    if g.get("player_color") == "white":
                        g["player_moves"] = (plies + 1) // 2
                    else:
                        g["player_moves"] = plies // 2
                    if g.get("end_time"):
                        g["end_time"] = g["end_time"].isoformat()

            return jsonify({
                'username': username_filter or 'All Players',
                'errors': opportunities_in_histogram,
                'histogram': histogram_data,
                'total_errors': len(opportunities_in_histogram),
                'missed_count': missed_count_in_histogram,
                'converted_count': total_count_in_histogram - missed_count_in_histogram,
                'games_analyzed': len(games_seen),
                'total_games_analyzed': total_games_analyzed,
                'total_opportunities': total_count_in_histogram,
                'total_player_moves': total_player_moves,
                'games_with_moves': games_with_moves,
                'source': 'missed-opportunities',
                'timestamp': datetime.now().isoformat()
            })
        
        if not os.path.exists(csv_path):
            return jsonify({
                'error': 'Analysis results not found. Run pre_analyze_v4.py first.',
                'instructions': 'python pre_analyze_v4.py'
            }), 404
        
        # Load from CSV
        print(f"\n📊 Loading missed opportunities from {csv_path}...", flush=True)
        if username_filter:
            print(f"  Filtering for player: {username_filter}", flush=True)
        
        # Load full CSV
        df = pd.read_csv(csv_path)
        
        # Filter out overlapping opportunities
        if 'excluded_overlap' in df.columns:
            df = df[df['excluded_overlap'] != 1]
        
        # Filter out opportunities with material imbalance >= 9
        df['material_diff'] = df['fen_before'].apply(lambda fen: abs(calculate_material_diff_from_fen(fen)))
        df = df[df['material_diff'] < 9]
        df = df.drop(columns=['material_diff'])  # Remove temporary column
        
        # Filter by username if specified
        if username_filter:
            df = df[df['username'].str.lower() == username_filter.lower()]
        
        # Filter by ELO if specified
        if min_elo > 0 or max_elo < 3000:
            elo_map = load_game_elo_data()
            
            def get_player_elo(row):
                """Get the player's ELO for this game from the cache."""
                game_url = row['game_url']
                username = row['username'].lower()
                
                if game_url in elo_map and username in elo_map[game_url]:
                    return elo_map[game_url][username]
                return 0
            
            df['player_elo'] = df.apply(get_player_elo, axis=1)
            df = df[(df['player_elo'] >= min_elo) & (df['player_elo'] <= max_elo)]
            df = df.drop(columns=['player_elo'])  # Remove temporary column
        
        if len(df) == 0:
            return jsonify({
                'username': username_filter or 'All Players',
                'errors': [],
                'histogram': {'delta_bins': [], 't_bins': [], 'counts': []},
                'total_errors': 0,
                'games_analyzed': 0,
                'source': 'missed-opportunities',
                'timestamp': datetime.now().isoformat()
            })
        
        # Convert to opportunities format
        opportunities = []
        for _, row in df.iterrows():
            # Parse pv_evals
            pv_evals = []
            if pd.notna(row.get('pv_evals', '')) and row['pv_evals']:
                try:
                    pv_evals = [float(e) for e in str(row['pv_evals']).split('|') if e]
                except:
                    pass
            
            # Get eval_before
            eval_before = 0
            if pd.notna(row.get('eval_before', '')):
                try:
                    eval_before = float(row['eval_before'])
                except:
                    pass
            
            t_engine_raw = int(row['t_turns_engine'])
            t_engine_display = t_engine_raw

            t_actual_raw = None
            try:
                if pd.notna(row.get('t_turns_actual', '')) and str(row.get('t_turns_actual', '')).strip() != '':
                    t_actual_raw = int(float(row['t_turns_actual']))
            except:
                t_actual_raw = None

            t_actual_display = None
            if t_actual_raw is not None:
                t_actual_display = max(1, t_actual_raw - 2)

            pv_moves_list = row['pv_moves'].split('|') if pd.notna(row['pv_moves']) and row['pv_moves'] else []
            # Keep PV moves up to the raw value so users can see the actual material gain
            pv_moves_list = pv_moves_list[:t_engine_raw]
            pv_evals = pv_evals[:t_engine_raw] if pv_evals else pv_evals

            # For mate opportunities, opportunity_cp might be NaN
            # For mate, we use a high value for histogram purposes
            if row['opportunity_kind'] == 'mate':
                delta_cp = 1000  # Treat mate as very high value
                mate_in = int(row['mate_in']) if pd.notna(row.get('mate_in')) else None
            else:
                delta_cp = int(row['opportunity_cp']) if pd.notna(row['opportunity_cp']) else 0
                mate_in = None

            # Calculate material differential at the time of opponent's mistake
            # Filter out opportunities where material imbalance >= 9 points
            material_diff = calculate_material_diff_from_fen(row['fen_before'])
            if abs(material_diff) >= 9:
                continue  # Skip this opportunity - too much material imbalance
            
            opp = {
                'delta_cp': delta_cp,
                't_plies': t_engine_display,
                'ply_index': int(row['opponent_move_ply_index']),
                'move_san': row['opponent_move_san'],
                'move_uci': row['opponent_move_uci'],
                'best_move_uci': row['best_reply_uci'],
                'best_move_san': row['best_reply_san'],
                'fen': row['fen_before'],
                'fen_after': row['fen_after'],
                'pv_moves': pv_moves_list,
                'pv_evals': pv_evals,
                'eval_before': eval_before,
                'game_url': row['game_url'],
                'opportunity_cp': delta_cp,
                'opportunity_kind': row['opportunity_kind'],
                'mate_in': mate_in,
                'target_pawns': int(row['target_pawns']),
                'converted_actual': int(row['converted_actual']),
                'conversion_method': row.get('conversion_method') or ('missed' if int(row['converted_actual']) == 0 else 'actual'),
                't_plies_raw': t_engine_raw,
                't_turns_actual': t_actual_display,
                't_turns_actual_raw': t_actual_raw,
            }
            opportunities.append(opp)
        
        # Filter to only opportunities that will appear in histogram (>= 100cp)
        opportunities_in_histogram = [opp for opp in opportunities if opp['delta_cp'] >= 100]
        
        # Debug logging
        print(f"\n📊 DEBUG for {username_filter}:", flush=True)
        print(f"  Total opportunities: {len(opportunities)}", flush=True)
        print(f"  Opportunities >= 100cp: {len(opportunities_in_histogram)}", flush=True)
        
        # Count missed before histogram
        missed_before_histogram = [opp for opp in opportunities_in_histogram if opp['converted_actual'] == 0]
        print(f"  Missed opportunities >= 100cp: {len(missed_before_histogram)}", flush=True)
        
        # Compute histogram for opportunities in range
        histogram_data = compute_histogram(opportunities_in_histogram)
        
        # Compute histogram for MISSED opportunities only (>= 100cp)
        missed_opportunities = [opp for opp in opportunities_in_histogram if opp['converted_actual'] == 0]
        missed_histogram = compute_histogram(missed_opportunities)
        
        # Count what's actually in the histogram (sum all cells)
        missed_count_in_histogram = sum(sum(row) for row in missed_histogram['counts'])
        total_count_in_histogram = sum(sum(row) for row in histogram_data['counts'])
        
        print(f"  Missed in histogram cells: {missed_count_in_histogram}", flush=True)
        print(f"  Total in histogram cells: {total_count_in_histogram}", flush=True)
        
        # Print all missed opportunities and their bin assignments
        print(f"\n  All {len(missed_before_histogram)} missed opportunities:", flush=True)
        for i, opp in enumerate(missed_before_histogram, 1):
            print(f"    {i}. delta_cp={opp['delta_cp']}, t_plies={opp['t_plies']}", flush=True)
        
        print(f"\n  Histogram cell counts:", flush=True)
        for i, (delta_label, row) in enumerate(zip(missed_histogram['delta_bins'], missed_histogram['counts'])):
            for j, (t_label, count) in enumerate(zip(missed_histogram['t_bins'], row)):
                if count > 0:
                    print(f"    [{delta_label} cp, {t_label} moves]: {count}", flush=True)
        
        # Get total games from fetched_games_v5.json
        total_games_map = load_total_games_from_json()
        current_username = username_filter or df.iloc[0]['username']
        total_games_analyzed = total_games_map.get(current_username.lower(), df['game_index'].nunique())
        
        result = {
            'username': current_username,
            'errors': opportunities_in_histogram,  # Only send opportunities that appear in histogram
            'histogram': histogram_data,
            'total_errors': len(opportunities_in_histogram),
            'missed_count': missed_count_in_histogram,  # Count from histogram
            'converted_count': total_count_in_histogram - missed_count_in_histogram,
            'games_analyzed': df['game_index'].nunique(),  # Games with opportunities
            'total_games_analyzed': total_games_analyzed,  # Total games from chess.com
            'total_opportunities': total_count_in_histogram,  # Total opportunities in histogram
            'source': 'missed-opportunities',
            'timestamp': datetime.now().isoformat()
        }
        
        print(f"✓ Loaded {len(opportunities)} total opportunities ({missed_count_in_histogram} missed in histogram, {total_count_in_histogram - missed_count_in_histogram} converted) from {result['games_analyzed']} games", flush=True)
        
        return jsonify(result)
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ── New endpoints: submit analysis, poll progress, search users ────────────

@app.route('/api/submit-analysis', methods=['POST'])
def submit_analysis():
    """
    Fetch games from chess.com, upload manifest, submit Batch array job.
    Body: {"username": "...", "num_games": 500}
    Returns: {"job_id": "...", "total_games": N}
    """
    if not _batch_available:
        return jsonify({"error": "Batch infrastructure not configured (missing AWS credentials or env vars)"}), 503

    if not tt_db.db_enabled():
        return jsonify({"error": "Database not configured"}), 503

    data = request.get_json(force=True)
    username = (data.get("username") or "").strip().lower()
    num_games = int(data.get("num_games", 500))

    if not username:
        return jsonify({"error": "username is required"}), 400

    try:
        games = chesscom.fetch_recent_games(username, n=num_games)
    except Exception as e:
        return jsonify({"error": f"Failed to fetch games from chess.com: {e}"}), 502

    if not games:
        return jsonify({"error": f"No games found for chess.com user '{username}'"}), 404

    already_done = _db_get_analyzed_urls(username)

    # Backfill `rules` for games already in tt_games (they were analyzed before
    # we started recording variant). This way Pull Data on an existing player
    # also fixes their historical variant labels in the ELO time series.
    refresh_rows = [
        (g["url"], g.get("rules") or "chess")
        for g in games
        if g["url"] in already_done
    ]
    if refresh_rows:
        _conn = None
        try:
            _conn = tt_db.get_conn()
            with _conn.cursor() as _cur:
                _cur.executemany(
                    "UPDATE tt_games SET rules = %s, updated_at = NOW() "
                    "WHERE username = %s AND game_url = %s AND rules IS DISTINCT FROM %s",
                    [(rules, username, url, rules) for url, rules in refresh_rows],
                )
            _conn.commit()
            print(
                f"[INFO] backfilled `rules` for {len(refresh_rows)} existing "
                f"games of {username}", flush=True,
            )
        except Exception as _e:
            # Don't block the submit on a backfill failure — log and proceed.
            print(f"[WARN] rules backfill failed for {username}: {_e}", flush=True)
        finally:
            if _conn is not None:
                _conn.close()

    new_games = [g for g in games if g["url"] not in already_done]

    if not new_games:
        return jsonify({"job_id": None, "total_games": 0, "skipped": len(games),
                        "message": "All requested games have already been analyzed."})

    try:
        conn = tt_db.get_conn()
        job_id = tt_batch.submit_analysis(username, new_games, conn)
        conn.close()
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"Failed to submit analysis job: {e}"}), 500

    return jsonify({"job_id": job_id, "total_games": len(new_games), "skipped": len(games) - len(new_games)})


@app.route('/api/job-status/<job_id>', methods=['GET'])
def job_status(job_id: str):
    """
    Poll progress for a running analysis job.
    Returns: {job_id, username, status, total_games, games_done, games_failed, pct_done}
    """
    if not tt_db.db_enabled():
        return jsonify({"error": "Database not configured"}), 503

    conn = tt_db.get_conn()
    try:
        status = tt_batch.get_job_status(job_id, conn)
    finally:
        conn.close()

    if status is None:
        return jsonify({"error": "Job not found"}), 404

    return jsonify(status)


@app.route('/api/search-user', methods=['GET'])
def search_user():
    """
    Check if a chess.com username exists and return basic info.
    Query params: ?username=...
    """
    username = (request.args.get("username") or "").strip().lower()
    if not username:
        return jsonify({"error": "username is required"}), 400

    try:
        r = __import__("requests").get(
            f"https://api.chess.com/pub/player/{username}",
            headers={"User-Agent": chesscom.USER_AGENT},
            timeout=10,
        )
        if r.status_code == 404:
            return jsonify({"exists": False, "username": username})
        r.raise_for_status()
        profile = r.json()
        return jsonify({
            "exists": True,
            "username": profile.get("username", username),
            "player_id": profile.get("player_id"),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route('/api/active-job', methods=['GET'])
def active_job():
    """
    Return the most recent non-completed job for a username so the
    frontend can resume polling after a tab close/reopen.
    Query params: ?username=...
    """
    if not tt_db.db_enabled():
        return jsonify({"error": "Database not configured"}), 503

    username = (request.args.get("username") or "").strip().lower()
    if not username:
        return jsonify({"error": "username is required"}), 400

    rows = _db_fetchall(
        """
        SELECT job_id, username, status, total_games, games_done, games_failed
          FROM tt_jobs
         WHERE username = %s AND status IN ('pending', 'running')
         ORDER BY created_at DESC
         LIMIT 1
        """,
        (username,),
    )
    if not rows:
        return jsonify({"active": False})

    r = rows[0]
    total = r["total_games"] or 1
    done = r["games_done"] or 0
    return jsonify({
        "active": True,
        "job_id": r["job_id"],
        "username": r["username"],
        "status": r["status"],
        "total_games": total,
        "games_done": done,
        "games_failed": r["games_failed"] or 0,
        "pct_done": round(done / total * 100, 1),
    })


@app.route('/api/queue-info', methods=['GET'])
def queue_info():
    """
    Return queue position info.  When `job_id` is provided, returns how many
    jobs (from other users) were submitted before this one and are still active.
    """
    if not tt_db.db_enabled():
        return jsonify({"error": "Database not configured"}), 503

    job_id = request.args.get("job_id")

    rows = _db_fetchall(
        """
        SELECT COALESCE(SUM(total_games - games_done - games_failed), 0) AS games_ahead,
               COUNT(*) AS active_jobs
          FROM tt_jobs
         WHERE status IN ('pending', 'running')
        """,
    )
    r = rows[0] if rows else {"games_ahead": 0, "active_jobs": 0}

    position = 0
    if job_id:
        pos_rows = _db_fetchall(
            """
            SELECT COUNT(*) AS ahead
              FROM tt_jobs a
             WHERE a.status IN ('pending', 'running')
               AND a.created_at < (
                     SELECT created_at FROM tt_jobs WHERE job_id = %s
                   )
            """,
            (job_id,),
        )
        if pos_rows:
            position = int(pos_rows[0]["ahead"])

    return jsonify({
        "games_ahead": int(r["games_ahead"]),
        "active_jobs": int(r["active_jobs"]),
        "position": position,
    })


# ── Training Tactics ──────────────────────────────────────────────────────────
# 3×3 heatmap binning matches Heatmap.tsx / DifferenceHeatmap.tsx exactly.
_TT_DELTA_LABELS = ['100-299', '300-799', '800+']
_TT_T_LABELS     = ['1-3', '5-7', '9+']
_TT_EXCLUDED_CELL = (0, 2)  # (delta_idx=100-299, t_idx=9+) — excluded from heatmap


def _tt_delta_idx(delta_cp: int, kind: str) -> Optional[int]:
    if kind == "mate":
        return 2  # 800+ bucket holds mates
    if delta_cp >= 800:
        return 2
    if delta_cp >= 300:
        return 1
    if delta_cp >= 100:
        return 0
    return None


def _tt_t_idx(t_plies: int) -> Optional[int]:
    if t_plies >= 8:
        return 2
    if t_plies >= 4:
        return 1
    if t_plies >= 1:
        return 0
    return None


def _tt_bin_opp(opp: Dict[str, Any]) -> Optional[tuple]:
    """Return (delta_idx, t_idx) for an opportunity, or None if it doesn't fit."""
    kind = opp.get("opportunity_kind") or "cp"
    if kind == "mate":
        delta_cp = 1000  # arbitrary large value to land in 800+
    else:
        try:
            delta_cp = int(opp.get("opportunity_cp") or 0)
        except (TypeError, ValueError):
            delta_cp = 0
    try:
        t_plies = int(opp.get("t_turns_engine") or 0)
    except (TypeError, ValueError):
        t_plies = 0

    di = _tt_delta_idx(delta_cp, kind)
    ti = _tt_t_idx(t_plies)
    if di is None or ti is None:
        return None
    if (di, ti) == _TT_EXCLUDED_CELL:
        return None
    return (di, ti)


def _tt_serialize_opp(r: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a raw tt_opportunities row into the puzzle format the UI consumes."""
    pv_moves_str = r.get("pv_moves") or ""
    pv_moves_list = [m for m in pv_moves_str.split("|") if m] if pv_moves_str else []

    pv_evals_str = r.get("pv_evals") or ""
    pv_evals: List[float] = []
    if pv_evals_str:
        for token in pv_evals_str.split("|"):
            if not token:
                continue
            try:
                pv_evals.append(float(token))
            except (TypeError, ValueError):
                pass

    try:
        eval_before = float(r.get("eval_before") or 0)
    except (TypeError, ValueError):
        eval_before = 0.0

    kind = r.get("opportunity_kind") or "cp"
    if kind == "mate":
        delta_cp = 1000
        mate_in = int(r.get("mate_in")) if r.get("mate_in") is not None else None
    else:
        try:
            delta_cp = int(r.get("opportunity_cp") or 0)
        except (TypeError, ValueError):
            delta_cp = 0
        mate_in = None

    try:
        t_engine = int(r.get("t_turns_engine") or 0)
    except (TypeError, ValueError):
        t_engine = 0

    # Trim PV to the engine's stated horizon (matches /api/analysis behavior).
    if t_engine and pv_moves_list:
        pv_moves_list = pv_moves_list[:t_engine]
    if t_engine and pv_evals:
        pv_evals = pv_evals[:t_engine]

    return {
        'delta_cp': delta_cp,
        't_plies': t_engine,
        'ply_index': int(r.get("opponent_move_ply_index") or 0),
        'move_san': r.get("opponent_move_san") or "",
        'move_uci': r.get("opponent_move_uci") or "",
        'best_move_uci': r.get("best_reply_uci") or "",
        'best_move_san': r.get("best_reply_san") or "",
        'fen': r.get("fen_before") or "",
        'fen_after': r.get("fen_after") or "",
        'pv_moves': pv_moves_list,
        'pv_evals': pv_evals,
        'eval_before': eval_before,
        'game_url': r.get("game_url") or "",
        'opportunity_cp': delta_cp,
        'opportunity_kind': kind,
        'mate_in': mate_in,
        'target_pawns': int(r.get("target_pawns") or 0),
        'converted_actual': int(r.get("converted_actual") or 0),
        'conversion_method': r.get("conversion_method") or (
            'missed' if int(r.get("converted_actual") or 0) == 0 else 'actual'
        ),
    }


@app.route('/api/training-tactics', methods=['GET'])
def training_tactics():
    """
    Return 10 training puzzles for `username`, biased toward heatmap cells where
    the player lags the field (filtered by ELO range).

    Query params:
      username  (required)
      min_elo   (optional, default 0)
      max_elo   (optional, default 3000)
      n         (optional, default 10)
    """
    if not tt_db.db_enabled():
        return jsonify({"error": "Database not configured"}), 503

    username = (request.args.get("username") or "").strip().lower()
    if not username:
        return jsonify({"error": "username is required"}), 400

    try:
        min_elo = int(request.args.get("min_elo", 0))
        max_elo = int(request.args.get("max_elo", 3000))
        n_target = max(1, min(20, int(request.args.get("n", 10))))
    except (TypeError, ValueError):
        return jsonify({"error": "min_elo / max_elo / n must be integers"}), 400

    # ── Pull all this user's opportunities ───────────────────────────────────
    player_rows = _db_fetchall(
        """
        SELECT
          username, game_url, game_index, event_index,
          opportunity_kind, opportunity_cp, mate_in, target_pawns,
          t_turns_engine, converted_actual, conversion_method, t_turns_actual,
          opponent_move_ply_index, opponent_move_san, opponent_move_uci,
          best_reply_san, best_reply_uci,
          fen_before, fen_after,
          pv_moves, pv_evals, eval_before,
          white_player, black_player, player_color, time_control, game_result, end_time
        FROM tt_opportunities
        WHERE username = %s
        """,
        (username,),
    )
    if not player_rows:
        return jsonify({
            "error": f"No opportunities found for {username}. Pull and analyze games first.",
        }), 404

    # ── Bin player & field opportunities into 3×3 heatmap cells ──────────────
    player_by_cell: Dict[tuple, List[Dict[str, Any]]] = {}
    player_missed_by_cell: Dict[tuple, int] = {}
    player_total_by_cell: Dict[tuple, int] = {}

    for r in player_rows:
        cell = _tt_bin_opp(r)
        if cell is None:
            continue
        player_by_cell.setdefault(cell, []).append(r)
        player_total_by_cell[cell] = player_total_by_cell.get(cell, 0) + 1
        if int(r.get("converted_actual") or 0) == 0:
            player_missed_by_cell[cell] = player_missed_by_cell.get(cell, 0) + 1

    # Field rows for the comparator. We filter by ELO range using tt_games joined
    # via game_url+username, mirroring the /api/analysis ELO filter.
    field_rows = _db_fetchall(
        """
        SELECT o.opportunity_kind, o.opportunity_cp, o.mate_in,
               o.t_turns_engine, o.converted_actual,
               g.player_elo
          FROM tt_opportunities o
          JOIN tt_games g
            ON g.username = o.username AND g.game_url = o.game_url
         WHERE g.player_elo IS NOT NULL
           AND g.player_elo BETWEEN %s AND %s
        """,
        (min_elo, max_elo),
    )

    field_missed_by_cell: Dict[tuple, int] = {}
    field_total_by_cell: Dict[tuple, int] = {}
    for fr in field_rows:
        cell = _tt_bin_opp(fr)
        if cell is None:
            continue
        field_total_by_cell[cell] = field_total_by_cell.get(cell, 0) + 1
        if int(fr.get("converted_actual") or 0) == 0:
            field_missed_by_cell[cell] = field_missed_by_cell.get(cell, 0) + 1

    # ── Build per-cell summary (player_pct, field_pct, diff) ─────────────────
    summary: Dict[str, Dict[str, Any]] = {}
    for di, _dlabel in enumerate(_TT_DELTA_LABELS):
        for ti, _tlabel in enumerate(_TT_T_LABELS):
            cell = (di, ti)
            if cell == _TT_EXCLUDED_CELL:
                continue
            p_total = player_total_by_cell.get(cell, 0)
            p_miss  = player_missed_by_cell.get(cell, 0)
            f_total = field_total_by_cell.get(cell, 0)
            f_miss  = field_missed_by_cell.get(cell, 0)
            p_pct = (p_miss / p_total * 100) if p_total else None
            f_pct = (f_miss / f_total * 100) if f_total else None
            diff = (f_pct - p_pct) if (p_pct is not None and f_pct is not None) else None
            summary[f"{di},{ti}"] = {
                "delta_label": _TT_DELTA_LABELS[di],
                "t_label":     _TT_T_LABELS[ti],
                "player_total": p_total,
                "player_missed": p_miss,
                "player_missrate_pct": p_pct,
                "field_total": f_total,
                "field_missed": f_miss,
                "field_missrate_pct": f_pct,
                "diff": diff,
            }

    # ── Sample ──────────────────────────────────────────────────────────────
    rng = random.Random()

    eligible_cells = [c for c, opps in player_by_cell.items() if opps]
    if not eligible_cells:
        return jsonify({"error": f"No eligible opportunities for {username}."}), 404

    def diff_for(cell: tuple) -> Optional[float]:
        s = summary.get(f"{cell[0]},{cell[1]}")
        return s["diff"] if s else None

    # Cells where the player is behind: diff is None (no field comparator) →
    # treat as 0 lag; otherwise use max(0, -diff).
    def lag_for(cell: tuple) -> float:
        d = diff_for(cell)
        if d is None:
            return 0.0
        return max(0.0, -d)

    # Quotas:
    #   2 from "green" cells (diff >= 5)
    #   2 from the 9+ moves column (t_idx == 2)
    #   the rest from lagging cells, weighted by lag × sqrt(n_player_opps_in_cell)
    green_cells   = [c for c in eligible_cells if (diff_for(c) is not None and diff_for(c) >= 5)]
    long_t_cells  = [c for c in eligible_cells if c[1] == 2]
    lagging_cells = [c for c in eligible_cells if lag_for(c) > 0]

    # If we have no clear "green" cells, allow any cell with diff > 0.
    if not green_cells:
        green_cells = [c for c in eligible_cells if (diff_for(c) is not None and diff_for(c) > 0)]

    n_green     = min(2, len(green_cells))
    n_long_t    = min(2, len(long_t_cells))

    # Cell quota counts (we may sample multiple puzzles from the same cell).
    cell_pick_quotas: List[tuple] = []

    def add_cells(target_n: int, candidates: List[tuple], weight_fn) -> None:
        if target_n <= 0 or not candidates:
            return
        weights = [max(1e-6, weight_fn(c)) for c in candidates]
        for _ in range(target_n):
            chosen = rng.choices(candidates, weights=weights, k=1)[0]
            cell_pick_quotas.append(chosen)

    # Green: weight by # opportunities (so big green cells dominate)
    add_cells(n_green,  green_cells,  lambda c: len(player_by_cell[c]))
    # 9+ column: prefer cells where player lags more
    add_cells(n_long_t, long_t_cells, lambda c: (1.0 + lag_for(c) / 10.0) * len(player_by_cell[c]))

    n_remaining = n_target - len(cell_pick_quotas)
    if n_remaining > 0:
        weighting_pool = lagging_cells if lagging_cells else eligible_cells
        add_cells(
            n_remaining,
            weighting_pool,
            lambda c: (lag_for(c) + 1.0) * len(player_by_cell[c]) ** 0.5,
        )

    # ── Pick puzzles, deduplicating by (game_url, event_index) ──────────────
    used_keys: set = set()
    puzzles: List[Dict[str, Any]] = []
    # Shuffle inside each cell so multiple picks from the same cell give different puzzles
    cell_pools: Dict[tuple, List[Dict[str, Any]]] = {}
    for cell, opps in player_by_cell.items():
        pool = list(opps)
        rng.shuffle(pool)
        cell_pools[cell] = pool

    for cell in cell_pick_quotas:
        pool = cell_pools.get(cell) or []
        chosen = None
        while pool:
            cand = pool.pop()
            key = (cand.get("game_url"), cand.get("event_index"))
            if key in used_keys:
                continue
            chosen = cand
            used_keys.add(key)
            break
        if chosen is None:
            continue
        serialized = _tt_serialize_opp(chosen)
        serialized["cell"] = {
            "delta_idx": cell[0],
            "t_idx": cell[1],
            "delta_label": _TT_DELTA_LABELS[cell[0]],
            "t_label": _TT_T_LABELS[cell[1]],
        }
        puzzles.append(serialized)

    # If we ended up with fewer than requested (e.g. small cell ran out), top up
    # from any remaining eligible opportunities, weighted by lag.
    if len(puzzles) < n_target:
        remaining = []
        for cell, pool in cell_pools.items():
            for cand in pool:
                key = (cand.get("game_url"), cand.get("event_index"))
                if key in used_keys:
                    continue
                remaining.append((cell, cand))
        rng.shuffle(remaining)
        # Sort so puzzles from lagging cells come first
        remaining.sort(key=lambda pair: -lag_for(pair[0]))
        for cell, cand in remaining:
            if len(puzzles) >= n_target:
                break
            key = (cand.get("game_url"), cand.get("event_index"))
            if key in used_keys:
                continue
            used_keys.add(key)
            serialized = _tt_serialize_opp(cand)
            serialized["cell"] = {
                "delta_idx": cell[0],
                "t_idx": cell[1],
                "delta_label": _TT_DELTA_LABELS[cell[0]],
                "t_label": _TT_T_LABELS[cell[1]],
            }
            puzzles.append(serialized)

    return jsonify({
        "username": username,
        "min_elo": min_elo,
        "max_elo": max_elo,
        "puzzles": puzzles,
        "cell_summary": summary,
        "delta_labels": _TT_DELTA_LABELS,
        "t_labels": _TT_T_LABELS,
        "excluded_cell": list(_TT_EXCLUDED_CELL),
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"\n Starting Tactic Trainer Backend...")
    print(f"   Mode: {'DB' if tt_db.db_enabled() else 'CSV'}")
    print(f"   Batch: {'available' if _batch_available else 'NOT available'}")
    print(f"   Port: {port}")

    load_game_elo_data()

    print(f"\n Server ready at http://localhost:{port}\n")

    app.run(host='0.0.0.0', port=port, debug=True)


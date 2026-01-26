"""
Flask backend for Tactic Trainer (CSV-based).
Serves pre-computed missed opportunity analysis from CSV.
"""

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import pandas as pd
import json
import os
import config
from datetime import datetime
from typing import Optional, List, Dict, Any

import db as tt_db

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
        "SELECT COUNT(*) AS n FROM tt_records WHERE record_kind='game' AND username=%s",
        (username.lower(),),
    )
    return int(rows[0]["n"]) if rows else 0


def _db_load_opportunities(username_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    params: List[Any] = []
    where = ["record_kind='opportunity'"]
    if username_filter:
        where.append("username=%s")
        params.append(username_filter.lower())

    # exclude overlaps at the DB level
    where.append("(excluded_overlap IS NULL OR excluded_overlap <> 1)")

    q = f"""
        SELECT
          username, game_url, game_index, event_index,
          opportunity_kind, opportunity_cp, mate_in, target_pawns,
          t_turns_engine, converted_actual, t_turns_actual,
          opponent_move_ply_index, opponent_move_san, opponent_move_uci,
          best_reply_san, best_reply_uci,
          fen_before, fen_after,
          pv_moves, pv_evals, eval_before,
          white_player, black_player, player_color, time_control, game_result, end_time,
          converted_by_resignation, excluded_overlap, overlap_owner_ply, overlap_owner_event
        FROM tt_records
        WHERE {' AND '.join(where)}
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
            'converted_actual': int(row['converted_actual'])
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
      - opportunity_cp: 100-299, 300-499, 500-799, 800+ (mate is included in 800+)
      - t_turns: 1-3, 5-7, 9-15, 17+ (we round up boundary values into the next bucket)
    """
    # Define bins (no 0 column)
    delta_bins = [100, 300, 500, 800, float('inf')]
    delta_labels = ['100-299', '300-499', '500-799', '800+']

    # Keep internal edges contiguous but label as requested. Values on the boundary
    # (4, 8, 16) are effectively rounded up into the next labeled bucket.
    t_bins = [1, 4, 8, 16, float('inf')]
    t_labels = ['1-3', '5-7', '9-15', '17+']

    # Initialize histogram (4 rows x 4 cols)
    histogram = {
        'delta_bins': delta_labels,
        't_bins': t_labels,
        'counts': [[0 for _ in t_labels] for _ in delta_labels]
    }
    
    # Count errors in each bin
    for error in errors:
        # Mate opportunities are included in 800+ bucket
        is_mate = error.get('opportunity_kind') == 'mate'
        delta_cp = 1000 if is_mate else error['delta_cp']

        # Find delta bin (only include if >= 100)
        if delta_cp < 100:
            continue  # Skip opportunities below threshold

        delta_idx = None
        for idx in range(len(delta_bins) - 1):
            if delta_cp >= delta_bins[idx] and delta_cp < delta_bins[idx + 1]:
                delta_idx = idx
                break

        if delta_idx is None:
            delta_idx = len(delta_labels) - 1  # 800+
        
        # Find t bin
        t_plies = error['t_plies']
        t_idx = None
        for idx in range(len(t_bins) - 1):
            if t_plies >= t_bins[idx] and t_plies < t_bins[idx + 1]:
                t_idx = idx
                break
        
        if t_idx is None:
            t_idx = len(t_labels) - 1  # 17+
        
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
                t_engine_display = max(1, t_engine_raw - 2) if t_engine_raw else 0

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

                # total games: prefer explicit game rows (record_kind='game'), fallback to distinct game_url
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
                # We use a "sustain for 3 plies" rule in the pre-analysis.
                # The CSV's t_turns_engine is the 3rd ply in the 3-ply hold window,
                # so subtract 2 to get the first ply where the threshold is held.
                t_engine_display = max(1, t_engine_raw - 2)
                
                # For mate opportunities, opportunity_cp might be NaN
                # For mate, we use a high value for histogram purposes
                if row['opportunity_kind'] == 'mate':
                    delta_cp = 1000  # Treat mate as very high value
                else:
                    delta_cp = int(row['opportunity_cp']) if pd.notna(row['opportunity_cp']) else 0
                
                user_opportunities.append({
                    'delta_cp': delta_cp,
                    't_plies': t_engine_display,
                    'converted_actual': int(row['converted_actual'])
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
                t_engine_display = max(1, t_engine_raw - 2) if t_engine_raw else 0

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
                    't_plies_raw': t_engine_raw,
                    't_turns_actual': None,
                    't_turns_actual_raw': r.get("t_turns_actual"),
                }

                opportunities.append(opp)
                games_seen.add(r.get("game_url") or "")

            # Filter by ELO if specified
            if min_elo > 0 or max_elo < 3000:
                elo_map = load_game_elo_data()
                filtered_opps = []
                
                for opp in opportunities:
                    game_url = opp['game_url']
                    # Get username from the first opportunity (assumes single user or all users)
                    username = username_filter.lower() if username_filter else None
                    
                    # If no username filter, we need to determine which player this opportunity belongs to
                    if not username:
                        # For "all players" mode, check each tracked player
                        player_elo = None
                        if game_url in elo_map:
                            for tracked_user in elo_map[game_url].keys():
                                if tracked_user in ['k2f4x', 'key_kay', 'jtkms']:
                                    player_elo = elo_map[game_url][tracked_user]
                                    break
                        
                        if player_elo is not None and min_elo <= player_elo <= max_elo:
                            filtered_opps.append(opp)
                    else:
                        # Single user mode
                        if game_url in elo_map and username in elo_map[game_url]:
                            player_elo = elo_map[game_url][username]
                            if min_elo <= player_elo <= max_elo:
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
            if username_filter:
                total_games_analyzed = _db_count_games_for_user(username_filter)
                if total_games_analyzed == 0:
                    total_games_analyzed = len(games_seen)

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
            
            # We use a "sustain for 3 plies" rule in the pre-analysis.
            # The CSV's t_turns_engine corresponds to the ply where the advantage has been
            # sustained for 3 consecutive plies (i.e. the 3rd ply in the window).
            # For visualization and PV navigation, we want the FIRST ply where the threshold
            # is crossed and then held, so we subtract 2 plies.
            t_engine_raw = int(row['t_turns_engine'])
            t_engine_display = max(1, t_engine_raw - 2)

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
                # Keep raw times too (debug/inspection)
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


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"\n🚀 Starting Tactic Trainer Backend...")
    print(f"   Mode: CSV-based (missed opportunities)")
    print(f"   Port: {port}")
    print(f"   CSV file: analysis_results_v5.fixed4.csv")
    
    # Preload ELO data
    print(f"   Loading ELO data...")
    load_game_elo_data()
    
    print(f"\n✓ Server ready at http://localhost:{port}\n")
    
    app.run(host='0.0.0.0', port=port, debug=True)


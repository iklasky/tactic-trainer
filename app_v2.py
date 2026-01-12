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

app = Flask(__name__, static_folder='dist')
CORS(app)

# Cache for CSV data
analysis_cache = None
analysis_cache_time = None


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


def compute_histogram(errors: list) -> dict:
    """
    Compute 2D histogram for visualization.
    Bins: opportunity_cp (100-200, 200-300, 300-500, 500-800, 800+)
          t_turns (1-3, 4-7, 8-15, 16-31, 32+)
    """
    # Define bins (removed 0 turn column)
    delta_bins = [100, 200, 300, 500, 800, float('inf')]
    delta_labels = ['100-199', '200-299', '300-499', '500-799', '800+']
    
    t_bins = [1, 4, 8, 16, 32, float('inf')]
    t_labels = ['1-3', '4-7', '8-15', '16-31', '32+']
    
    # Initialize histogram
    histogram = {
        'delta_bins': delta_labels,
        't_bins': t_labels,
        'counts': [[0 for _ in t_labels] for _ in delta_labels]
    }
    
    # Count errors in each bin
    for error in errors:
        delta_cp = error['delta_cp']
        t_plies = error['t_plies']
        
        # Find delta bin
        for idx, threshold in enumerate(delta_bins[:-1]):
            if delta_cp < delta_bins[idx + 1]:
                delta_idx = idx
                break
        else:
            delta_idx = len(delta_labels) - 1
        
        # Find t bin
        for idx, threshold in enumerate(t_bins[:-1]):
            if t_plies < t_bins[idx + 1]:
                t_idx = idx
                break
        else:
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
        'mode': 'missed-opportunities (CSV)',
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
        csv_path = 'analysis_results.csv'
        
        if not os.path.exists(csv_path):
            return jsonify({'players': []}), 200
        
        df = pd.read_csv(csv_path)
        
        # Get unique usernames and their stats
        players = []
        for username in df['username'].unique():
            user_data = df[df['username'] == username]
            players.append({
                'username': username,
                'opportunities': len(user_data),
                'games': user_data['game_index'].nunique() if 'game_index' in user_data else 0
            })
        
        return jsonify({'players': players})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/analysis', methods=['GET'])
def get_analysis():
    """
    Get pre-computed missed opportunity analysis from CSV.
    Optional query param: username (filter by specific player)
    """
    try:
        csv_path = 'analysis_results.csv'
        username_filter = request.args.get('username', None)
        
        if not os.path.exists(csv_path):
            return jsonify({
                'error': 'Analysis results not found. Run pre_analyze_v2.py first.',
                'instructions': 'python pre_analyze_v2.py 100'
            }), 404
        
        # Load from CSV
        print(f"\n📊 Loading missed opportunities from {csv_path}...", flush=True)
        if username_filter:
            print(f"  Filtering for player: {username_filter}", flush=True)
        
        # Load full CSV
        df = pd.read_csv(csv_path)
        
        # Filter by username if specified
        if username_filter:
            df = df[df['username'].str.lower() == username_filter.lower()]
        
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
            
            opp = {
                'delta_cp': int(row['opportunity_cp']),
                't_plies': int(row['t_turns_engine']),
                'ply_index': int(row['opponent_move_ply_index']),
                'move_san': row['opponent_move_san'],
                'move_uci': row['opponent_move_uci'],
                'best_move_uci': row['best_reply_uci'],
                'best_move_san': row['best_reply_san'],
                'fen': row['fen_before'],
                'fen_after': row['fen_after'],
                'pv_moves': row['pv_moves'].split('|') if pd.notna(row['pv_moves']) and row['pv_moves'] else [],
                'pv_evals': pv_evals,
                'eval_before': eval_before,
                'game_url': row['game_url'],
                'opportunity_cp': int(row['opportunity_cp']),
                'target_pawns': int(row['target_pawns']),
                'converted_actual': int(row['converted_actual'])
            }
            opportunities.append(opp)
        
        # Compute histogram
        histogram_data = compute_histogram(opportunities)
        
        result = {
            'username': username_filter or df.iloc[0]['username'],
            'errors': opportunities,
            'histogram': histogram_data,
            'total_errors': len(opportunities),
            'games_analyzed': df['game_index'].nunique(),
            'source': 'missed-opportunities',
            'timestamp': datetime.now().isoformat()
        }
        
        print(f"✓ Loaded {result['total_errors']} missed opportunities from {result['games_analyzed']} games", flush=True)
        
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
    print(f"   CSV file: analysis_results.csv")
    print(f"\n✓ Server ready at http://localhost:{port}\n")
    
    app.run(host='0.0.0.0', port=port, debug=True)


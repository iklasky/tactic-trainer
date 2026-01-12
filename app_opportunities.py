"""
Flask backend for tactic-trainer - Missed Opportunities version.
Loads pre-computed missed opportunity analysis from CSV.
"""

from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import json
import os
import csv
from datetime import datetime
from typing import Dict, List
import pandas as pd

import config

app = Flask(__name__, static_folder='dist', static_url_path='')
CORS(app)

# Cache for CSV data
analysis_cache = None
analysis_cache_time = None

def load_analysis_from_csv(csv_path='opportunities_results.csv'):
    """Load pre-computed opportunity analysis from CSV."""
    global analysis_cache, analysis_cache_time
    
    # Return cached data if available and file hasn't changed
    if analysis_cache is not None:
        try:
            file_mtime = os.path.getmtime(csv_path)
            if analysis_cache_time == file_mtime:
                return analysis_cache
        except:
            pass
    
    # Load CSV
    df = pd.read_csv(csv_path)
    
    # Convert to structured format (map to frontend-expected field names)
    opportunities = []
    for _, row in df.iterrows():
        opp = {
            # Map opportunity fields to what frontend expects (keeping ErrorEvent interface)
            'delta_cp': int(row['opportunity_cp']),  # Opportunity size
            't_plies': int(row['t_turns_engine']),   # Engine conversion time
            'ply_index': int(row['opponent_move_ply_index']),  # When opponent blundered
            'move_san': row['opponent_move_san'],    # Opponent's mistake
            'move_uci': row['opponent_move_uci'],
            'best_move_uci': row['best_reply_uci'],  # Your best reply
            'best_move_san': row['best_reply_san'],
            'fen': row['fen_before'],                # Before opponent mistake
            'fen_after': row['fen_after'],           # After opponent mistake
            'pv_moves': row['pv_moves'].split('|') if pd.notna(row['pv_moves']) and row['pv_moves'] else [],
            'game_url': row['game_url'],
            # Additional metadata
            'target_pawns': int(row['target_pawns']),
            'converted_actual': bool(row['converted_actual']) if pd.notna(row['converted_actual']) else False
        }
        opportunities.append(opp)
    
    analysis_cache = {
        'username': df.iloc[0]['username'] if len(df) > 0 else 'Unknown',
        'errors': opportunities,  # Keep 'errors' key for frontend compatibility
        'total_errors': len(opportunities),
        'games_analyzed': int(df['game_index'].nunique()) if len(df) > 0 else 0
    }
    
    try:
        analysis_cache_time = os.path.getmtime(csv_path)
    except:
        analysis_cache_time = None
    
    return analysis_cache


def load_test_games():
    """Load test games from JSON file."""
    json_path = os.path.join(os.path.dirname(__file__), 'test_games.json')
    with open(json_path, 'r') as f:
        data = json.load(f)
    return data


def compute_histogram(opportunities: list) -> dict:
    """
    Compute 2D histogram for visualization.
    Bins: opportunity_cp (100-200, 200-300, 300-500, 500-800, 800+)
          t_turns (1-3, 4-7, 8-15, 16-31, 32+)
    """
    # Define bins (removed 0 turn column as requested)
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
    
    # Fill histogram
    for opp in opportunities:
        opp_cp = opp['delta_cp']  # Mapped from opportunity_cp
        t_turns = opp['t_plies']   # Mapped from t_turns_engine
        
        # Skip 0 turn (immediate captures - though shouldn't happen with opportunities)
        if t_turns < 1:
            continue
        
        # Find delta bin
        delta_idx = 0
        for i in range(len(delta_bins) - 1):
            if opp_cp < delta_bins[i + 1]:
                delta_idx = i
                break
        else:
            delta_idx = len(delta_labels) - 1
        
        # Find t bin (adjusted for 1-based bins)
        t_idx = 0
        for i in range(len(t_bins) - 1):
            if t_turns <= t_bins[i + 1] - 1:
                t_idx = i
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
    csv_exists = os.path.exists('opportunities_results.csv')
    
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
            summary = {
                'url': game.get('url', ''),
                'white': game.get('white', {}).get('username', ''),
                'black': game.get('black', {}).get('username', ''),
                'result': f"{game.get('white', {}).get('result', '')} vs {game.get('black', {}).get('result', '')}",
                'time_control': game.get('time_control', ''),
                'end_time': game.get('end_time', 0)
            }
            game_summaries.append(summary)
        
        return jsonify({
            'username': username,
            'total_games': total_games,
            'games': game_summaries
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/analysis', methods=['GET'])
def get_analysis():
    """
    Get pre-computed missed opportunity analysis from CSV.
    """
    try:
        csv_path = 'opportunities_results.csv'
        
        if not os.path.exists(csv_path):
            return jsonify({
                'error': 'Opportunity analysis not found. Run pre_analyze_opportunities.py first.',
                'instructions': 'python pre_analyze_opportunities.py 100'
            }), 404
        
        # Load from CSV
        print(f"\n📊 Loading missed opportunity analysis from {csv_path}...", flush=True)
        analysis_data = load_analysis_from_csv(csv_path)
        
        # Compute histogram
        histogram_data = compute_histogram(analysis_data['errors'])
        
        result = {
            'username': analysis_data['username'],
            'errors': analysis_data['errors'],  # Frontend expects 'errors' key
            'histogram': histogram_data,
            'total_errors': analysis_data['total_errors'],
            'games_analyzed': analysis_data['games_analyzed'],
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
    print("\n" + "="*80)
    print("🚀 Tactic Trainer - Missed Opportunities Mode")
    print("="*80)
    print(f"Loading: opportunities_results.csv")
    print(f"Shows: Opponent mistakes you failed to convert")
    
    if os.path.exists('opportunities_results.csv'):
        print("✓ CSV file found")
        # Print preview
        try:
            df = pd.read_csv('opportunities_results.csv')
            print(f"✓ Contains {len(df)} missed opportunities from {df['game_index'].nunique()} games")
        except:
            pass
    else:
        print("⚠️  CSV file not found")
        print("   Run: python pre_analyze_opportunities.py 100")
    
    print("="*80 + "\n")
    
    app.run(host='0.0.0.0', port=port, debug=True)

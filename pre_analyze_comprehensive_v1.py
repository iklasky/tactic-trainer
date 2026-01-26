#!/usr/bin/env python3
"""
Comprehensive Pre-Analysis Script V1

Analyzes BOTH:
1. Received opportunities: opponent mistakes that the player could capitalize on
2. Given opportunities: player mistakes that create opportunities for opponent

Outputs:
- analysis_received_v1.csv (with converted_actual flag)
- analysis_given_v1.csv (all player mistakes, no conversion tracking)

Features:
- Multiprocessing with 6 workers
- RAM monitoring + kill-switch at 80%
- Per-worker resource reporting
- Caffeinate wrapper
- Incremental CSV writing
"""

import csv
import json
import multiprocessing as mp
import os
import subprocess
import sys
import time
from typing import List, Dict, Any

# Import the V5 analyzer
from chess_analyzer_v5 import ChessAnalyzerV5

# Configuration
GAMES_FILE = "fetched_games_v5.json"
OUTPUT_RECEIVED = "analysis_received_v1.csv"
OUTPUT_GIVEN = "analysis_given_v1.csv"
TT_WORKERS = int(os.environ.get("TT_WORKERS", "6"))
TT_MAX_RAM_PCT = float(os.environ.get("TT_MAX_RAM_PCT", "80"))

# CSV fieldnames for both outputs
FIELDNAMES_RECEIVED = [
    'username', 'game_id', 'game_url', 'ply_index', 'player_color',
    'opportunity_cp', 'opportunity_kind', 'mate_in',
    't_plies', 't_plies_raw',
    'fen_before', 'fen_after',
    'opponent_move_uci', 'opponent_move_san',
    'best_reply_uci', 'best_reply_san',
    'pv_moves', 'pv_evals', 'eval_before',
    'converted_actual', 'excluded_overlap'
]

FIELDNAMES_GIVEN = [
    'username', 'game_id', 'game_url', 'ply_index', 'player_color',
    'opportunity_cp', 'opportunity_kind', 'mate_in',
    't_plies', 't_plies_raw',
    'fen_before', 'fen_after',
    'player_move_uci', 'player_move_san',
    'best_move_uci', 'best_move_san',
    'pv_moves', 'pv_evals', 'eval_before',
    'excluded_overlap'
]


def load_games(filepath: str) -> List[Dict[str, Any]]:
    """Load games from JSON file."""
    with open(filepath, 'r') as f:
        data = json.load(f)
    return data.get('games', [])


def get_memory_pressure() -> tuple[str, float]:
    """
    Get macOS memory pressure status.
    Returns: (status, free_pct)
    """
    try:
        result = subprocess.run(
            ['memory_pressure'],
            capture_output=True,
            text=True,
            timeout=2
        )
        output = result.stdout
        
        # Parse status (Normal, Warning, Critical)
        status = 'Unknown'
        if 'System-wide memory free percentage:' in output:
            for line in output.split('\n'):
                if 'The system has' in line:
                    if 'normal' in line.lower():
                        status = 'Normal'
                    elif 'warning' in line.lower():
                        status = 'Warning'
                    elif 'critical' in line.lower():
                        status = 'Critical'
                elif 'System-wide memory free percentage:' in line:
                    parts = line.split(':')
                    if len(parts) == 2:
                        free_pct = float(parts[1].strip().rstrip('%'))
                        return status, free_pct
        
        return status, 0.0
    except Exception as e:
        return 'Unknown', 0.0


def get_worker_stats(pid: int) -> tuple[float, float]:
    """
    Get CPU% and RSS (MB) for a specific PID using ps.
    Returns: (cpu_pct, rss_mb)
    """
    try:
        result = subprocess.run(
            ['ps', '-p', str(pid), '-o', 'pcpu=,rss='],
            capture_output=True,
            text=True,
            timeout=1
        )
        output = result.stdout.strip()
        if output:
            parts = output.split()
            cpu_pct = float(parts[0])
            rss_kb = float(parts[1])
            rss_mb = rss_kb / 1024
            return cpu_pct, rss_mb
    except:
        pass
    return 0.0, 0.0


def analyze_single_game(args: tuple) -> Dict[str, Any]:
    """
    Worker function to analyze a single game for BOTH received and given opportunities.
    
    Returns dict with:
    - received_opps: list of received opportunities
    - given_opps: list of given opportunities
    - error: error message if any
    """
    game_data, target_username = args
    
    try:
        pgn_text = game_data['pgn']
        
        # Parse PGN to get white_player and black_player
        import io
        import chess.pgn
        pgn_io = io.StringIO(pgn_text)
        game = chess.pgn.read_game(pgn_io)
        
        white_player = game.headers.get('White', 'Unknown')
        black_player = game.headers.get('Black', 'Unknown')
        game_link = game.headers.get('Link', 'Chess.com')
        
        # Determine opponent
        if target_username.lower() == white_player.lower():
            opponent_username = black_player
        elif target_username.lower() == black_player.lower():
            opponent_username = white_player
        else:
            # Target player not in this game
            return {
                'received_opps': [],
                'given_opps': [],
                'error': None
            }
        
        analyzer = ChessAnalyzerV5()
        
        # 1. Analyze RECEIVED opportunities (opponent mistakes)
        received_opps = analyzer.analyze_game(pgn_text, target_username)
        
        # Add game_url to each
        for opp in received_opps:
            opp['game_url'] = game_link
        
        # 2. Analyze GIVEN opportunities (target player's mistakes)
        # We analyze from the OPPONENT'S perspective, but label them as the target's mistakes
        given_opps_raw = analyzer.analyze_game(pgn_text, opponent_username)
        
        # Relabel: these are the target's mistakes
        given_opps = []
        for opp in given_opps_raw:
            # Flip perspective: the "opponent" in the raw data is actually our target player
            given_opp = {
                'username': target_username,
                'game_id': opp['game_id'],
                'game_url': game_link,
                'ply_index': opp['ply_index'],
                'player_color': opp['opponent_color'],  # Target player's color
                'opportunity_cp': opp.get('opportunity_cp'),
                'opportunity_kind': opp['opportunity_kind'],
                'mate_in': opp.get('mate_in'),
                't_plies': opp['t_plies'],
                't_plies_raw': opp.get('t_plies_raw'),
                'fen_before': opp['fen_before'],
                'fen_after': opp['fen_after'],
                'player_move_uci': opp['opponent_move_uci'],  # Target's bad move
                'player_move_san': opp['opponent_move_san'],
                'best_move_uci': opp['best_reply_uci'],  # What target should have played
                'best_move_san': opp['best_reply_san'],
                'pv_moves': opp['pv_moves'],
                'pv_evals': opp['pv_evals'],
                'eval_before': opp['eval_before'],
                'excluded_overlap': 0
            }
            given_opps.append(given_opp)
        
        return {
            'received_opps': received_opps,
            'given_opps': given_opps,
            'error': None
        }
        
    except Exception as e:
        return {
            'received_opps': [],
            'given_opps': [],
            'error': str(e)
        }


def writer_process(
    result_queue: mp.Queue,
    total_games: int,
    usernames: List[str]
):
    """
    Single writer process that:
    1. Receives results from workers
    2. Writes to both CSV files
    3. Monitors system RAM
    4. Reports progress
    """
    
    # Initialize CSV writers
    f_received = open(OUTPUT_RECEIVED, 'w', newline='', encoding='utf-8')
    f_given = open(OUTPUT_GIVEN, 'w', newline='', encoding='utf-8')
    
    writer_received = csv.DictWriter(f_received, fieldnames=FIELDNAMES_RECEIVED)
    writer_given = csv.DictWriter(f_given, fieldnames=FIELDNAMES_GIVEN)
    
    writer_received.writeheader()
    writer_given.writeheader()
    
    games_processed = 0
    received_count = 0
    given_count = 0
    error_count = 0
    
    start_time = time.time()
    
    while True:
        msg = result_queue.get()
        
        if msg is None:
            break
        
        if msg['type'] == 'result':
            result = msg['data']
            
            # Write received opportunities
            for opp in result['received_opps']:
                writer_received.writerow(opp)
                received_count += 1
            
            # Write given opportunities
            for opp in result['given_opps']:
                writer_given.writerow(opp)
                given_count += 1
            
            if result['error']:
                error_count += 1
            
            games_processed += 1
            
            # Flush every 10 games
            if games_processed % 10 == 0:
                f_received.flush()
                f_given.flush()
            
            # Progress report every 25 games
            if games_processed % 25 == 0 or games_processed == total_games:
                elapsed = time.time() - start_time
                rate = games_processed / elapsed if elapsed > 0 else 0
                eta = (total_games - games_processed) / rate if rate > 0 else 0
                
                # Get memory pressure
                mem_status, mem_free_pct = get_memory_pressure()
                used_pct = 100 - mem_free_pct
                
                # Get worker stats
                worker_stats = []
                for worker_id in msg.get('worker_pids', []):
                    cpu, rss = get_worker_stats(worker_id)
                    worker_stats.append(f"W{worker_id}: {cpu:.0f}% CPU, {rss:.0f}MB")
                
                print(f"\n{'='*80}")
                print(f"Progress: {games_processed}/{total_games} games ({games_processed/total_games*100:.1f}%)")
                print(f"Received opportunities: {received_count} | Given opportunities: {given_count}")
                print(f"Errors: {error_count}")
                print(f"Rate: {rate:.1f} games/sec | ETA: {eta/60:.1f} min")
                print(f"Memory: {mem_status} ({used_pct:.1f}% used, {mem_free_pct:.1f}% free)")
                if worker_stats:
                    print(f"Workers: {' | '.join(worker_stats[:3])}")
                print(f"{'='*80}\n")
                
                # RAM kill-switch
                if used_pct > TT_MAX_RAM_PCT:
                    print(f"\n❌ MEMORY LIMIT EXCEEDED ({used_pct:.1f}% > {TT_MAX_RAM_PCT}%)")
                    print(f"Killing process to prevent system crash...")
                    f_received.close()
                    f_given.close()
                    os._exit(1)
    
    f_received.close()
    f_given.close()
    
    elapsed = time.time() - start_time
    print(f"\n{'='*80}")
    print(f"✅ COMPLETE")
    print(f"Total games processed: {games_processed}")
    print(f"Received opportunities: {received_count}")
    print(f"Given opportunities: {given_count}")
    print(f"Errors: {error_count}")
    print(f"Time: {elapsed/60:.1f} minutes")
    print(f"Output files:")
    print(f"  - {OUTPUT_RECEIVED}")
    print(f"  - {OUTPUT_GIVEN}")
    print(f"{'='*80}\n")


def main():
    print(f"\n{'='*80}")
    print(f"Comprehensive Pre-Analysis V1")
    print(f"Workers: {TT_WORKERS} | RAM limit: {TT_MAX_RAM_PCT}%")
    print(f"{'='*80}\n")
    
    # Load games
    print(f"Loading games from {GAMES_FILE}...")
    games = load_games(GAMES_FILE)
    print(f"Loaded {len(games)} games\n")
    
    # Get unique usernames
    usernames = list(set(g['username'] for g in games))
    print(f"Analyzing for users: {', '.join(usernames)}\n")
    
    # Prepare work items: (game_data, username) for each game-user pair
    work_items = []
    for game in games:
        work_items.append((game, game['username']))
    
    total_items = len(work_items)
    
    # Start writer process
    result_queue = mp.Queue()
    writer = mp.Process(
        target=writer_process,
        args=(result_queue, total_items, usernames)
    )
    writer.start()
    
    # Start worker pool
    with mp.Pool(processes=TT_WORKERS) as pool:
        worker_pids = [w.pid for w in pool._pool]
        
        # Process games
        for i, result in enumerate(pool.imap_unordered(analyze_single_game, work_items)):
            result_queue.put({
                'type': 'result',
                'data': result,
                'worker_pids': worker_pids
            })
    
    # Signal writer to finish
    result_queue.put(None)
    writer.join()


if __name__ == '__main__':
    # Check for caffeinate
    if sys.platform == 'darwin':
        print("Starting with caffeinate to prevent sleep...")
        subprocess.run(['caffeinate', '-i', sys.executable, __file__])
    else:
        main()


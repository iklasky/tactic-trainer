"""
Pre-analysis script V4: Fetch and analyze recent games with improved heuristic.
- Fetches 10 most recent games for each of: k2f4x, key_kay, jtkms
- Uses sustained material advantage (3 plies)
- Saves ALL opportunities (both converted and missed)
"""

import requests
import json
import csv
from chess_analyzer_v4 import ChessAnalyzerV4
import sys
import time
from datetime import datetime

USERNAMES = ['k2f4x', 'key_kay', 'jtkms']
GAMES_PER_USER = 10
OUTPUT_CSV = 'analysis_results_v4.csv'

def fetch_recent_games(username, num_games=10):
    """Fetch most recent games from chess.com API."""
    print(f"\n📥 Fetching games for {username}...", flush=True)
    
    # Get list of archives
    archives_url = f"https://api.chess.com/pub/player/{username}/games/archives"
    headers = {'User-Agent': 'TacticTrainer/1.0 (Contact: github.com/iklasky/tactic-trainer)'}
    
    response = requests.get(archives_url, headers=headers)
    if response.status_code != 200:
        print(f"❌ Failed to fetch archives for {username}: {response.status_code}", flush=True)
        return []
    
    archives = response.json().get('archives', [])
    if not archives:
        print(f"❌ No archives found for {username}", flush=True)
        return []
    
    # Fetch games from most recent archive(s)
    games = []
    for archive_url in reversed(archives):  # Start with most recent
        if len(games) >= num_games:
            break
        
        response = requests.get(archive_url, headers=headers)
        if response.status_code != 200:
            continue
        
        archive_games = response.json().get('games', [])
        games.extend(archive_games)
        time.sleep(0.5)  # Rate limiting
    
    # Take the most recent num_games
    games = games[-num_games:]
    
    print(f"✅ Fetched {len(games)} games for {username}", flush=True)
    return games

def main():
    print("=" * 80, flush=True)
    print("CHESS TACTIC TRAINER - PRE-ANALYSIS V4", flush=True)
    print("Improved heuristic: Material advantage sustained for 3 plies", flush=True)
    print("=" * 80, flush=True)
    
    analyzer = ChessAnalyzerV4()
    
    # Prepare CSV writer
    csv_file = open(OUTPUT_CSV, 'w', newline='', encoding='utf-8')
    fieldnames = [
        'username', 'game_url', 'game_index', 'event_index',
        'opportunity_cp', 'target_pawns', 't_turns_engine', 'converted_actual', 't_turns_actual',
        'opponent_move_ply_index', 'opponent_move_san', 'opponent_move_uci',
        'best_reply_san', 'best_reply_uci',
        'fen_before', 'fen_after', 'pv_moves', 'pv_evals', 'eval_before',
        'white_player', 'black_player', 'player_color',
        'time_control', 'game_result', 'end_time'
    ]
    writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
    writer.writeheader()
    csv_file.flush()
    
    total_games = 0
    total_opportunities = 0
    total_converted = 0
    total_missed = 0
    start_time = time.time()
    
    for username in USERNAMES:
        print(f"\n{'='*80}", flush=True)
        print(f"PROCESSING USER: {username}", flush=True)
        print(f"{'='*80}", flush=True)
        
        # Fetch games
        games = fetch_recent_games(username, GAMES_PER_USER)
        
        for game_idx, game_data in enumerate(games):
            total_games += 1
            
            # Extract PGN
            pgn = game_data.get('pgn', '')
            if not pgn:
                print(f"⚠️  Game {game_idx + 1}/{len(games)}: No PGN available", flush=True)
                continue
            
            # Get opponent name
            white_player = game_data.get('white', {}).get('username', 'Unknown')
            black_player = game_data.get('black', {}).get('username', 'Unknown')
            opponent = black_player if white_player.lower() == username.lower() else white_player
            
            print(f"\n🎮 Game {game_idx + 1}/{len(games)}: {username} vs {opponent}", flush=True)
            
            try:
                # Analyze game
                opportunities = analyzer.analyze_game(pgn, username)
                
                # Count converted vs missed
                game_converted = sum(1 for o in opportunities if o['converted_actual'] == 1)
                game_missed = len(opportunities) - game_converted
                
                total_opportunities += len(opportunities)
                total_converted += game_converted
                total_missed += game_missed
                
                print(f"  ✓ Found {len(opportunities)} opportunities ({game_converted} converted, {game_missed} missed)", flush=True)
                
                # Write to CSV
                for event_idx, opp in enumerate(opportunities):
                    row = {
                        'username': opp['username'],
                        'game_url': opp['game_url'],
                        'game_index': total_games - 1,
                        'event_index': event_idx,
                        'opportunity_cp': opp['opportunity_cp'],
                        'target_pawns': opp['target_pawns'],
                        't_turns_engine': opp['t_turns_engine'],
                        'converted_actual': opp['converted_actual'],
                        't_turns_actual': opp.get('t_turns_actual', ''),
                        'opponent_move_ply_index': opp['opponent_move_ply_index'],
                        'opponent_move_san': opp['opponent_move_san'],
                        'opponent_move_uci': opp['opponent_move_uci'],
                        'best_reply_san': opp['best_reply_san'],
                        'best_reply_uci': opp['best_reply_uci'],
                        'fen_before': opp['fen_before'],
                        'fen_after': opp['fen_after'],
                        'pv_moves': opp['pv_moves'],
                        'pv_evals': opp['pv_evals'],
                        'eval_before': opp['eval_before'],
                        'white_player': opp['white_player'],
                        'black_player': opp['black_player'],
                        'player_color': opp['player_color'],
                        'time_control': opp['time_control'],
                        'game_result': opp['game_result'],
                        'end_time': opp['end_time']
                    }
                    writer.writerow(row)
                
                csv_file.flush()
                
            except Exception as e:
                print(f"  ❌ Error analyzing game: {e}", flush=True)
                continue
            
            # Progress update
            elapsed = time.time() - start_time
            avg_time_per_game = elapsed / total_games
            remaining_games = (len(USERNAMES) * GAMES_PER_USER) - total_games
            est_remaining = remaining_games * avg_time_per_game
            
            print(f"\n📊 PROGRESS:", flush=True)
            print(f"  Games analyzed: {total_games}/{len(USERNAMES) * GAMES_PER_USER}", flush=True)
            print(f"  Total opportunities: {total_opportunities} ({total_converted} converted, {total_missed} missed)", flush=True)
            print(f"  Conversion rate: {(total_converted / total_opportunities * 100) if total_opportunities > 0 else 0:.1f}%", flush=True)
            print(f"  Time elapsed: {int(elapsed // 60)}m {int(elapsed % 60)}s", flush=True)
            print(f"  Est. remaining: {int(est_remaining // 60)}m {int(est_remaining % 60)}s", flush=True)
    
    csv_file.close()
    
    print(f"\n{'='*80}", flush=True)
    print(f"✅ ANALYSIS COMPLETE!", flush=True)
    print(f"{'='*80}", flush=True)
    print(f"Total games analyzed: {total_games}", flush=True)
    print(f"Total opportunities: {total_opportunities}", flush=True)
    print(f"  - Converted: {total_converted} ({(total_converted / total_opportunities * 100) if total_opportunities > 0 else 0:.1f}%)", flush=True)
    print(f"  - Missed: {total_missed} ({(total_missed / total_opportunities * 100) if total_opportunities > 0 else 0:.1f}%)", flush=True)
    print(f"Results saved to: {OUTPUT_CSV}", flush=True)
    print(f"Total time: {int((time.time() - start_time) // 60)}m {int((time.time() - start_time) % 60)}s", flush=True)

if __name__ == "__main__":
    main()


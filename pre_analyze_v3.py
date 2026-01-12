"""
Pre-analysis script V3: Analyze ALL opportunities (missed AND converted)
This enables percentage calculations for success rates.
Output: analysis_results_v3.csv
"""

import json
import csv
from datetime import datetime
from chess_analyzer_v3 import ChessAnalyzerV3
import sys

def analyze_all_opportunities(output_file='analysis_results_v3.csv'):
    """
    Analyze games from fetched_games.json for ALL opportunities (missed and converted).
    """
    
    print(f"\n{'='*80}", flush=True)
    print(f"🚀 ANALYZING ALL OPPORTUNITIES (MISSED + CONVERTED)", flush=True)
    print(f"{'='*80}\n", flush=True)
    
    # Load fetched games
    print("📂 Loading game data from fetched_games.json...", flush=True)
    with open('fetched_games.json', 'r') as f:
        data = json.load(f)
    
    total_games = sum(len(games) for games in data.values())
    print(f"✓ Found {total_games} total games from {len(data)} users", flush=True)
    for username, games in data.items():
        print(f"  - {username}: {len(games)} games", flush=True)
    
    # Create analyzer
    print("\n🔧 Initializing Stockfish analyzer V3...", flush=True)
    analyzer = ChessAnalyzerV3()
    print("✓ Analyzer ready\n", flush=True)
    
    # Prepare CSV file
    csv_columns = [
        'username', 'game_url', 'game_index', 'event_index',
        'opportunity_cp', 'target_pawns', 't_turns_engine',
        'converted_actual', 't_turns_actual',
        'opponent_move_ply_index', 'opponent_move_san', 'opponent_move_uci',
        'best_reply_san', 'best_reply_uci',
        'fen_before', 'fen_after', 'pv_moves', 'pv_evals', 'eval_before',
        'white_player', 'black_player', 'player_color',
        'time_control', 'game_result', 'end_time'
    ]
    
    # Initialize CSV with headers
    with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=csv_columns)
        writer.writeheader()
    
    print(f"📝 Created CSV file: {output_file}", flush=True)
    print(f"   This CSV includes BOTH missed and converted opportunities", flush=True)
    print(f"   converted_actual: 0 = missed, 1 = converted\n", flush=True)
    
    total_opportunities = 0
    total_converted = 0
    total_missed = 0
    games_with_opportunities = 0
    failed_games = []
    game_counter = 0
    
    start_time = datetime.now()
    
    # Analyze each user's games
    for username, games in data.items():
        print(f"\n{'='*80}", flush=True)
        print(f"👤 ANALYZING GAMES FOR: {username}", flush=True)
        print(f"{'='*80}", flush=True)
        
        for game_idx, game_data in enumerate(games):
            game_counter += 1
            pgn = game_data.get('pgn', '')
            game_url = game_data.get('url', '')
            time_control = game_data.get('time_class', '')
            end_time = game_data.get('end_time', 0)
            
            # Extract player names from PGN
            white_player = "Unknown"
            black_player = "Unknown"
            game_result = "Unknown"
            
            try:
                for line in pgn.split('\n'):
                    if line.startswith('[White "'):
                        white_player = line.split('"')[1]
                    elif line.startswith('[Black "'):
                        black_player = line.split('"')[1]
                    elif line.startswith('[Result "'):
                        game_result = line.split('"')[1]
            except:
                pass
            
            # Determine player color
            player_color = 'white' if username.lower() == white_player.lower() else 'black'
            
            print(f"\n{'─'*80}", flush=True)
            print(f"[{game_counter}/{total_games}] Analyzing game {game_idx + 1}/{len(games)} for {username}", flush=True)
            print(f"  Opponents: {white_player} (White) vs {black_player} (Black)", flush=True)
            print(f"  Analyzing: {username} ({player_color})", flush=True)
            print(f"  URL: {game_url}", flush=True)
            print(f"  Time: {datetime.now().strftime('%H:%M:%S')}", flush=True)
            
            try:
                # Analyze the game - gets ALL opportunities
                opportunities = analyzer.analyze_game(pgn, username)
                
                if opportunities:
                    games_with_opportunities += 1
                    game_converted = sum(1 for opp in opportunities if opp['converted_actual'] == 1)
                    game_missed = len(opportunities) - game_converted
                    
                    total_opportunities += len(opportunities)
                    total_converted += game_converted
                    total_missed += game_missed
                    
                    print(f"  ✓ Found {len(opportunities)} opportunities:", flush=True)
                    print(f"    - Converted: {game_converted}", flush=True)
                    print(f"    - Missed: {game_missed}", flush=True)
                    
                    # Write opportunities to CSV immediately
                    with open(output_file, 'a', newline='', encoding='utf-8') as csvfile:
                        writer = csv.DictWriter(csvfile, fieldnames=csv_columns)
                        
                        for event_idx, opp in enumerate(opportunities):
                            row = {
                                'username': username,
                                'game_url': game_url,
                                'game_index': game_idx,
                                'event_index': event_idx,
                                'opportunity_cp': opp['opportunity_cp'],
                                'target_pawns': opp['target_pawns'],
                                't_turns_engine': opp['t_turns_engine'],
                                'converted_actual': opp['converted_actual'],  # 0 or 1
                                't_turns_actual': opp.get('t_turns_actual', ''),
                                'opponent_move_ply_index': opp['opponent_move_ply_index'],
                                'opponent_move_san': opp['opponent_move_san'],
                                'opponent_move_uci': opp['opponent_move_uci'],
                                'best_reply_san': opp.get('best_reply_san', ''),
                                'best_reply_uci': opp.get('best_reply_uci', ''),
                                'fen_before': opp['fen_before'],
                                'fen_after': opp['fen_after'],
                                'pv_moves': '|'.join(opp.get('pv_moves', [])),
                                'pv_evals': '|'.join(str(e) for e in opp.get('pv_evals', [])),
                                'eval_before': opp.get('eval_before', ''),
                                'white_player': white_player,
                                'black_player': black_player,
                                'player_color': player_color,
                                'time_control': time_control,
                                'game_result': game_result,
                                'end_time': end_time
                            }
                            writer.writerow(row)
                    
                    print(f"  💾 Saved to CSV", flush=True)
                else:
                    print(f"  ○ No opportunities found", flush=True)
            
            except Exception as e:
                print(f"  ✗ Error: {str(e)}", flush=True)
                import traceback
                traceback.print_exc()
                failed_games.append({'game_idx': game_counter, 'url': game_url, 'error': str(e)})
            
            # Progress update
            elapsed = (datetime.now() - start_time).total_seconds()
            avg_per_game = elapsed / game_counter
            remaining = avg_per_game * (total_games - game_counter)
            
            if total_opportunities > 0:
                conversion_rate = (total_converted / total_opportunities) * 100
            else:
                conversion_rate = 0
            
            print(f"\n  📊 PROGRESS:", flush=True)
            print(f"     Games: {game_counter}/{total_games} ({(game_counter/total_games*100):.1f}%)", flush=True)
            print(f"     Total Opportunities: {total_opportunities}", flush=True)
            print(f"     - Converted: {total_converted} ({conversion_rate:.1f}%)", flush=True)
            print(f"     - Missed: {total_missed} ({100-conversion_rate:.1f}%)", flush=True)
            print(f"     Time: {elapsed/60:.1f} min elapsed, {remaining/60:.1f} min remaining", flush=True)
    
    # Summary
    elapsed_total = (datetime.now() - start_time).total_seconds()
    final_conversion_rate = (total_converted / total_opportunities * 100) if total_opportunities > 0 else 0
    
    print(f"\n{'='*80}", flush=True)
    print(f"📈 ANALYSIS COMPLETE", flush=True)
    print(f"{'='*80}", flush=True)
    print(f"Total games analyzed: {total_games}", flush=True)
    print(f"Games with opportunities: {games_with_opportunities}", flush=True)
    print(f"", flush=True)
    print(f"OPPORTUNITIES BREAKDOWN:", flush=True)
    print(f"  Total: {total_opportunities}", flush=True)
    print(f"  Converted (Success): {total_converted} ({final_conversion_rate:.1f}%)", flush=True)
    print(f"  Missed (Failed): {total_missed} ({100-final_conversion_rate:.1f}%)", flush=True)
    print(f"", flush=True)
    print(f"Failed games: {len(failed_games)}", flush=True)
    print(f"Total time: {elapsed_total/60:.1f} minutes", flush=True)
    print(f"\n✅ Results saved to: {output_file}", flush=True)
    print(f"{'='*80}\n", flush=True)

if __name__ == '__main__':
    analyze_all_opportunities()


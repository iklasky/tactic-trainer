"""
Pre-analysis script for MISSED OPPORTUNITIES: Analyze games and save results to CSV.
This finds opponent mistakes that you failed to convert.
"""

import json
import csv
from datetime import datetime
from chess_analyzer_opportunities import OpportunityAnalyzer
import sys
import os

def analyze_and_save_to_csv(num_games=100, output_file='opportunities_results.csv'):
    """
    Analyze the first N games and save all missed opportunity data to CSV.
    Writes incrementally after each game to prevent data loss.
    """
    
    print(f"\n{'='*80}", flush=True)
    print(f"🚀 STARTING MISSED OPPORTUNITY ANALYSIS - {num_games} GAMES", flush=True)
    print(f"{'='*80}\n", flush=True)
    
    # Load test games
    print("📂 Loading game data from test_games.json...", flush=True)
    with open('test_games.json', 'r') as f:
        data = json.load(f)
    
    username = data.get('username', 'Unknown')
    games = data.get('games', [])
    
    print(f"✓ Found {len(games)} total games", flush=True)
    print(f"✓ Analyzing player: {username}", flush=True)
    print(f"✓ Processing first {num_games} games", flush=True)
    print(f"✓ Looking for: Opponent mistakes you failed to convert\n", flush=True)
    
    # Sort by end_time descending (most recent first)
    games_sorted = sorted(
        games,
        key=lambda g: g.get('end_time', 0),
        reverse=True
    )
    
    games_to_analyze = games_sorted[:num_games]
    
    # Create analyzer
    print("🔧 Initializing Stockfish analyzer...", flush=True)
    analyzer = OpportunityAnalyzer()
    print("✓ Analyzer ready\n", flush=True)
    
    # Prepare CSV file with new schema
    csv_columns = [
        'username', 'game_url', 'game_index', 'event_index',
        'opportunity_cp', 't_turns_engine', 'opponent_move_ply_index', 'target_pawns',
        'opponent_move_san', 'opponent_move_uci',
        'best_reply_uci', 'best_reply_san',
        'fen_before', 'fen_after', 'pv_moves',
        'converted_actual', 't_turns_actual',
        'white_player', 'black_player', 'player_color',
        'time_control', 'game_result', 'end_time'
    ]
    
    # Initialize CSV with headers
    file_exists = os.path.exists(output_file)
    if not file_exists:
        with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=csv_columns)
            writer.writeheader()
        print(f"📝 Created new CSV file: {output_file}\n", flush=True)
    else:
        # Backup existing file
        backup_name = output_file.replace('.csv', f'_backup_{int(datetime.now().timestamp())}.csv')
        os.rename(output_file, backup_name)
        print(f"📝 Backed up existing CSV to: {backup_name}", flush=True)
        
        with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=csv_columns)
            writer.writeheader()
        print(f"📝 Created fresh CSV file: {output_file}\n", flush=True)
    
    total_opportunities = 0
    games_with_opportunities = 0
    failed_games = []
    
    start_time = datetime.now()
    
    # Analyze each game
    for game_idx, game in enumerate(games_to_analyze):
        game_url = game.get('url', '')
        white_player = game.get('white', {}).get('username', '')
        black_player = game.get('black', {}).get('username', '')
        time_control = game.get('time_control', '')
        end_time = game.get('end_time', 0)
        
        # Determine result
        white_result = game.get('white', {}).get('result', '')
        black_result = game.get('black', {}).get('result', '')
        game_result = f"{white_result} vs {black_result}"
        
        # Determine player color
        player_color = 'white' if username.lower() == white_player.lower() else 'black'
        
        print(f"\n{'─'*80}", flush=True)
        print(f"[{game_idx + 1}/{len(games_to_analyze)}] Analyzing game {game_idx + 1}", flush=True)
        print(f"  URL: {game_url}", flush=True)
        print(f"  Players: {white_player} (W) vs {black_player} (B)", flush=True)
        print(f"  Analyzing: {username} ({player_color})", flush=True)
        
        try:
            # Analyze the game for missed opportunities
            opportunities = analyzer.analyze_game(game.get('pgn', ''), username)
            
            if opportunities:
                games_with_opportunities += 1
                total_opportunities += len(opportunities)
                
                print(f"  ✓ Found {len(opportunities)} missed opportunities", flush=True)
                
                # Write opportunities to CSV immediately (incremental)
                with open(output_file, 'a', newline='', encoding='utf-8') as csvfile:
                    writer = csv.DictWriter(csvfile, fieldnames=csv_columns)
                    
                    for event_idx, opp in enumerate(opportunities):
                        row = {
                            'username': username,
                            'game_url': game_url,
                            'game_index': game_idx,
                            'event_index': event_idx,
                            'opportunity_cp': opp['opportunity_cp'],
                            't_turns_engine': opp['t_turns_engine'],
                            'opponent_move_ply_index': opp['opponent_move_ply_index'],
                            'target_pawns': opp['target_pawns'],
                            'opponent_move_san': opp['opponent_move_san'],
                            'opponent_move_uci': opp['opponent_move_uci'],
                            'best_reply_uci': opp.get('best_reply_uci', ''),
                            'best_reply_san': opp.get('best_reply_san', ''),
                            'fen_before': opp['fen_before'],
                            'fen_after': opp['fen_after'],
                            'pv_moves': '|'.join(opp.get('pv_moves', [])),
                            'converted_actual': opp['converted_actual'],
                            't_turns_actual': opp.get('t_turns_actual') or '',
                            'white_player': white_player,
                            'black_player': black_player,
                            'player_color': player_color,
                            'time_control': time_control,
                            'game_result': game_result,
                            'end_time': end_time
                        }
                        writer.writerow(row)
                
                print(f"  💾 Saved {len(opportunities)} opportunities to CSV", flush=True)
            else:
                print(f"  ○ No missed opportunities (perfect conversion!)", flush=True)
        
        except Exception as e:
            print(f"  ✗ Error: {str(e)}", flush=True)
            import traceback
            traceback.print_exc()
            failed_games.append({'game_idx': game_idx, 'url': game_url, 'error': str(e)})
        
        # Progress update
        elapsed = (datetime.now() - start_time).total_seconds()
        avg_per_game = elapsed / (game_idx + 1)
        remaining = avg_per_game * (len(games_to_analyze) - game_idx - 1)
        
        print(f"\n  📊 PROGRESS:", flush=True)
        print(f"     Completed: {game_idx + 1}/{len(games_to_analyze)} ({((game_idx + 1)/len(games_to_analyze)*100):.1f}%)", flush=True)
        print(f"     Missed opportunities so far: {total_opportunities}", flush=True)
        print(f"     Avg time: {avg_per_game:.1f}s/game", flush=True)
        print(f"     Elapsed: {elapsed/60:.1f} min | Remaining: {remaining/60:.1f} min", flush=True)
    
    # Summary
    elapsed_total = (datetime.now() - start_time).total_seconds()
    
    print(f"\n{'='*80}", flush=True)
    print(f"📈 ANALYSIS COMPLETE", flush=True)
    print(f"{'='*80}", flush=True)
    print(f"Total games analyzed: {len(games_to_analyze)}", flush=True)
    print(f"Games with missed opportunities: {games_with_opportunities}", flush=True)
    print(f"Total missed opportunities found: {total_opportunities}", flush=True)
    print(f"Average per game: {total_opportunities/len(games_to_analyze):.2f}", flush=True)
    print(f"Failed games: {len(failed_games)}", flush=True)
    print(f"Total time: {elapsed_total/60:.1f} minutes", flush=True)
    print(f"Average: {elapsed_total/len(games_to_analyze):.1f} seconds per game", flush=True)
    
    if failed_games:
        print(f"\n⚠️  Failed games:", flush=True)
        for failed in failed_games[:10]:  # Show first 10
            print(f"  Game {failed['game_idx']}: {failed['url']}", flush=True)
        if len(failed_games) > 10:
            print(f"  ... and {len(failed_games) - 10} more", flush=True)
    
    print(f"\n✅ Results saved to: {output_file}", flush=True)
    print(f"{'='*80}\n", flush=True)

if __name__ == '__main__':
    num_games = 100
    if len(sys.argv) > 1:
        try:
            num_games = int(sys.argv[1])
        except:
            print("Usage: python pre_analyze_opportunities.py [num_games]")
            sys.exit(1)
    
    analyze_and_save_to_csv(num_games=num_games)

"""
Chess Analyzer V4: Improved material conversion heuristic.
Now requires material advantage to be SUSTAINED for 3 consecutive plies.
"""

import chess
import chess.pgn
from stockfish import Stockfish
from typing import List, Dict, Optional, Tuple
import io
import config


class ChessAnalyzerV4:
    def __init__(self):
        pass
    
    def _init_engine(self):
        """Initialize Stockfish engine."""
        engine = Stockfish(
            path=config.STOCKFISH_PATH,
            depth=config.STOCKFISH_DEPTH,
            parameters={"Threads": 2, "Minimum Thinking Time": 10}
        )
        return engine
    
    def parse_pgn(self, pgn_string: str) -> Tuple[chess.pgn.Game, List[chess.Board]]:
        """Parse PGN and return game + list of board positions."""
        pgn = io.StringIO(pgn_string)
        game = chess.pgn.read_game(pgn)
        
        if game is None:
            return None, []
        
        positions = []
        board = game.board()
        positions.append(board.copy())
        
        for move in game.mainline_moves():
            board.push(move)
            positions.append(board.copy())
        
        return game, positions
    
    def get_material_value(self, board: chess.Board) -> int:
        """Calculate total material value on the board."""
        total = 0
        for piece_type, value in config.MATERIAL_VALUES.items():
            total += len(board.pieces(getattr(chess, piece_type), chess.WHITE)) * value
            total -= len(board.pieces(getattr(chess, piece_type), chess.BLACK)) * value
        return total
    
    def get_stockfish_eval(self, engine: Stockfish, board: chess.Board) -> Optional[float]:
        """Get Stockfish evaluation for a position."""
        if board.is_game_over():
            return None
        
        engine.set_fen_position(board.fen())
        eval_dict = engine.get_evaluation()
        
        if eval_dict['type'] == 'cp':
            return eval_dict['value'] / 100.0
        elif eval_dict['type'] == 'mate':
            mate_in = eval_dict['value']
            return 100.0 if mate_in > 0 else -100.0
        
        return None
    
    def compute_opportunity_gain(self, engine: Stockfish,
                                  board_before: chess.Board,
                                  board_after: chess.Board,
                                  player_color: chess.Color) -> Optional[int]:
        """
        Compute the eval increase for the player after opponent's move.
        """
        eval_before = self.get_stockfish_eval(engine, board_before)
        eval_after = self.get_stockfish_eval(engine, board_after)
        
        if eval_before is None or eval_after is None:
            return None
        
        # Convert to player's perspective
        if player_color == chess.BLACK:
            eval_before *= -1
            eval_after *= -1
        
        # Opportunity gain = how much better it got for player
        opportunity_cp = int((eval_after - eval_before) * 100)
        
        return opportunity_cp
    
    def compute_engine_conversion_time(self, engine: Stockfish,
                                       board_after: chess.Board,
                                       opportunity_cp: int,
                                       player_color: chess.Color) -> Optional[Tuple[int, List[str], List[int], int]]:
        """
        Compute how many plies engine needs to convert opportunity to material.
        NEW: Requires material advantage to be SUSTAINED for 3 consecutive plies.
        Returns: (plies_to_convert, pv_moves, pv_evals, eval_before) or None
        """
        material_before = self.get_material_value(board_after)
        eval_before_cp = self.get_stockfish_eval(engine, board_after)
        if eval_before_cp is None:
            return None
        eval_before_cp = int(eval_before_cp * 100)
        
        target_pawns = opportunity_cp // 100
        
        if player_color == chess.BLACK:
            target_material = material_before - target_pawns
        else:
            target_material = material_before + target_pawns
        
        temp_board = board_after.copy()
        pv_moves = []
        pv_evals = []
        
        # Track sustained advantage
        sustained_count = 0  # How many consecutive plies we've held the advantage
        first_crossing_ply = None  # When we first crossed the threshold
        
        for ply in range(1, config.MAX_HORIZON_PLIES + 1):
            if temp_board.is_game_over():
                return None
            
            engine.set_fen_position(temp_board.fen())
            best_move_uci = engine.get_best_move()
            
            if not best_move_uci:
                return None
            
            temp_board.push(chess.Move.from_uci(best_move_uci))
            pv_moves.append(best_move_uci)
            
            # Get eval for this position
            eval_cp = self.get_stockfish_eval(engine, temp_board)
            if eval_cp is not None:
                pv_evals.append(int(eval_cp * 100))
            else:
                pv_evals.append(0)
            
            current_material = self.get_material_value(temp_board)
            
            # Check if we've crossed the threshold
            threshold_crossed = False
            if player_color == chess.BLACK:
                threshold_crossed = current_material <= target_material
            else:
                threshold_crossed = current_material >= target_material
            
            if threshold_crossed:
                if first_crossing_ply is None:
                    first_crossing_ply = ply
                sustained_count += 1
                
                # If sustained for 3 plies, we've successfully converted
                if sustained_count >= 3:
                    return (ply, pv_moves, pv_evals, eval_before_cp)
            else:
                # Dropped below threshold, reset
                sustained_count = 0
                first_crossing_ply = None
        
        return None
    
    def check_actual_conversion(self, board_after: chess.Board,
                                remaining_moves: List[chess.Move],
                                target_pawns: int,
                                player_color: chess.Color,
                                mistake_ply: int) -> Tuple[bool, Optional[int]]:
        """
        Check if player actually converted the opportunity in the game.
        NEW: Also requires sustained advantage for 3 plies.
        """
        material_before = self.get_material_value(board_after)
        
        if player_color == chess.BLACK:
            target_material = material_before - target_pawns
        else:
            target_material = material_before + target_pawns
        
        temp_board = board_after.copy()
        sustained_count = 0
        first_crossing_ply = None
        
        for ply_idx, move in enumerate(remaining_moves, start=1):
            temp_board.push(move)
            current_material = self.get_material_value(temp_board)
            
            threshold_crossed = False
            if player_color == chess.BLACK:
                threshold_crossed = current_material <= target_material
            else:
                threshold_crossed = current_material >= target_material
            
            if threshold_crossed:
                if first_crossing_ply is None:
                    first_crossing_ply = ply_idx
                sustained_count += 1
                
                if sustained_count >= 3:
                    return True, ply_idx
            else:
                sustained_count = 0
                first_crossing_ply = None
        
        return False, None
    
    def analyze_game(self, pgn_string: str, player_username: str) -> List[Dict]:
        """
        Analyze a single game for ALL opportunities (missed and converted).
        Returns list of opportunity events with 'converted_actual' flag.
        """
        engine = self._init_engine()
        
        try:
            game, positions = self.parse_pgn(pgn_string)
            
            # Determine player color
            white_name = game.headers.get("White", "").lower()
            black_name = game.headers.get("Black", "").lower()
            player_username_lower = player_username.lower()
            
            if player_username_lower == white_name:
                player_color = chess.WHITE
                opponent_color = chess.BLACK
            elif player_username_lower == black_name:
                player_color = chess.BLACK
                opponent_color = chess.WHITE
            else:
                return []
            
            moves = list(game.mainline_moves())
            opportunities = []
            
            # Iterate through opponent moves
            for i in range(len(positions) - 1):
                board_before = positions[i]
                
                # Check if it's opponent's turn
                if board_before.turn != opponent_color:
                    continue
                
                move = moves[i]
                board_after = positions[i + 1]
                
                # Compute opportunity gain (eval increase for player)
                opportunity_cp = self.compute_opportunity_gain(
                    engine, board_before, board_after, player_color
                )
                
                if opportunity_cp is None or opportunity_cp < config.DELTA_CUTOFF_CP:
                    continue
                
                # Compute engine conversion time (with sustained advantage)
                result = self.compute_engine_conversion_time(
                    engine, board_after, opportunity_cp, player_color
                )
                
                if result is None:
                    # Engine can't convert within horizon, skip
                    continue
                
                t_engine, pv_moves, pv_evals, eval_before_cp = result
                
                # Check if player actually converted in the real game
                remaining_moves = moves[i + 1:]  # Moves after opponent's mistake
                target_pawns = opportunity_cp // 100
                
                converted, t_actual = self.check_actual_conversion(
                    board_after, remaining_moves, target_pawns, player_color, i
                )
                
                # Get best reply from PV
                best_reply_uci = pv_moves[0] if pv_moves else ""
                best_reply_san = ""
                if best_reply_uci:
                    try:
                        temp_board = board_after.copy()
                        best_reply_move = chess.Move.from_uci(best_reply_uci)
                        best_reply_san = temp_board.san(best_reply_move)
                    except:
                        best_reply_san = best_reply_uci
                
                # Store ALL opportunities (both converted and missed)
                opportunities.append({
                    'username': player_username,
                    'game_url': game.headers.get('Site', ''),
                    'opponent_move_ply_index': i,
                    'opponent_move_san': board_before.san(move),
                    'opponent_move_uci': move.uci(),
                    'opportunity_cp': opportunity_cp,
                    'target_pawns': target_pawns,
                    't_turns_engine': t_engine,
                    'converted_actual': 1 if converted else 0,
                    't_turns_actual': t_actual if t_actual is not None else None,
                    'best_reply_uci': best_reply_uci,
                    'best_reply_san': best_reply_san,
                    'fen_before': board_before.fen(),
                    'fen_after': board_after.fen(),
                    'pv_moves': '|'.join(pv_moves),
                    'pv_evals': '|'.join(map(str, pv_evals)),
                    'eval_before': eval_before_cp,
                    'white_player': game.headers.get('White', ''),
                    'black_player': game.headers.get('Black', ''),
                    'player_color': 'white' if player_color == chess.WHITE else 'black',
                    'time_control': game.headers.get('TimeControl', ''),
                    'game_result': game.headers.get('Result', ''),
                    'end_time': game.headers.get('UTCDate', '') + ' ' + game.headers.get('UTCTime', '')
                })
            
            return opportunities
        
        finally:
            del engine


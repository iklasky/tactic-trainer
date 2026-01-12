"""
Chess Analyzer V3 - Tracks ALL opportunities (both missed and converted)
This version saves both successfully converted and missed opportunities
to enable percentage calculations.
"""

import chess
import chess.pgn
from stockfish import Stockfish
from typing import List, Dict, Optional, Tuple
import io
import config


class ChessAnalyzerV3:
    """
    Analyzes chess games to find ALL scoring opportunities (missed and converted).
    """
    
    def __init__(self):
        self.stockfish_path = config.STOCKFISH_PATH
    
    def _init_engine(self):
        """Initialize Stockfish engine."""
        engine = Stockfish(
            path=self.stockfish_path,
            depth=config.STOCKFISH_DEPTH,
            parameters={"Threads": 2, "Hash": 2048}
        )
        return engine
    
    def parse_pgn(self, pgn_string: str) -> Tuple[chess.pgn.Game, List[chess.Board]]:
        """Parse PGN and return game object and list of board positions."""
        pgn_io = io.StringIO(pgn_string)
        game = chess.pgn.read_game(pgn_io)
        
        if game is None:
            raise ValueError("Invalid PGN")
        
        # Generate all positions
        board = game.board()
        positions = [board.copy()]
        
        for move in game.mainline_moves():
            board.push(move)
            positions.append(board.copy())
        
        return game, positions
    
    def get_material_value(self, board: chess.Board) -> int:
        """Calculate total material value on board."""
        material = 0
        for square in chess.SQUARES:
            piece = board.piece_at(square)
            if piece:
                piece_name = chess.piece_name(piece.piece_type).upper()
                value = config.MATERIAL_VALUES.get(piece_name, 0)
                if piece.color == chess.WHITE:
                    material += value
                else:
                    material -= value
        return material
    
    def get_eval(self, engine: Stockfish, board: chess.Board) -> Optional[float]:
        """Get Stockfish evaluation in centipawns (White's POV)."""
        try:
            engine.set_fen_position(board.fen())
            eval_data = engine.get_evaluation()
            
            if eval_data['type'] == 'cp':
                return eval_data['value'] / 100.0
            elif eval_data['type'] == 'mate':
                mate_in = eval_data['value']
                return 100.0 if mate_in > 0 else -100.0
            
            return None
        except:
            return None
    
    def compute_opportunity_gain(self, engine: Stockfish, 
                                 board_before: chess.Board,
                                 board_after: chess.Board,
                                 player_color: chess.Color) -> Optional[int]:
        """
        Calculate eval gain for player after opponent's move.
        Returns centipawns from player's perspective.
        """
        eval_before = self.get_eval(engine, board_before)
        eval_after = self.get_eval(engine, board_after)
        
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
                                       player_color: chess.Color) -> Optional[int]:
        """
        Compute how many plies engine needs to convert opportunity to material.
        """
        material_before = self.get_material_value(board_after)
        target_pawns = opportunity_cp // 100
        
        if player_color == chess.BLACK:
            target_material = material_before - target_pawns
        else:
            target_material = material_before + target_pawns
        
        temp_board = board_after.copy()
        
        for ply in range(1, config.MAX_HORIZON_PLIES + 1):
            if temp_board.is_game_over():
                return None
            
            engine.set_fen_position(temp_board.fen())
            best_move_uci = engine.get_best_move()
            
            if not best_move_uci:
                return None
            
            temp_board.push(chess.Move.from_uci(best_move_uci))
            current_material = self.get_material_value(temp_board)
            
            if player_color == chess.BLACK:
                if current_material <= target_material:
                    return ply
            else:
                if current_material >= target_material:
                    return ply
        
        return None
    
    def check_actual_conversion(self, board_after: chess.Board,
                                remaining_moves: List[chess.Move],
                                target_pawns: int,
                                player_color: chess.Color,
                                mistake_ply: int) -> Tuple[bool, Optional[int]]:
        """
        Check if player actually converted the opportunity in the game.
        Returns (converted, plies_to_convert)
        """
        material_before = self.get_material_value(board_after)
        
        if player_color == chess.BLACK:
            target_material = material_before - target_pawns
        else:
            target_material = material_before + target_pawns
        
        temp_board = board_after.copy()
        
        for ply_idx, move in enumerate(remaining_moves, start=1):
            temp_board.push(move)
            current_material = self.get_material_value(temp_board)
            
            if player_color == chess.BLACK:
                if current_material <= target_material:
                    return True, ply_idx
            else:
                if current_material >= target_material:
                    return True, ply_idx
        
        return False, None
    
    def analyze_game(self, pgn_string: str, player_username: str) -> List[Dict]:
        """
        Analyze a single game for ALL scoring opportunities (missed AND converted).
        Returns list of ALL opportunity events.
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
                
                # Compute opportunity gain
                opportunity_cp = self.compute_opportunity_gain(
                    engine, board_before, board_after, player_color
                )
                
                if opportunity_cp is None or opportunity_cp < config.DELTA_CUTOFF_CP:
                    continue
                
                # Compute engine conversion time
                t_engine = self.compute_engine_conversion_time(
                    engine, board_after, opportunity_cp, player_color
                )
                
                if t_engine is None:
                    continue
                
                # Check if player actually converted
                remaining_moves = moves[i + 1:]
                target_pawns = opportunity_cp // 100
                
                converted, t_actual = self.check_actual_conversion(
                    board_after, remaining_moves, target_pawns, player_color, i
                )
                
                # KEY DIFFERENCE: We save ALL opportunities, not just missed ones
                
                # Get best reply
                engine.set_fen_position(board_after.fen())
                best_reply_uci = engine.get_best_move()
                best_reply_san = board_after.san(chess.Move.from_uci(best_reply_uci)) if best_reply_uci else None
                
                # Get PV and evals
                pv_moves = []
                pv_evals = []
                try:
                    eval_start = self.get_eval(engine, board_before)
                    eval_after_mistake = self.get_eval(engine, board_after)
                    
                    temp_board = board_after.copy()
                    pv_evals.append(eval_after_mistake)
                    
                    for _ in range(min(20, config.MAX_HORIZON_PLIES)):
                        if temp_board.is_game_over():
                            break
                        engine.set_fen_position(temp_board.fen())
                        next_move_uci = engine.get_best_move()
                        if next_move_uci:
                            pv_moves.append(next_move_uci)
                            temp_board.push(chess.Move.from_uci(next_move_uci))
                            eval_after_move = self.get_eval(engine, temp_board)
                            if eval_after_move is not None:
                                pv_evals.append(eval_after_move)
                        else:
                            break
                except:
                    pass
                
                opportunities.append({
                    'opportunity_cp': opportunity_cp,
                    't_turns_engine': t_engine,
                    'opponent_move_ply_index': i,
                    'opponent_move_san': board_before.san(move),
                    'opponent_move_uci': move.uci(),
                    'best_reply_uci': best_reply_uci,
                    'best_reply_san': best_reply_san,
                    'fen_before': board_before.fen(),
                    'fen_after': board_after.fen(),
                    'pv_moves': pv_moves,
                    'pv_evals': pv_evals,
                    'eval_before': eval_start,
                    'converted_actual': 1 if converted else 0,  # 1 = converted, 0 = missed
                    't_turns_actual': t_actual if converted else None,
                    'target_pawns': target_pawns
                })
            
            return opportunities
            
        finally:
            del engine


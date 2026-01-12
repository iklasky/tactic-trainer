"""
Chess analysis engine for finding MISSED scoring opportunities.
Detects when opponent makes a mistake (your eval increases) and you fail to convert it.
"""

import chess
import chess.pgn
from stockfish import Stockfish
from typing import Dict, List, Tuple, Optional
import io
import config


class OpportunityAnalyzer:
    """Analyzes chess games to find missed scoring opportunities."""
    
    def __init__(self, stockfish_path: str = None):
        """Initialize the analyzer with Stockfish."""
        self.stockfish_path = stockfish_path or config.STOCKFISH_PATH
        self.eval_cache: Dict[str, int] = {}  # FEN -> centipawn eval
        
    def _init_engine(self) -> Stockfish:
        """Create a new Stockfish instance."""
        engine = Stockfish(
            path=self.stockfish_path,
            depth=config.STOCKFISH_DEPTH,
            parameters={"Threads": config.STOCKFISH_THREADS}
        )
        return engine
    
    def parse_pgn(self, pgn_string: str) -> Tuple[chess.pgn.Game, List[chess.Board]]:
        """Parse PGN and return game object plus list of board positions."""
        pgn_io = io.StringIO(pgn_string)
        game = chess.pgn.read_game(pgn_io)
        
        if game is None:
            raise ValueError("Failed to parse PGN")
        
        # Generate all positions
        board = game.board()
        positions = [board.copy()]
        
        for move in game.mainline_moves():
            board.push(move)
            positions.append(board.copy())
        
        return game, positions
    
    def compute_material_score(self, board: chess.Board, player_color: chess.Color) -> int:
        """
        Compute net material score from player's perspective.
        Returns material in pawn units (P=1, N=3, B=3, R=5, Q=9).
        """
        material = 0
        
        for piece_type in [chess.PAWN, chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN]:
            # Count player pieces
            player_pieces = len(board.pieces(piece_type, player_color))
            # Count opponent pieces
            opponent_pieces = len(board.pieces(piece_type, not player_color))
            
            piece_value = config.MATERIAL_VALUES[chess.piece_name(piece_type).upper()]
            material += (player_pieces - opponent_pieces) * piece_value
        
        return material
    
    def get_eval(self, engine: Stockfish, board: chess.Board) -> Optional[int]:
        """
        Get centipawn evaluation from White's POV.
        Returns None for mate positions if SKIP_MATE_POSITIONS is True.
        """
        fen = board.fen()
        
        # Check cache
        if config.ENABLE_CACHE and fen in self.eval_cache:
            return self.eval_cache[fen]
        
        # Set position
        engine.set_fen_position(fen)
        
        # Get evaluation
        eval_info = engine.get_evaluation()
        
        # Handle mate scores
        if eval_info['type'] == 'mate':
            if config.SKIP_MATE_POSITIONS:
                return None
            # Convert mate to large centipawn value
            mate_in = eval_info['value']
            cp_value = 100000 - abs(mate_in) * 100
            return cp_value if mate_in > 0 else -cp_value
        
        cp_value = eval_info['value']
        
        # Cache
        if config.ENABLE_CACHE:
            if len(self.eval_cache) < config.CACHE_SIZE_LIMIT:
                self.eval_cache[fen] = cp_value
        
        return cp_value
    
    def detect_opponent_mistake(self, engine: Stockfish, board_before: chess.Board,
                               opponent_move: chess.Move, player_color: chess.Color) -> Optional[int]:
        """
        Detect if opponent's move created a scoring opportunity.
        Returns opportunity size in centipawns (from player POV), or None if not significant.
        """
        # Get eval before opponent move
        eval_before_white_pov = self.get_eval(engine, board_before)
        if eval_before_white_pov is None:
            return None
        
        # Get eval after opponent move
        board_after = board_before.copy()
        board_after.push(opponent_move)
        eval_after_white_pov = self.get_eval(engine, board_after)
        if eval_after_white_pov is None:
            return None
        
        # Convert to player POV
        if player_color == chess.WHITE:
            eval_before = eval_before_white_pov
            eval_after = eval_after_white_pov
        else:  # Black
            eval_before = -eval_before_white_pov
            eval_after = -eval_after_white_pov
        
        # Opportunity is when your eval increases
        opportunity = max(0, eval_after - eval_before)
        
        return opportunity if opportunity >= config.DELTA_CUTOFF_CP else None
    
    def compute_engine_conversion_time(self, engine: Stockfish, board_after_mistake: chess.Board,
                                       opportunity_cp: int, player_color: chess.Color) -> Optional[int]:
        """
        Compute how many turns it takes for engine to convert opportunity to material.
        Baseline is material at board_after_mistake.
        
        Returns:
            Number of plies until material converted, or None if unrealized
        """
        # Material baseline (after opponent mistake)
        material_baseline = self.compute_material_score(board_after_mistake, player_color)
        
        # Target material gain
        target_material_gain = opportunity_cp // 100
        
        if target_material_gain < 1:
            return None
        
        # Walk the PV (best play continuation)
        current_board = board_after_mistake.copy()
        
        for ply in range(1, config.MAX_HORIZON_PLIES + 1):
            if current_board.is_game_over():
                break
            
            # Get best move from this position
            engine.set_fen_position(current_board.fen())
            best_move_uci = engine.get_best_move()
            
            if best_move_uci is None:
                break
            
            # Apply best move
            try:
                best_move = chess.Move.from_uci(best_move_uci)
                current_board.push(best_move)
            except:
                break
            
            # Check material at this ply
            material_k = self.compute_material_score(current_board, player_color)
            
            if (material_k - material_baseline) >= target_material_gain:
                return ply
        
        # Unrealized within horizon
        return None
    
    def check_actual_conversion(self, board_after_mistake: chess.Board, 
                               remaining_moves: List[chess.Move],
                               target_material_gain: int,
                               player_color: chess.Color) -> Tuple[bool, Optional[int]]:
        """
        Check if player actually converted the opportunity in the real game.
        
        Args:
            board_after_mistake: Position after opponent's mistake
            remaining_moves: Actual moves played after the mistake
            target_material_gain: How much material needed (in pawns)
            player_color: Player's color
        
        Returns:
            (converted, t_actual) where:
            - converted: True if player achieved material gain
            - t_actual: Ply where gain achieved, or None
        """
        material_baseline = self.compute_material_score(board_after_mistake, player_color)
        
        current_board = board_after_mistake.copy()
        horizon = min(len(remaining_moves), config.MAX_HORIZON_PLIES)
        
        for ply in range(horizon):
            if current_board.is_game_over():
                break
            
            try:
                current_board.push(remaining_moves[ply])
            except:
                break
            
            material_k = self.compute_material_score(current_board, player_color)
            
            if (material_k - material_baseline) >= target_material_gain:
                return True, ply + 1
        
        return False, None
    
    def analyze_game(self, pgn_string: str, player_username: str) -> List[Dict]:
        """
        Analyze a single game for missed opportunities.
        Returns list of opportunity events where player failed to convert.
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
                # Player not in this game
                return []
            
            # Get all moves
            moves = list(game.mainline_moves())
            
            # Analyze each opponent move
            missed_opportunities = []
            
            for i, move in enumerate(moves):
                # Check if this is opponent's move
                board_before = positions[i]
                if board_before.turn != opponent_color:
                    continue
                
                # Check if opponent made a mistake (created opportunity)
                opportunity_cp = self.detect_opponent_mistake(
                    engine, board_before, move, player_color
                )
                
                if opportunity_cp is None:
                    continue
                
                # Position after opponent's mistake
                board_after = positions[i + 1]
                
                # Compute engine conversion time
                t_engine = self.compute_engine_conversion_time(
                    engine, board_after, opportunity_cp, player_color
                )
                
                if t_engine is None:
                    # Engine can't convert within horizon - skip
                    continue
                
                # Check if player actually converted in the real game
                remaining_moves = moves[i + 1:]  # Moves after opponent mistake
                target_pawns = opportunity_cp // 100
                
                converted, t_actual = self.check_actual_conversion(
                    board_after, remaining_moves, target_pawns, player_color
                )
                
                # Only keep if player FAILED to convert
                if not converted:
                    # Get best reply move
                    engine.set_fen_position(board_after.fen())
                    best_reply_uci = engine.get_best_move()
                    best_reply_san = None
                    if best_reply_uci:
                        try:
                            best_reply_san = board_after.san(chess.Move.from_uci(best_reply_uci))
                        except:
                            pass
                    
                    # Get PV moves for visualization
                    pv_moves = []
                    try:
                        # Get multiple best moves to extract PV
                        temp_board = board_after.copy()
                        for _ in range(min(10, config.MAX_HORIZON_PLIES)):
                            if temp_board.is_game_over():
                                break
                            engine.set_fen_position(temp_board.fen())
                            best_move_uci = engine.get_best_move()
                            if best_move_uci:
                                pv_moves.append(best_move_uci)
                                try:
                                    temp_board.push(chess.Move.from_uci(best_move_uci))
                                except:
                                    break
                            else:
                                break
                    except:
                        pass
                    
                    missed_opportunities.append({
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
                        'converted_actual': False,
                        't_turns_actual': t_actual,
                        'target_pawns': target_pawns
                    })
            
            return missed_opportunities
            
        finally:
            # Cleanup
            del engine
    
    def analyze_multiple_games(self, games_data: List[Dict], 
                               player_username: str) -> List[Dict]:
        """
        Analyze multiple games for missed opportunities.
        Each game_data should have 'pgn' and 'url' fields.
        Returns aggregated list of all missed opportunity events.
        """
        all_opportunities = []
        
        for game_data in games_data:
            pgn = game_data.get('pgn', '')
            url = game_data.get('url', '')
            
            if not pgn:
                continue
            
            try:
                opportunities = self.analyze_game(pgn, player_username)
                
                # Add game context to each opportunity
                for opp in opportunities:
                    opp['game_url'] = url
                
                all_opportunities.extend(opportunities)
                
            except Exception as e:
                print(f"Error analyzing game {url}: {e}")
                continue
        
        return all_opportunities

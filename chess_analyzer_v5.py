"""
Chess Analyzer V5

Adds support for "mate opportunities" (opponent blunder gives a forced mate).

Key points:
- Opportunity kinds:
  - "cp": standard centipawn-based opportunities (>= DELTA_CUTOFF_CP)
  - "mate": forced mate detected for the player after opponent's move
- For "mate" opportunities:
  - opportunity is labeled as "M" (via opportunity_kind='mate')
  - t_plies is plies-to-checkmate along best play (within MAX_HORIZON_PLIES)
  - no 3-ply hold rule (mate is terminal)
- For "cp" opportunities:
  - uses "sustain for 3 plies" rule for material conversion
  - IMPORTANT: we REPORT t_plies as the FIRST ply of the 3-ply hold window
    (i.e. we do not count the last 2 confirmation plies in UI time)
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import chess
import chess.pgn
from stockfish import Stockfish

import config


@dataclass
class EngineEval:
    kind: str  # "cp" or "mate"
    value: int  # centipawns if cp, mate-in plies if mate (positive means side-to-move mates)


class ChessAnalyzerV5:
    def __init__(self):
        pass

    def _init_engine(self) -> Stockfish:
        engine = Stockfish(
            path=config.STOCKFISH_PATH,
            depth=config.STOCKFISH_DEPTH,
            parameters={
                # Safety: each worker should use 1 thread so we don't oversubscribe CPU
                "Threads": 1,
                "Minimum Thinking Time": 10,
            },
        )
        return engine

    def parse_pgn(self, pgn_string: str) -> Tuple[Optional[chess.pgn.Game], List[chess.Board]]:
        pgn = io.StringIO(pgn_string)
        game = chess.pgn.read_game(pgn)
        if game is None:
            return None, []

        positions: List[chess.Board] = []
        board = game.board()
        positions.append(board.copy())
        for mv in game.mainline_moves():
            board.push(mv)
            positions.append(board.copy())
        return game, positions

    def _get_engine_eval(self, engine: Stockfish, board: chess.Board) -> Optional[EngineEval]:
        if board.is_game_over():
            return None
        engine.set_fen_position(board.fen())
        e = engine.get_evaluation()
        if not e or "type" not in e:
            return None
        if e["type"] == "cp":
            return EngineEval(kind="cp", value=int(e["value"]))
        if e["type"] == "mate":
            # In UCI, mate score sign is from side-to-move perspective.
            return EngineEval(kind="mate", value=int(e["value"]))
        return None

    def compute_opportunity_kind(
        self,
        engine: Stockfish,
        board_before: chess.Board,
        board_after: chess.Board,
        player_color: chess.Color,
    ) -> Optional[Dict]:
        """
        Decide if this opponent move created an opportunity, and return a dict describing it.

        Returns:
          - None if no opportunity (below thresholds / not convertible / etc)
          - dict with keys:
              opportunity_kind: "cp" | "mate"
              opportunity_cp: int (only for cp)
              mate_in: int (only for mate; positive means side-to-move mates)
              eval_before_cp: int (centipawns, for UI)
        """
        # Eval before opponent move (from player's POV)
        eval_before = self._get_engine_eval(engine, board_before)
        eval_after = self._get_engine_eval(engine, board_after)
        if eval_before is None or eval_after is None:
            return None

        # Mate opportunity: after opponent move, it's player's turn.
        # If engine reports a positive mate score, side-to-move can force mate.
        if eval_after.kind == "mate" and eval_after.value > 0:
            # Still record eval_before in cp if available; if it was mate too, set 0.
            eval_before_cp = eval_before.value if eval_before.kind == "cp" else 0
            # Convert eval_before_cp to player's perspective (cp is from White POV)
            if player_color == chess.BLACK:
                eval_before_cp *= -1
            return {
                "opportunity_kind": "mate",
                "mate_in": int(eval_after.value),
                "eval_before": int(eval_before_cp),
            }

        # Centipawn opportunity
        if eval_before.kind != "cp" or eval_after.kind != "cp":
            return None

        eval_before_cp = eval_before.value
        eval_after_cp = eval_after.value

        # Convert to player's POV (cp is from White POV)
        if player_color == chess.BLACK:
            eval_before_cp *= -1
            eval_after_cp *= -1

        opportunity_cp = int(eval_after_cp - eval_before_cp)
        if opportunity_cp < config.DELTA_CUTOFF_CP:
            return None

        return {
            "opportunity_kind": "cp",
            "opportunity_cp": int(opportunity_cp),
            "eval_before": int(eval_before_cp),
        }

    def _pv_walk_collect(
        self,
        engine: Stockfish,
        start_board: chess.Board,
        max_plies: int,
    ) -> Tuple[List[str], List[int], Optional[int]]:
        """
        Walk best moves from a start position.
        Returns (pv_moves_uci, pv_evals_cp, plies_to_checkmate_if_reached).
        pv_evals_cp are centipawns from White POV when available; mate positions store 0.
        """
        b = start_board.copy()
        pv_moves: List[str] = []
        pv_evals: List[int] = []

        for ply in range(1, max_plies + 1):
            if b.is_game_over():
                break
            engine.set_fen_position(b.fen())
            best = engine.get_best_move()
            if not best:
                break
            b.push(chess.Move.from_uci(best))
            pv_moves.append(best)

            ev = self._get_engine_eval(engine, b)
            if ev is None:
                pv_evals.append(0)
            elif ev.kind == "cp":
                pv_evals.append(int(ev.value))
            else:
                pv_evals.append(0)

            if b.is_checkmate():
                return pv_moves, pv_evals, ply

        return pv_moves, pv_evals, None

    def compute_engine_time_to_mate(
        self, engine: Stockfish, board_after: chess.Board
    ) -> Optional[Tuple[int, List[str], List[int]]]:
        """
        Returns (t_plies_to_mate, pv_moves, pv_evals) or None if mate not delivered within horizon.
        """
        pv_moves, pv_evals, mate_ply = self._pv_walk_collect(
            engine, board_after, config.MAX_HORIZON_PLIES
        )
        if mate_ply is None:
            return None
        # For mate, t_plies is plies-to-checkmate (terminal), no 3-ply window.
        return mate_ply, pv_moves, pv_evals

    def compute_engine_conversion_time_hold3_first_ply(
        self,
        engine: Stockfish,
        board_after: chess.Board,
        opportunity_cp: int,
        player_color: chess.Color,
    ) -> Optional[Tuple[int, List[str], List[int]]]:
        """
        Material conversion time under "hold for 3 plies" rule.

        We simulate best play. When the material threshold is reached, we require it to remain
        beyond the threshold for 3 consecutive plies.

        Returns:
          (t_first_ply, pv_moves_up_to_t_first_ply, pv_evals_up_to_t_first_ply)
        or None if not achieved within horizon.
        """
        material_before = self.get_material_value(board_after)
        target_pawns = opportunity_cp // 100

        # Material metric is from White POV (white - black)
        # Convert threshold direction based on player_color.
        if player_color == chess.BLACK:
            # For black, gaining material means white-black decreases
            target_material = material_before - target_pawns
        else:
            target_material = material_before + target_pawns

        b = board_after.copy()
        pv_moves_full: List[str] = []
        pv_evals_full: List[int] = []

        sustained = 0
        first_cross: Optional[int] = None

        for ply in range(1, config.MAX_HORIZON_PLIES + 1):
            if b.is_game_over():
                return None

            engine.set_fen_position(b.fen())
            best = engine.get_best_move()
            if not best:
                return None
            b.push(chess.Move.from_uci(best))
            pv_moves_full.append(best)

            ev = self._get_engine_eval(engine, b)
            if ev is None:
                pv_evals_full.append(0)
            elif ev.kind == "cp":
                pv_evals_full.append(int(ev.value))
            else:
                pv_evals_full.append(0)

            current_material = self.get_material_value(b)
            crossed = (
                current_material <= target_material
                if player_color == chess.BLACK
                else current_material >= target_material
            )

            if crossed:
                if first_cross is None:
                    first_cross = ply
                sustained += 1
                if sustained >= 3:
                    # Return the FIRST ply where threshold was crossed & held
                    assert first_cross is not None
                    t_first = first_cross
                    return (
                        t_first,
                        pv_moves_full[:t_first],
                        pv_evals_full[:t_first],
                    )
            else:
                sustained = 0
                first_cross = None

        return None

    def check_actual_conversion_hold3_first_ply(
        self,
        board_after: chess.Board,
        remaining_moves: List[chess.Move],
        target_pawns: int,
        player_color: chess.Color,
        horizon: int,
    ) -> Tuple[bool, Optional[int]]:
        """
        In the actual game, did the player convert material (hold for 3 plies)?
        Returns (converted, t_first_ply) where t_first_ply is first ply of hold window.
        """
        material_before = self.get_material_value(board_after)
        if player_color == chess.BLACK:
            target_material = material_before - target_pawns
        else:
            target_material = material_before + target_pawns

        b = board_after.copy()
        sustained = 0
        first_cross: Optional[int] = None

        for ply_idx, mv in enumerate(remaining_moves[:horizon], start=1):
            b.push(mv)
            current_material = self.get_material_value(b)
            crossed = (
                current_material <= target_material
                if player_color == chess.BLACK
                else current_material >= target_material
            )
            if crossed:
                if first_cross is None:
                    first_cross = ply_idx
                sustained += 1
                if sustained >= 3:
                    assert first_cross is not None
                    return True, first_cross
            else:
                sustained = 0
                first_cross = None
        return False, None

    def check_actual_mate(
        self,
        board_after: chess.Board,
        remaining_moves: List[chess.Move],
        horizon: int,
        player_color: chess.Color,
    ) -> Tuple[bool, Optional[int]]:
        """
        In the actual game, did the player deliver checkmate within horizon plies?
        Returns (converted, t_plies_to_mate).
        """
        b = board_after.copy()
        for ply_idx, mv in enumerate(remaining_moves[:horizon], start=1):
            b.push(mv)
            if b.is_checkmate():
                # Winner is side who just moved
                winner = not b.turn
                if winner == player_color:
                    return True, ply_idx
                return False, None
        return False, None

    def get_material_value(self, board: chess.Board) -> int:
        """
        Material value as (white - black) using config.MATERIAL_VALUES.
        Keys in config are expected to match chess piece constants names (PAWN, KNIGHT, ...).
        """
        total = 0
        for piece_name, value in config.MATERIAL_VALUES.items():
            piece_type = getattr(chess, piece_name)
            total += len(board.pieces(piece_type, chess.WHITE)) * value
            total -= len(board.pieces(piece_type, chess.BLACK)) * value
        return total

    def analyze_game(self, pgn_string: str, player_username: str) -> List[Dict]:
        """
        Analyze a single game and return ALL opportunities (missed + converted),
        including mate opportunities.
        """
        engine = self._init_engine()
        try:
            game, positions = self.parse_pgn(pgn_string)
            if game is None:
                return []

            white_name = game.headers.get("White", "").lower()
            black_name = game.headers.get("Black", "").lower()
            u = player_username.lower()

            if u == white_name:
                player_color = chess.WHITE
                opponent_color = chess.BLACK
            elif u == black_name:
                player_color = chess.BLACK
                opponent_color = chess.WHITE
            else:
                return []

            moves = list(game.mainline_moves())
            opportunities: List[Dict] = []

            for i in range(len(positions) - 1):
                board_before = positions[i]
                if board_before.turn != opponent_color:
                    continue

                mv = moves[i]
                board_after = positions[i + 1]

                opp_info = self.compute_opportunity_kind(
                    engine, board_before, board_after, player_color
                )
                if opp_info is None:
                    continue

                remaining_moves = moves[i + 1 :]

                if opp_info["opportunity_kind"] == "mate":
                    # Engine time-to-mate (plies-to-checkmate)
                    mate_result = self.compute_engine_time_to_mate(engine, board_after)
                    if mate_result is None:
                        # unrealized within horizon, skip
                        continue
                    t_engine, pv_moves, pv_evals = mate_result

                    # Actual conversion: did player deliver mate within horizon?
                    converted, t_actual = self.check_actual_mate(
                        board_after, remaining_moves, config.MAX_HORIZON_PLIES, player_color
                    )

                    # Best reply is first PV move
                    best_reply_uci = pv_moves[0] if pv_moves else ""
                    best_reply_san = ""
                    if best_reply_uci:
                        try:
                            tb = board_after.copy()
                            m = chess.Move.from_uci(best_reply_uci)
                            best_reply_san = tb.san(m)
                        except Exception:
                            best_reply_san = best_reply_uci

                    opportunities.append(
                        {
                            "username": player_username,
                            "game_url": game.headers.get("Site", ""),
                            "opponent_move_ply_index": i,
                            "opponent_move_san": board_before.san(mv),
                            "opponent_move_uci": mv.uci(),
                            "opportunity_kind": "mate",
                            "opportunity_cp": None,
                            "mate_in": int(opp_info["mate_in"]),
                            "target_pawns": 0,
                            "t_turns_engine": int(t_engine),
                            "converted_actual": 1 if converted else 0,
                            "t_turns_actual": int(t_actual) if t_actual is not None else None,
                            "best_reply_uci": best_reply_uci,
                            "best_reply_san": best_reply_san,
                            "fen_before": board_before.fen(),
                            "fen_after": board_after.fen(),
                            "pv_moves": "|".join(pv_moves),
                            "pv_evals": "|".join(map(str, pv_evals)),
                            "eval_before": int(opp_info["eval_before"]),
                            "white_player": game.headers.get("White", ""),
                            "black_player": game.headers.get("Black", ""),
                            "player_color": "white" if player_color == chess.WHITE else "black",
                            "time_control": game.headers.get("TimeControl", ""),
                            "game_result": game.headers.get("Result", ""),
                            "end_time": (game.headers.get("UTCDate", "") + " " + game.headers.get("UTCTime", "")).strip(),
                        }
                    )
                    continue

                # CP case
                opportunity_cp = int(opp_info["opportunity_cp"])

                # Engine conversion time (hold 3 plies) but RETURN first ply of hold window
                conv = self.compute_engine_conversion_time_hold3_first_ply(
                    engine, board_after, opportunity_cp, player_color
                )
                if conv is None:
                    continue
                t_engine_first, pv_moves, pv_evals = conv

                target_pawns = opportunity_cp // 100

                converted, t_actual_first = self.check_actual_conversion_hold3_first_ply(
                    board_after,
                    remaining_moves,
                    target_pawns,
                    player_color,
                    horizon=config.MAX_HORIZON_PLIES,
                )

                best_reply_uci = pv_moves[0] if pv_moves else ""
                best_reply_san = ""
                if best_reply_uci:
                    try:
                        tb = board_after.copy()
                        m = chess.Move.from_uci(best_reply_uci)
                        best_reply_san = tb.san(m)
                    except Exception:
                        best_reply_san = best_reply_uci

                opportunities.append(
                    {
                        "username": player_username,
                        "game_url": game.headers.get("Site", ""),
                        "opponent_move_ply_index": i,
                        "opponent_move_san": board_before.san(mv),
                        "opponent_move_uci": mv.uci(),
                        "opportunity_kind": "cp",
                        "opportunity_cp": int(opportunity_cp),
                        "mate_in": None,
                        "target_pawns": int(target_pawns),
                        "t_turns_engine": int(t_engine_first),
                        "converted_actual": 1 if converted else 0,
                        "t_turns_actual": int(t_actual_first) if t_actual_first is not None else None,
                        "best_reply_uci": best_reply_uci,
                        "best_reply_san": best_reply_san,
                        "fen_before": board_before.fen(),
                        "fen_after": board_after.fen(),
                        "pv_moves": "|".join(pv_moves),
                        "pv_evals": "|".join(map(str, pv_evals)),
                        "eval_before": int(opp_info["eval_before"]),
                        "white_player": game.headers.get("White", ""),
                        "black_player": game.headers.get("Black", ""),
                        "player_color": "white" if player_color == chess.WHITE else "black",
                        "time_control": game.headers.get("TimeControl", ""),
                        "game_result": game.headers.get("Result", ""),
                        "end_time": (game.headers.get("UTCDate", "") + " " + game.headers.get("UTCTime", "")).strip(),
                    }
                )

            return opportunities
        finally:
            # Ensure Stockfish process is cleaned up
            del engine



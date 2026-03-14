"""
Configuration for chess analysis.
"""

import os

STOCKFISH_PATH = os.environ.get("STOCKFISH_PATH", "/opt/homebrew/bin/stockfish")
STOCKFISH_DEPTH = int(os.environ.get("STOCKFISH_DEPTH", "15"))

DELTA_CUTOFF_CP = 100
MAX_HORIZON_PLIES = 40

# Per-game analysis timeout in seconds (0 = no limit)
ANALYSIS_TIMEOUT_SEC = int(os.environ.get("ANALYSIS_TIMEOUT_SEC", "600"))

MATERIAL_VALUES = {
    'PAWN': 1,
    'KNIGHT': 3,
    'BISHOP': 3,
    'ROOK': 5,
    'QUEEN': 9,
    'KING': 0
}

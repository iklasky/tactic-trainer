"""
Configuration for chess analysis.
"""

import os

# Stockfish configuration — override STOCKFISH_PATH env var in production Docker images
STOCKFISH_PATH = os.environ.get("STOCKFISH_PATH", "/opt/homebrew/bin/stockfish")
STOCKFISH_DEPTH = 20

# Analysis parameters
DELTA_CUTOFF_CP = 100  # Minimum centipawns to consider as opportunity
MAX_HORIZON_PLIES = 40  # Maximum plies to look ahead for conversion

# Material values (in pawns)
MATERIAL_VALUES = {
    'PAWN': 1,
    'KNIGHT': 3,
    'BISHOP': 3,
    'ROOK': 5,
    'QUEEN': 9,
    'KING': 0
}


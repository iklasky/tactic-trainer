import React, { useState, useEffect } from 'react';
import { Chessboard } from 'react-chessboard';
import { Chess } from 'chess.js';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import type { ErrorEvent } from '../types';

interface ChessBoardViewerProps {
  error: ErrorEvent;
}

const ChessBoardViewer: React.FC<ChessBoardViewerProps> = ({ error }) => {
  const [position, setPosition] = useState(error.fen_after);
  const [moveIndex, setMoveIndex] = useState(-1); // -1 = before best reply, 0+ = PV moves
  const [customArrows, setCustomArrows] = useState<any[]>([]);
  const [currentEval, setCurrentEval] = useState(0);
  const [materialDiff, setMaterialDiff] = useState(0);
  const [baselineMaterial, setBaselineMaterial] = useState(0);
  
  // Reset when error changes
  useEffect(() => {
    setPosition(error.fen_after);
    setMoveIndex(-1);
    updateArrows(error.fen_after);
    
    // Set initial eval and material
    // Use the same conversion logic as navigation (eval_before is stored in centipawns)
    setCurrentEval((error.eval_before || 0) / 100);
    
    // Calculate baseline material at starting position
    const baseline = getAbsoluteMaterialDiff(error.fen_after);
    setBaselineMaterial(baseline);
    setMaterialDiff(0); // Start at 0 since we're at the baseline
  }, [error]);
  
  const updateArrows = (currentFen: string) => {
    const arrows = [];
    
    // Black arrow for opponent's mistake
    const opponentMoveFrom = error.move_uci.slice(0, 2);
    const opponentMoveTo = error.move_uci.slice(2, 4);
    arrows.push([opponentMoveFrom, opponentMoveTo, 'rgba(0, 0, 0, 0.5)']);
    
    // Light blue arrow for best reply (only if we haven't started PV yet)
    if (moveIndex === -1 && error.best_move_uci) {
      const bestMoveFrom = error.best_move_uci.slice(0, 2);
      const bestMoveTo = error.best_move_uci.slice(2, 4);
      arrows.push([bestMoveFrom, bestMoveTo, 'rgba(135, 206, 250, 0.7)']);
    }
    
    setCustomArrows(arrows);
  };
  
  // Calculate absolute material difference on the board
  const getAbsoluteMaterialDiff = (fen: string): number => {
    const chess = new Chess(fen);
    const board = chess.board();
    
    const pieceValues: Record<string, number> = {
      'p': 1, 'n': 3, 'b': 3, 'r': 5, 'q': 9, 'k': 0
    };
    
    let whiteMaterial = 0;
    let blackMaterial = 0;
    
    board.forEach(row => {
      row.forEach(square => {
        if (square) {
          const value = pieceValues[square.type];
          if (square.color === 'w') {
            whiteMaterial += value;
          } else {
            blackMaterial += value;
          }
        }
      });
    });
    
    // Return from player's perspective
    // If FEN shows White to move (" w "), player is White
    const playerIsWhite = error.fen_after.includes(' w ');
    return playerIsWhite ? (whiteMaterial - blackMaterial) : (blackMaterial - whiteMaterial);
  };
  
  // Calculate change in material from baseline position
  const calculateMaterialChange = (fen: string): number => {
    const currentMaterial = getAbsoluteMaterialDiff(fen);
    return currentMaterial - baselineMaterial;
  };
  
  const getEvalForPosition = (index: number): number => {
    // index -1 = before best reply (use eval_before)
    // index 0 = after best reply (use pv_evals[0])
    // index 1+ = subsequent PV positions (use pv_evals[index])
    
    if (index === -1) {
      // eval_before is in centipawns, convert to pawns
      return (error.eval_before || 0) / 100;
    }
    
    if (error.pv_evals && error.pv_evals.length > 0) {
      // pv_evals are in centipawns, always from White's perspective
      // pv_evals[0] is eval after best reply
      // pv_evals[1] is eval after opponent's response, etc.
      const evalIndex = index;
      if (evalIndex < error.pv_evals.length) {
        // Convert centipawns to pawns
        return error.pv_evals[evalIndex] / 100;
      }
    }
    
    // Fallback: linear interpolation
    const progress = (index + 1) / (error.t_plies || 1);
    return (error.eval_before || 0) / 100 + (error.delta_cp / 100) * progress;
  };
  
  const handleNext = () => {
    if (moveIndex >= error.t_plies) return;
    
    const chess = new Chess(position);
    const newIndex = moveIndex + 1;
    
    if (newIndex === 0) {
      // Apply best reply
      if (error.best_move_uci) {
        try {
          const from = error.best_move_uci.slice(0, 2);
          const to = error.best_move_uci.slice(2, 4);
          const promotion = error.best_move_uci.length > 4 ? error.best_move_uci[4] : undefined;
          
          chess.move({ from, to, promotion });
          setPosition(chess.fen());
          setMoveIndex(0);
          setCustomArrows([]);
          
          // Update eval and material
          const newEval = getEvalForPosition(0);
          setCurrentEval(newEval);
          setMaterialDiff(calculateMaterialChange(chess.fen()));
        } catch (e) {
          console.error('Failed to apply best move:', e);
        }
      }
    } else {
      // Apply PV move (pv_moves[0] is the best reply, already played)
      const pvMoveIndex = newIndex;
      if (pvMoveIndex < error.pv_moves.length) {
        const pvMove = error.pv_moves[pvMoveIndex];
        try {
          const tempChess = new Chess(position);
          const from = pvMove.slice(0, 2);
          const to = pvMove.slice(2, 4);
          const promotion = pvMove.length > 4 ? pvMove[4] : undefined;
          
          tempChess.move({ from, to, promotion });
          setPosition(tempChess.fen());
          setMoveIndex(newIndex);
          
          // Update eval and material
          const newEval = getEvalForPosition(newIndex);
          setCurrentEval(newEval);
          setMaterialDiff(calculateMaterialChange(tempChess.fen()));
        } catch (e) {
          console.error('Failed to apply PV move:', e);
        }
      }
    }
  };
  
  const handlePrevious = () => {
    if (moveIndex === -1) return;
    
    if (moveIndex === 0) {
      // Go back to position after opponent's mistake
      setPosition(error.fen_after);
      setMoveIndex(-1);
      updateArrows(error.fen_after);
      
      // Update eval and material
      const newEval = getEvalForPosition(-1);
      setCurrentEval(newEval);
      setMaterialDiff(0); // Back to baseline
    } else {
      // Rebuild position from scratch
      try {
        const chess = new Chess(error.fen_after);
        
        // Apply best reply
        if (error.best_move_uci) {
          const from = error.best_move_uci.slice(0, 2);
          const to = error.best_move_uci.slice(2, 4);
          const promotion = error.best_move_uci.length > 4 ? error.best_move_uci[4] : undefined;
          chess.move({ from, to, promotion });
        }
        
        // Apply PV moves up to new index (skip pv_moves[0], it's the best reply)
        const newIndex = moveIndex - 1;
        for (let i = 1; i <= newIndex; i++) {
          if (i < error.pv_moves.length) {
            const pvMove = error.pv_moves[i];
            const from = pvMove.slice(0, 2);
            const to = pvMove.slice(2, 4);
            const promotion = pvMove.length > 4 ? pvMove[4] : undefined;
            chess.move({ from, to, promotion });
          }
        }
        
        setPosition(chess.fen());
        setMoveIndex(newIndex);
        
        // Update eval and material
        const newEval = getEvalForPosition(newIndex);
        setCurrentEval(newEval);
        setMaterialDiff(calculateMaterialChange(chess.fen()));
      } catch (e) {
        console.error('Failed to rebuild position:', e);
      }
    }
  };
  
  const getPositionLabel = () => {
    if (moveIndex === -1) {
      return `Position before move (Move ${error.ply_index + 1})`;
    } else {
      return `After best play: move ${moveIndex} of ${error.t_plies}`;
    }
  };
  
  // Render evaluation bar
  const renderEvalBar = () => {
    // Clamp eval between -10 and +10 (in pawns)
    const clampedEval = Math.max(-10, Math.min(10, currentEval));
    
    // Calculate percentage for white (top is +10, bottom is -10)
    // If eval is +10 (white winning), white fill should be 100%
    // If eval is -10 (black winning), white fill should be 0%
    // If eval is 0, white fill should be 50%
    const whitePercent = ((clampedEval + 10) / 20) * 100;
    const blackPercent = 100 - whitePercent;
    
    return (
      <div className="flex flex-col items-center">
        <div className="text-slate-400 text-sm mb-2">Position Evaluation</div>
        
        {/* Eval Bar */}
        <div className="relative w-12 h-64 border-2 border-slate-600 rounded overflow-hidden">
          {/* White advantage (top) */}
          <div 
            className="absolute top-0 left-0 right-0 bg-white transition-all duration-300"
            style={{ height: `${whitePercent}%` }}
          ></div>
          
          {/* Black advantage (bottom) */}
          <div 
            className="absolute bottom-0 left-0 right-0 bg-black transition-all duration-300"
            style={{ height: `${blackPercent}%` }}
          ></div>
          
          {/* Center line */}
          <div className="absolute left-0 right-0 h-0.5 bg-slate-400" style={{ top: '50%' }}></div>
        </div>
        
        {/* Eval Value */}
        <div className={`mt-2 font-mono text-sm font-bold ${
          currentEval > 0 ? 'text-white' : currentEval < 0 ? 'text-slate-300' : 'text-slate-400'
        }`}>
          {currentEval > 0 ? '+' : ''}{currentEval.toFixed(1)}
        </div>
        
        {/* Material Difference */}
        <div className="mt-4">
          <div className="text-slate-400 text-xs mb-1 text-center">Material</div>
          <div className={`font-mono text-lg font-bold ${
            materialDiff > 0 ? 'text-green-400' : materialDiff < 0 ? 'text-red-400' : 'text-slate-400'
          }`}>
            {materialDiff > 0 ? '+' : ''}{materialDiff}
          </div>
        </div>
      </div>
    );
  };
  
  // Calculate material equivalent from eval
  const materialEquivalent = Math.floor(error.delta_cp / 100);
  
  // Determine whose opportunity it was (player's turn after opponent's mistake)
  const playerColor = error.fen_after.includes(' w ') ? 'White' : 'Black';
  
  return (
    <div className="bg-slate-800 p-6 rounded-lg shadow-lg">
      <h3 className="text-xl font-bold text-white mb-4">Missed Opportunity Analysis</h3>
      
      {/* Opportunity Description */}
      <div className="mb-4 p-4 bg-slate-700 rounded-lg">
        <p className="text-slate-200 text-sm">
          <span className="font-semibold text-white">{playerColor}</span> had the opportunity to score <span className="italic">at least</span>{' '}
          <span className="font-semibold text-green-400">{materialEquivalent} points of material</span> and{' '}
          <span className="font-semibold text-blue-400">{error.delta_cp} evaluation points</span> in{' '}
          <span className="font-semibold text-violet-400">{error.t_plies} moves</span>
        </p>
      </div>
      
      <div className="grid md:grid-cols-[400px_auto_1fr] gap-6">
        {/* Chess Board */}
        <div>
          <div className="mb-4">
            <Chessboard
              position={position}
              boardWidth={400}
              customArrows={customArrows}
              areDragsForbidden={true}
              customBoardStyle={{
                borderRadius: '4px',
                boxShadow: '0 4px 6px rgba(0, 0, 0, 0.3)'
              }}
            />
          </div>
          
          {/* Navigation */}
          <div className="flex items-center justify-between bg-slate-700 p-3 rounded">
            <button
              onClick={handlePrevious}
              disabled={moveIndex === -1}
              className="p-2 bg-slate-600 hover:bg-slate-500 disabled:bg-slate-800 disabled:cursor-not-allowed rounded transition-colors"
            >
              <ChevronLeft className="w-5 h-5 text-white" />
            </button>
            
            <span className="text-slate-200 text-sm font-medium px-4 text-center">
              {getPositionLabel()}
            </span>
            
            <button
              onClick={handleNext}
              disabled={moveIndex >= error.t_plies}
              className="p-2 bg-slate-600 hover:bg-slate-500 disabled:bg-slate-800 disabled:cursor-not-allowed rounded transition-colors"
            >
              <ChevronRight className="w-5 h-5 text-white" />
            </button>
          </div>
        </div>
        
        {/* Eval Bar */}
        <div className="flex items-start justify-center pt-12">
          {renderEvalBar()}
        </div>
        
        {/* Move Details */}
        <div className="space-y-4">
          {/* Opponent's Mistake */}
          <div className="bg-slate-700 p-4 rounded-lg">
            <div className="text-slate-400 text-sm mb-1">Opponent's Mistake</div>
            <div className="text-white text-2xl font-bold font-mono">{error.move_san}</div>
            <div className="text-slate-400 text-xs mt-1">({error.move_uci})</div>
          </div>
          
          {/* Best Response */}
          <div className="bg-slate-700 p-4 rounded-lg">
            <div className="text-slate-400 text-sm mb-1">Best Response</div>
            <div className="text-indigo-400 text-2xl font-bold font-mono">{error.best_move_san}</div>
            <div className="text-slate-400 text-xs mt-1">({error.best_move_uci})</div>
          </div>
          
          {/* Opportunity Gained */}
          <div className="bg-slate-700 p-4 rounded-lg">
            <div className="text-slate-400 text-sm mb-1">Opportunity Gained</div>
            <div className="text-green-400 text-2xl font-bold">+{error.delta_cp} cp</div>
          </div>
          
          {/* Engine Conversion Time */}
          <div className="bg-slate-700 p-4 rounded-lg">
            <div className="text-slate-400 text-sm mb-1">Engine Conversion Time</div>
            <div className="text-indigo-400 font-bold text-xl">{error.t_plies} moves</div>
            <div className="text-slate-400 text-xs mt-1">
              Material gain after {error.t_plies} moves of perfect play
            </div>
          </div>
          
          {/* Game Link */}
          <div className="bg-slate-700 p-4 rounded-lg">
            <div className="text-slate-400 text-sm mb-2">View Full Game</div>
            <a
              href={error.game_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-indigo-400 hover:text-indigo-300 underline break-all"
            >
              {error.game_url}
            </a>
          </div>
        </div>
      </div>
      
      {/* Arrow Legend */}
      <div className="mt-6 pt-6 border-t border-slate-700">
        <div className="text-slate-400 text-sm font-semibold mb-3">Arrow Legend</div>
        <div className="flex gap-6">
          <div className="flex items-center gap-2">
            <div className="w-4 h-4 bg-black opacity-50 rounded"></div>
            <span className="text-slate-300 text-sm">Opponent's mistake</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-4 h-4 bg-sky-300 opacity-70 rounded"></div>
            <span className="text-slate-300 text-sm">Best response (missed)</span>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ChessBoardViewer;


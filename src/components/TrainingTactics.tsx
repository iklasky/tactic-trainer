import React, { useCallback, useMemo, useState } from 'react';
import { Chessboard } from 'react-chessboard';
import { Chess } from 'chess.js';
import { Loader2, RefreshCw, ChevronRight, CheckCircle2, XCircle, Eye } from 'lucide-react';
import {
  fetchTrainingTactics,
  type TrainingPuzzle,
  type TrainingCellSummary,
  type TrainingTacticsResponse,
} from '../api';
import type { ErrorEvent } from '../types';
import ChessBoardViewer from './ChessBoardViewer';

interface Props {
  username: string;
  minElo: number;
  maxElo: number;
  eloRangeLabel: string;
}

type Phase = 'idle' | 'loading' | 'playing' | 'results';

interface PuzzleResult {
  puzzle: TrainingPuzzle;
  status: 'success' | 'failed';
  /** Engine ply on which the user went wrong (0 = first move). undefined if successful. */
  failedAtMove?: number;
  expectedMove?: string;
  attemptedMove?: string;
}

// Convert a UCI string ("e2e4", "e7e8q") into the {from, to, promotion} shape
// chess.js wants for a programmatic engine move.
function uciToMoveObj(uci: string): { from: string; to: string; promotion?: string } {
  return {
    from: uci.slice(0, 2),
    to:   uci.slice(2, 4),
    promotion: uci.length >= 5 ? uci.slice(4, 5) : undefined,
  };
}

// Convert chess.js move to a UCI string for comparison.
function moveToUci(m: { from: string; to: string; promotion?: string }): string {
  return m.from + m.to + (m.promotion || '');
}

// Convert a TrainingPuzzle to the ErrorEvent shape that ChessBoardViewer expects.
function puzzleToErrorEvent(p: TrainingPuzzle): ErrorEvent {
  return {
    delta_cp: p.delta_cp,
    t_plies: p.t_plies,
    ply_index: p.ply_index,
    move_san: p.move_san,
    move_uci: p.move_uci,
    best_move_uci: p.best_move_uci,
    best_move_san: p.best_move_san,
    fen: p.fen,
    fen_after: p.fen_after,
    pv_moves: p.pv_moves,
    pv_evals: p.pv_evals,
    eval_before: p.eval_before,
    game_url: p.game_url,
    converted_actual: p.converted_actual,
    conversion_method: p.conversion_method as ErrorEvent['conversion_method'],
    opportunity_kind: p.opportunity_kind,
    mate_in: p.mate_in ?? undefined,
  };
}

const TrainingTactics: React.FC<Props> = ({ username, minElo, maxElo, eloRangeLabel }) => {
  const [phase, setPhase] = useState<Phase>('idle');
  const [error, setError] = useState<string | null>(null);
  const [tactics, setTactics] = useState<TrainingTacticsResponse | null>(null);

  // Per-puzzle play state
  const [currentIdx, setCurrentIdx] = useState(0);
  const [chess, setChess] = useState<Chess | null>(null);
  const [boardFen, setBoardFen] = useState<string>('');
  const [pvCursor, setPvCursor] = useState(0); // index into puzzle.pv_moves
  const [feedback, setFeedback] = useState<{ kind: 'correct' | 'wrong' | 'done'; text: string } | null>(null);
  const [results, setResults] = useState<PuzzleResult[]>([]);

  // Results-screen state
  const [reviewing, setReviewing] = useState<number | null>(null);

  const startPuzzle = useCallback((puzzle: TrainingPuzzle) => {
    const c = new Chess(puzzle.fen_after);
    setChess(c);
    setBoardFen(c.fen());
    setPvCursor(0);
    setFeedback(null);
  }, []);

  const beginSet = useCallback(async () => {
    setPhase('loading');
    setError(null);
    setResults([]);
    setReviewing(null);
    try {
      const data = await fetchTrainingTactics(username, minElo, maxElo, 10);
      if (!data.puzzles || data.puzzles.length === 0) {
        setError('No training puzzles available for this player.');
        setPhase('idle');
        return;
      }
      setTactics(data);
      setCurrentIdx(0);
      startPuzzle(data.puzzles[0]);
      setPhase('playing');
    } catch (e: any) {
      setError(e.message || 'Failed to generate training tactics.');
      setPhase('idle');
    }
  }, [username, minElo, maxElo, startPuzzle]);

  const advanceToNext = useCallback((newResult: PuzzleResult) => {
    setResults(prev => {
      const next = [...prev, newResult];
      // If that was the last puzzle, transition to results
      if (!tactics || next.length >= tactics.puzzles.length) {
        setPhase('results');
        return next;
      }
      const nextIdx = next.length;
      setCurrentIdx(nextIdx);
      startPuzzle(tactics.puzzles[nextIdx]);
      return next;
    });
  }, [tactics, startPuzzle]);

  const skipPuzzle = useCallback(() => {
    if (!tactics) return;
    const puzzle = tactics.puzzles[currentIdx];
    advanceToNext({
      puzzle,
      status: 'failed',
      failedAtMove: pvCursor,
      expectedMove: puzzle.pv_moves[pvCursor],
      attemptedMove: '(skipped)',
    });
  }, [tactics, currentIdx, pvCursor, advanceToNext]);

  // Validate a user move against the expected PV position.
  const onPieceDrop = useCallback((sourceSquare: string, targetSquare: string, piece: string): boolean => {
    if (!chess || !tactics) return false;
    const puzzle = tactics.puzzles[currentIdx];
    const expectedUci = puzzle.pv_moves[pvCursor];
    if (!expectedUci) return false;

    // Default promotion to queen — same letter case as react-chessboard's `piece` arg lowercase.
    const promotion = piece && piece.length >= 2 ? piece[1].toLowerCase() : 'q';

    const trial = new Chess(chess.fen());
    let move;
    try {
      move = trial.move({ from: sourceSquare, to: targetSquare, promotion });
    } catch {
      return false;
    }
    if (!move) return false;

    const attemptedUci = moveToUci({ from: move.from, to: move.to, promotion: move.promotion });

    if (attemptedUci.toLowerCase() !== expectedUci.toLowerCase()) {
      // Wrong move → puzzle failed
      setFeedback({
        kind: 'wrong',
        text: `Wrong move. Best was ${puzzle.pv_moves[pvCursor]}. Moving on…`,
      });
      // Hold the wrong feedback briefly so the user sees it, then advance.
      setTimeout(() => {
        advanceToNext({
          puzzle,
          status: 'failed',
          failedAtMove: pvCursor,
          expectedMove: expectedUci,
          attemptedMove: attemptedUci,
        });
      }, 1100);
      return false; // don't accept the move on the board
    }

    // Correct → apply it
    setChess(trial);
    setBoardFen(trial.fen());
    let cursor = pvCursor + 1;

    // Auto-play engine reply (next PV move) if there is one
    const nextEngineUci = puzzle.pv_moves[cursor];
    if (nextEngineUci) {
      try {
        trial.move(uciToMoveObj(nextEngineUci));
        setBoardFen(trial.fen());
        cursor += 1;
      } catch {
        // PV malformed — treat as success and end this puzzle.
        setFeedback({ kind: 'done', text: 'Solved!' });
        setTimeout(() => {
          advanceToNext({ puzzle, status: 'success' });
        }, 700);
        return true;
      }
    }

    setPvCursor(cursor);

    // If we have run out of PV (we're at the engine horizon), puzzle solved.
    if (cursor >= puzzle.pv_moves.length) {
      setFeedback({ kind: 'done', text: 'Solved!' });
      setTimeout(() => {
        advanceToNext({ puzzle, status: 'success' });
      }, 700);
    } else {
      setFeedback({ kind: 'correct', text: 'Correct — find the next move.' });
    }
    return true;
  }, [chess, tactics, currentIdx, pvCursor, advanceToNext]);

  // Build a per-cell breakdown for the results screen.
  const cellBreakdown = useMemo(() => {
    if (results.length === 0) return [] as Array<{
      cell: { delta_idx: number; t_idx: number; delta_label: string; t_label: string };
      total: number;
      success: number;
      diff: number | null;
      summary?: TrainingCellSummary;
    }>;
    const byKey = new Map<string, {
      cell: { delta_idx: number; t_idx: number; delta_label: string; t_label: string };
      total: number;
      success: number;
    }>();
    for (const r of results) {
      const key = `${r.puzzle.cell.delta_idx},${r.puzzle.cell.t_idx}`;
      const existing = byKey.get(key) || { cell: r.puzzle.cell, total: 0, success: 0 };
      existing.total += 1;
      if (r.status === 'success') existing.success += 1;
      byKey.set(key, existing);
    }
    return Array.from(byKey.values()).map(b => {
      const summary = tactics?.cell_summary?.[`${b.cell.delta_idx},${b.cell.t_idx}`];
      return { ...b, diff: summary?.diff ?? null, summary };
    });
  }, [results, tactics]);

  // ── Phase: idle ─────────────────────────────────────────────────────────
  if (phase === 'idle') {
    return (
      <div className="bg-slate-800 p-6 rounded-lg shadow-lg mb-8 border-l-4 border-fuchsia-500">
        <h2 className="text-2xl font-bold text-white mb-2">Generate Training Tactics</h2>
        <p className="text-slate-300 text-sm mb-4">
          We'll pick 10 real positions from <span className="text-white font-semibold">{username}</span>'s
          games, biased toward heatmap cells where you're lagging the {eloRangeLabel} field. Find the
          best move (and the engine's whole line) — one wrong move and the puzzle is failed.
        </p>
        <button
          onClick={beginSet}
          className="bg-fuchsia-600 hover:bg-fuchsia-700 text-white px-6 py-3 rounded-lg font-semibold transition-colors flex items-center gap-2"
        >
          <RefreshCw className="w-5 h-5" />
          Generate Training Tactics
        </button>
        {error && (
          <div className="mt-4 bg-red-900/20 border border-red-500 text-red-200 p-3 rounded-lg text-sm">
            {error}
          </div>
        )}
      </div>
    );
  }

  // ── Phase: loading ──────────────────────────────────────────────────────
  if (phase === 'loading') {
    return (
      <div className="bg-slate-800 p-6 rounded-lg shadow-lg mb-8 border-l-4 border-fuchsia-500">
        <div className="flex items-center justify-center py-10">
          <Loader2 className="w-8 h-8 animate-spin text-fuchsia-400 mr-3" />
          <span className="text-slate-300">Generating your training set…</span>
        </div>
      </div>
    );
  }

  // ── Phase: playing ──────────────────────────────────────────────────────
  if (phase === 'playing' && tactics) {
    const puzzle = tactics.puzzles[currentIdx];
    const total = tactics.puzzles.length;
    const playerColor: 'white' | 'black' =
      puzzle.fen_after.includes(' w ') ? 'white' : 'black';

    return (
      <div className="bg-slate-800 p-6 rounded-lg shadow-lg mb-8 border-l-4 border-fuchsia-500">
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-2xl font-bold text-white">
            Training Puzzle {currentIdx + 1} <span className="text-slate-400 text-base">of {total}</span>
          </h2>
          <button
            onClick={skipPuzzle}
            className="text-sm text-slate-400 hover:text-white transition-colors"
          >
            Skip puzzle →
          </button>
        </div>

        <div className="grid md:grid-cols-[auto_1fr] gap-6">
          <div style={{ width: 'min(560px, 90vw)' }}>
            <Chessboard
              position={boardFen}
              onPieceDrop={onPieceDrop}
              boardOrientation={playerColor}
              boardWidth={Math.min(560, typeof window !== 'undefined' ? window.innerWidth - 64 : 560)}
              customBoardStyle={{ borderRadius: 8 }}
            />
          </div>

          <div className="space-y-3 text-sm">
            <div className="bg-slate-900/50 p-4 rounded-lg border border-slate-700">
              <div className="text-slate-400 mb-1">Heatmap cell</div>
              <div className="text-white font-semibold">
                {puzzle.cell.delta_label} cp · {puzzle.cell.t_label} moves
              </div>
            </div>
            <div className="bg-slate-900/50 p-4 rounded-lg border border-slate-700">
              <div className="text-slate-400 mb-1">Opponent's mistake</div>
              <div className="text-white font-mono">{puzzle.move_san}</div>
              <div className="text-slate-400 text-xs mt-1">
                Eval swing: {puzzle.opportunity_kind === 'mate' ? `mate in ${puzzle.mate_in ?? '?'}` : `+${puzzle.delta_cp} cp`}
              </div>
            </div>
            <div className="bg-slate-900/50 p-4 rounded-lg border border-slate-700">
              <div className="text-slate-400 mb-1">Your turn</div>
              <div className="text-white">
                Move {Math.floor(pvCursor / 2) + 1} of {Math.ceil(puzzle.pv_moves.length / 2)} —
                {' '}{playerColor === 'white' ? 'White' : 'Black'} to play.
              </div>
            </div>
            {feedback && (
              <div
                className={
                  'p-3 rounded-lg text-sm ' +
                  (feedback.kind === 'wrong'
                    ? 'bg-red-900/30 border border-red-500 text-red-200'
                    : feedback.kind === 'correct'
                    ? 'bg-emerald-900/30 border border-emerald-500 text-emerald-200'
                    : 'bg-indigo-900/30 border border-indigo-500 text-indigo-200')
                }
              >
                {feedback.text}
              </div>
            )}

            {/* Mini progress strip */}
            <div className="flex gap-1 mt-4">
              {tactics.puzzles.map((_, i) => {
                const r = results[i];
                let cls = 'flex-1 h-2 rounded-full ';
                if (i === currentIdx) cls += 'bg-fuchsia-500';
                else if (!r) cls += 'bg-slate-700';
                else cls += r.status === 'success' ? 'bg-emerald-500' : 'bg-red-500';
                return <div key={i} className={cls} />;
              })}
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ── Phase: results ──────────────────────────────────────────────────────
  if (phase === 'results' && tactics) {
    const successCount = results.filter(r => r.status === 'success').length;
    const failCount = results.length - successCount;

    return (
      <div className="bg-slate-800 p-6 rounded-lg shadow-lg mb-8 border-l-4 border-fuchsia-500">
        <h2 className="text-2xl font-bold text-white mb-4">Training Results</h2>

        <div className="grid grid-cols-3 gap-4 mb-6">
          <div className="bg-slate-900/50 p-4 rounded-lg border border-slate-700">
            <div className="text-slate-400 text-sm">Solved</div>
            <div className="text-3xl font-bold text-emerald-400">{successCount}</div>
          </div>
          <div className="bg-slate-900/50 p-4 rounded-lg border border-slate-700">
            <div className="text-slate-400 text-sm">Failed</div>
            <div className="text-3xl font-bold text-red-400">{failCount}</div>
          </div>
          <div className="bg-slate-900/50 p-4 rounded-lg border border-slate-700">
            <div className="text-slate-400 text-sm">Score</div>
            <div className="text-3xl font-bold text-white">
              {Math.round((successCount / Math.max(1, results.length)) * 100)}%
            </div>
          </div>
        </div>

        {/* Per-cell breakdown */}
        <div className="mb-6">
          <h3 className="text-lg font-semibold text-slate-300 mb-3">By heatmap cell</h3>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {cellBreakdown.map((b) => {
              const ratio = b.success / b.total;
              const isWeak = b.diff != null && b.diff < 0;
              return (
                <div
                  key={`${b.cell.delta_idx},${b.cell.t_idx}`}
                  className={
                    'p-3 rounded-lg border ' +
                    (isWeak ? 'border-red-500/40 bg-red-900/10' : 'border-slate-700 bg-slate-900/50')
                  }
                >
                  <div className="text-white text-sm font-semibold mb-1">
                    {b.cell.delta_label} cp · {b.cell.t_label} moves
                  </div>
                  <div className="text-xs text-slate-400 mb-2">
                    {b.success}/{b.total} solved
                    {b.diff != null && (
                      <span className={'ml-2 ' + (b.diff < 0 ? 'text-red-300' : 'text-emerald-300')}>
                        ({b.diff > 0 ? '+' : ''}{Math.round(b.diff)}% vs field)
                      </span>
                    )}
                  </div>
                  <div className="w-full h-2 bg-slate-800 rounded-full overflow-hidden">
                    <div
                      className={ratio === 1 ? 'h-2 bg-emerald-500' : ratio > 0 ? 'h-2 bg-amber-500' : 'h-2 bg-red-500'}
                      style={{ width: `${ratio * 100}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Improvement suggestion */}
        {(() => {
          const weakCells = cellBreakdown
            .filter(b => b.diff != null && b.diff < 0)
            .sort((a, b) => (a.diff ?? 0) - (b.diff ?? 0));
          if (weakCells.length === 0) return null;
          return (
            <div className="bg-slate-900/50 p-4 rounded-lg border border-amber-500/40 mb-6">
              <div className="text-amber-300 font-semibold mb-2">Areas to keep training</div>
              <ul className="text-slate-300 text-sm space-y-1">
                {weakCells.slice(0, 3).map((b) => (
                  <li key={`${b.cell.delta_idx},${b.cell.t_idx}`}>
                    • <span className="text-white">{b.cell.delta_label} cp · {b.cell.t_label} moves</span> —
                    {' '}{Math.round(-(b.diff ?? 0))}% below the {eloRangeLabel} field
                    {' '}({b.success}/{b.total} solved this round)
                  </li>
                ))}
              </ul>
            </div>
          );
        })()}

        {/* Per-puzzle list */}
        <div className="mb-6">
          <h3 className="text-lg font-semibold text-slate-300 mb-3">Per-puzzle</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-slate-700">
                <tr>
                  <th className="p-2 text-left text-slate-300">#</th>
                  <th className="p-2 text-left text-slate-300">Result</th>
                  <th className="p-2 text-left text-slate-300">Cell</th>
                  <th className="p-2 text-left text-slate-300">Opponent's mistake</th>
                  <th className="p-2 text-left text-slate-300">Best reply</th>
                  <th className="p-2 text-left text-slate-300">Game</th>
                  <th className="p-2 text-left text-slate-300">Action</th>
                </tr>
              </thead>
              <tbody>
                {results.map((r, i) => (
                  <tr
                    key={i}
                    className={
                      'border-t border-slate-700 ' +
                      (r.status === 'success' ? 'bg-emerald-950/20' : 'bg-red-950/20')
                    }
                  >
                    <td className="p-2 text-slate-300">{i + 1}</td>
                    <td className="p-2">
                      {r.status === 'success' ? (
                        <span className="inline-flex items-center gap-1 text-emerald-300">
                          <CheckCircle2 className="w-4 h-4" /> Solved
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-red-300">
                          <XCircle className="w-4 h-4" /> Failed
                        </span>
                      )}
                    </td>
                    <td className="p-2 text-slate-200 text-xs">
                      {r.puzzle.cell.delta_label} cp · {r.puzzle.cell.t_label}
                    </td>
                    <td className="p-2 text-white font-mono">{r.puzzle.move_san}</td>
                    <td className="p-2 text-white font-mono">{r.puzzle.best_move_san}</td>
                    <td className="p-2">
                      <a
                        href={r.puzzle.game_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-indigo-400 hover:text-indigo-300 underline"
                      >
                        view
                      </a>
                    </td>
                    <td className="p-2">
                      <button
                        onClick={() => setReviewing(reviewing === i ? null : i)}
                        className="inline-flex items-center gap-1 text-fuchsia-300 hover:text-fuchsia-200"
                      >
                        <Eye className="w-4 h-4" />
                        {reviewing === i ? 'Hide' : 'Solution'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Inline solution viewer */}
        {reviewing != null && results[reviewing] && (
          <div className="mb-6">
            <ChessBoardViewer error={puzzleToErrorEvent(results[reviewing].puzzle)} />
          </div>
        )}

        <div className="flex gap-3">
          <button
            onClick={beginSet}
            className="bg-fuchsia-600 hover:bg-fuchsia-700 text-white px-6 py-3 rounded-lg font-semibold transition-colors flex items-center gap-2"
          >
            <RefreshCw className="w-5 h-5" />
            Try another set of 10
          </button>
          <button
            onClick={() => { setPhase('idle'); setResults([]); setReviewing(null); setTactics(null); }}
            className="bg-slate-700 hover:bg-slate-600 text-white px-6 py-3 rounded-lg font-semibold transition-colors flex items-center gap-2"
          >
            <ChevronRight className="w-5 h-5" />
            Done
          </button>
        </div>
      </div>
    );
  }

  return null;
};

export default TrainingTactics;

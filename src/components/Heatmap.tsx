import React, { useState } from 'react';
import type { HistogramData, ErrorEvent } from '../types';

interface HeatmapProps {
  histogram: HistogramData;
  errors: ErrorEvent[];
  onCellClick?: (deltaIdx: number, tIdx: number, events: ErrorEvent[]) => void;
  onMoveClick?: (error: ErrorEvent) => void;
  viewMode: 'count' | 'percentage';
  onViewModeChange: (mode: 'count' | 'percentage') => void;
}

export const isExcludedError = (error: ErrorEvent): boolean => {
  const isMate = error.opportunity_kind === 'mate';
  const inLowDelta = !isMate && error.delta_cp >= 100 && error.delta_cp <= 299;
  const inHighMoves = error.t_plies >= 8;
  return inLowDelta && inHighMoves;
};

const isExcludedCell = (deltaIdx: number, tIdx: number): boolean => {
  return deltaIdx === 0 && tIdx === 2;
};

const Heatmap: React.FC<HeatmapProps> = ({ histogram, errors, onCellClick, onMoveClick, viewMode, onViewModeChange }) => {
  const { delta_bins, t_bins } = histogram;
  const [hoveredCell, setHoveredCell] = useState<{deltaIdx: number; tIdx: number} | null>(null);
  const [tooltipPos, setTooltipPos] = useState<{x: number; y: number}>({x: 0, y: 0});

  const missedErrors = errors.filter(e => e.converted_actual === 0);

  const inTBin = (tLabel: string, t: number): boolean => {
    if (tLabel === '1-3') return t >= 1 && t <= 3;
    if (tLabel === '5-7') return t >= 4 && t <= 7;
    if (tLabel === '9+') return t >= 8;
    return false;
  };

  const inDeltaBin = (deltaLabel: string, delta: number, isMate: boolean): boolean => {
    if (deltaLabel === '800+') return isMate || delta >= 800;
    if (isMate) return false;
    if (deltaLabel === '100-299') return delta >= 100 && delta <= 299;
    if (deltaLabel === '300-799') return delta >= 300 && delta <= 799;
    return false;
  };

  const getErrorsForCell = (deltaIdx: number, tIdx: number, errorList: ErrorEvent[]): ErrorEvent[] => {
    const deltaLabel = delta_bins[deltaIdx];
    const tLabel = t_bins[tIdx];
    return errorList.filter(error => {
      const isMate = error.opportunity_kind === 'mate';
      return inDeltaBin(deltaLabel, error.delta_cp, isMate) && inTBin(tLabel, error.t_plies);
    });
  };

  const getCellData = (deltaIdx: number, tIdx: number): { display: string; count: number } => {
    if (isExcludedCell(deltaIdx, tIdx)) return { display: '', count: 0 };
    const missedInCell = getErrorsForCell(deltaIdx, tIdx, missedErrors);
    const totalInCell = getErrorsForCell(deltaIdx, tIdx, errors);

    if (viewMode === 'count') {
      return { display: missedInCell.length.toString(), count: missedInCell.length };
    }
    if (totalInCell.length === 0) return { display: '0%', count: 0 };
    const percentage = (missedInCell.length / totalInCell.length) * 100;
    return { display: `${Math.round(percentage)}%`, count: Math.round(percentage) };
  };

  const allCellData = delta_bins.flatMap((_, di) =>
    t_bins.map((_, ti) => getCellData(di, ti).count)
  );
  const maxCount = Math.max(...allCellData, 1);

  const interpolateColor = (c1: number[], c2: number[], f: number): string => {
    const r = Math.round(c1[0] + (c2[0] - c1[0]) * f);
    const g = Math.round(c1[1] + (c2[1] - c1[1]) * f);
    const b = Math.round(c1[2] + (c2[2] - c1[2]) * f);
    return `rgb(${r}, ${g}, ${b})`;
  };

  const getColor = (count: number): string => {
    if (maxCount === 0) return 'rgb(51, 65, 85)';
    const intensity = count / maxCount;
    const colorStops = [
      [51, 65, 85], [71, 85, 105], [99, 102, 241],
      [139, 92, 246], [236, 72, 153], [239, 68, 68]
    ];
    const stopPositions = [0, 0.15, 0.3, 0.5, 0.7, 1.0];
    for (let i = 0; i < stopPositions.length - 1; i++) {
      if (intensity <= stopPositions[i + 1]) {
        const f = (intensity - stopPositions[i]) / (stopPositions[i + 1] - stopPositions[i]);
        return interpolateColor(colorStops[i], colorStops[i + 1], f);
      }
    }
    return `rgb(${colorStops[colorStops.length - 1].join(', ')})`;
  };

  const handleCellClick = (deltaIdx: number, tIdx: number) => {
    if (isExcludedCell(deltaIdx, tIdx)) return;
    const allInCell = getErrorsForCell(deltaIdx, tIdx, errors);
    if (onCellClick && allInCell.length > 0) {
      onCellClick(deltaIdx, tIdx, allInCell);
    }
  };

  const handleCellHover = (deltaIdx: number, tIdx: number, event: React.MouseEvent) => {
    setHoveredCell({ deltaIdx, tIdx });
    setTooltipPos({ x: event.clientX, y: event.clientY });
  };

  const reversedDeltaIndices = [...Array(delta_bins.length).keys()].reverse();

  return (
    <div className="relative">
      <div className="mb-4 flex items-center gap-3">
        <label className="text-slate-300 text-sm font-medium">View:</label>
        <div className="inline-flex rounded-lg border border-slate-600 overflow-hidden">
          <button
            onClick={() => onViewModeChange('percentage')}
            className={`px-4 py-2 text-sm font-medium transition-colors ${
              viewMode === 'percentage' ? 'bg-indigo-600 text-white' : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
            }`}
          >%</button>
          <button
            onClick={() => onViewModeChange('count')}
            className={`px-4 py-2 text-sm font-medium transition-colors border-l border-slate-600 ${
              viewMode === 'count' ? 'bg-indigo-600 text-white' : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
            }`}
          >Count</button>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="border-collapse">
          <tbody>
            {reversedDeltaIndices.map((deltaIdx) => (
              <tr key={deltaIdx}>
                <td className="p-2 text-slate-300 text-xs border border-slate-700 font-medium whitespace-nowrap">
                  {`${delta_bins[deltaIdx]} cp`}
                </td>
                {t_bins.map((_tBin, tIdx) => {
                  const excluded = isExcludedCell(deltaIdx, tIdx);

                  if (excluded) {
                    return (
                      <td
                        key={tIdx}
                        className="p-4 border border-slate-700 text-center relative"
                        style={{ backgroundColor: 'rgb(51, 65, 85)', minWidth: 80, minHeight: 48 }}
                        onMouseEnter={(e) => handleCellHover(deltaIdx, tIdx, e)}
                        onMouseLeave={() => setHoveredCell(null)}
                      >
                        <svg
                          className="absolute inset-0 w-full h-full pointer-events-none"
                          preserveAspectRatio="none"
                          viewBox="0 0 100 100"
                        >
                          <line x1="0" y1="100" x2="100" y2="0" stroke="#64748b" strokeWidth="2" />
                        </svg>
                      </td>
                    );
                  }

                  const cellData = getCellData(deltaIdx, tIdx);
                  const color = getColor(cellData.count);
                  return (
                    <td
                      key={tIdx}
                      className="p-4 border border-slate-700 text-center cursor-pointer hover:opacity-80 transition-opacity relative"
                      style={{ backgroundColor: color }}
                      onClick={() => handleCellClick(deltaIdx, tIdx)}
                      onMouseEnter={(e) => handleCellHover(deltaIdx, tIdx, e)}
                      onMouseLeave={() => setHoveredCell(null)}
                    >
                      <span className="text-white font-semibold text-sm">
                        {cellData.count > 0 ? cellData.display : ''}
                      </span>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th className="p-2 text-slate-400 text-xs border border-slate-700"></th>
              {t_bins.map((bin, idx) => (
                <th key={idx} className="p-2 text-slate-300 text-xs border border-slate-700 min-w-[80px]">
                  {bin} moves
                </th>
              ))}
            </tr>
          </tfoot>
        </table>
      </div>

      {hoveredCell && (() => {
        if (isExcludedCell(hoveredCell.deltaIdx, hoveredCell.tIdx)) {
          return (
            <div
              className="fixed z-50 bg-slate-800 border border-slate-600 rounded-lg shadow-xl p-4 max-w-xs pointer-events-none"
              style={{ left: tooltipPos.x + 15, top: tooltipPos.y + 15 }}
            >
              <div className="text-slate-300 text-sm">
                Low-signal missed opportunities excluded from analysis
              </div>
            </div>
          );
        }
        const missed = getErrorsForCell(hoveredCell.deltaIdx, hoveredCell.tIdx, missedErrors);
        const total = getErrorsForCell(hoveredCell.deltaIdx, hoveredCell.tIdx, errors);
        const missRate = total.length > 0 ? Math.round((missed.length / total.length) * 100) : 0;
        return (
          <div
            className="fixed z-50 bg-slate-800 border border-slate-600 rounded-lg shadow-xl p-4 max-w-md pointer-events-none"
            style={{ left: tooltipPos.x + 15, top: tooltipPos.y + 15 }}
          >
            <div className="text-white font-semibold mb-1">Missed Opportunities</div>
            <div className="text-slate-400 text-xs mb-3">
              {missed.length} missed / {total.length} total ({missRate}% miss rate)
            </div>
            <div className="max-h-64 overflow-y-auto">
              {missed.map((error, idx) => (
                <div key={idx} className="py-2 border-b border-slate-700 last:border-0 hover:bg-slate-700 cursor-pointer rounded px-2"
                  onClick={() => onMoveClick && onMoveClick(error)}>
                  <div className="flex justify-between items-center">
                    <span className="text-slate-200 font-mono">{error.move_san}</span>
                    <span className="text-green-400 text-sm">+{error.delta_cp}cp</span>
                  </div>
                  <div className="text-slate-400 text-xs mt-1">Move {error.ply_index + 1}</div>
                </div>
              ))}
            </div>
          </div>
        );
      })()}
    </div>
  );
};

export default Heatmap;

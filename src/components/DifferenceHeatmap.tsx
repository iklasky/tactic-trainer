import React from 'react';
import type { HistogramData, ErrorEvent } from '../types';

interface DifferenceHeatmapProps {
  playerHistogram: HistogramData;
  playerErrors: ErrorEvent[];
  fieldHistogram: HistogramData;
  fieldErrors: ErrorEvent[];
}

const DifferenceHeatmap: React.FC<DifferenceHeatmapProps> = ({ 
  playerHistogram, 
  playerErrors, 
  fieldHistogram, 
  fieldErrors 
}) => {
  const { delta_bins, t_bins } = playerHistogram;
  
  // Filter to only missed opportunities
  const playerMissed = playerErrors.filter(e => e.converted_actual === 0);
  const fieldMissed = fieldErrors.filter(e => e.converted_actual === 0);
  
  const inTBin = (tLabel: string, t: number): boolean => {
    if (tLabel === '1-3') return t >= 1 && t <= 3;
    if (tLabel === '5-7') return t >= 4 && t <= 7;
    if (tLabel === '9-15') return t >= 8 && t <= 15;
    if (tLabel === '17+') return t >= 16;
    return false;
  };

  const inDeltaBin = (deltaLabel: string, delta: number, isMate: boolean): boolean => {
    if (deltaLabel === '800+') return isMate || delta >= 800;
    if (isMate) return false;
    if (deltaLabel === '100-299') return delta >= 100 && delta <= 299;
    if (deltaLabel === '300-499') return delta >= 300 && delta <= 499;
    if (deltaLabel === '500-799') return delta >= 500 && delta <= 799;
    return false;
  };
  
  const getErrorsForCell = (deltaIdx: number, tIdx: number, errorList: ErrorEvent[]): ErrorEvent[] => {
    const deltaLabel = delta_bins[deltaIdx];
    const tLabel = t_bins[tIdx];

    return errorList.filter(error => {
      const delta = error.delta_cp;
      const t = error.t_plies;
      const isMate = error.opportunity_kind === 'mate';
      return inDeltaBin(deltaLabel, delta, isMate) && inTBin(tLabel, t);
    });
  };
  
  // Calculate percentage difference for a cell
  const getCellDifference = (deltaIdx: number, tIdx: number): { diff: number; hasData: boolean } => {
    const playerMissedInCell = getErrorsForCell(deltaIdx, tIdx, playerMissed);
    const playerTotalInCell = getErrorsForCell(deltaIdx, tIdx, playerErrors);
    const fieldMissedInCell = getErrorsForCell(deltaIdx, tIdx, fieldMissed);
    const fieldTotalInCell = getErrorsForCell(deltaIdx, tIdx, fieldErrors);
    
    if (playerTotalInCell.length === 0 && fieldTotalInCell.length === 0) {
      return { diff: 0, hasData: false };
    }
    
    const playerPct = playerTotalInCell.length > 0 
      ? (playerMissedInCell.length / playerTotalInCell.length) * 100 
      : 0;
    const fieldPct = fieldTotalInCell.length > 0 
      ? (fieldMissedInCell.length / fieldTotalInCell.length) * 100 
      : 0;
    
    // Negative = player is worse (misses more), Positive = player is better (misses less)
    return { diff: fieldPct - playerPct, hasData: true };
  };
  
  // Diverging color scale: red (worse) -> white (neutral) -> green (better)
  const getColor = (diff: number, hasData: boolean): string => {
    if (!hasData) return 'rgb(30, 41, 59)'; // slate-800 (darker for no data)
    
    // Clamp to -50 to +50 range for color scaling
    const clampedDiff = Math.max(-50, Math.min(50, diff));
    const intensity = Math.abs(clampedDiff) / 50;
    
    if (clampedDiff < 0) {
      // Worse than average (player misses more) - Red scale
      const r = Math.round(51 + (239 - 51) * intensity);  // slate-700 -> red-500
      const g = Math.round(65 + (68 - 65) * intensity);
      const b = Math.round(85 + (68 - 85) * intensity);
      return `rgb(${r}, ${g}, ${b})`;
    } else if (clampedDiff > 0) {
      // Better than average (player misses less) - Green scale
      const r = Math.round(51 + (34 - 51) * intensity);   // slate-700 -> green-500
      const g = Math.round(65 + (197 - 65) * intensity);
      const b = Math.round(85 + (94 - 85) * intensity);
      return `rgb(${r}, ${g}, ${b})`;
    } else {
      // Exactly average - slate-700
      return 'rgb(51, 65, 85)';
    }
  };
  
  return (
    <div className="relative">
      {/* Heatmap Table */}
      <div className="overflow-x-auto">
        <table className="border-collapse mx-auto">
          <thead>
            <tr>
              <th className="p-2 text-slate-400 text-xs border border-slate-700"></th>
              {t_bins.map((bin, idx) => (
                <th key={idx} className="p-2 text-slate-300 text-xs border border-slate-700 min-w-[80px]">
                  {bin} moves
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {delta_bins.map((deltaBin, deltaIdx) => (
              <tr key={deltaIdx}>
                <td className="p-2 text-slate-300 text-xs border border-slate-700 font-medium whitespace-nowrap">
                  {`${deltaBin} cp`}
                </td>
                {t_bins.map((_tBin, tIdx) => {
                  const { diff, hasData } = getCellDifference(deltaIdx, tIdx);
                  const color = getColor(diff, hasData);
                  const displayText = hasData ? `${diff > 0 ? '+' : ''}${Math.round(diff)}%` : '';
                  
                  return (
                    <td
                      key={tIdx}
                      className="p-4 border border-slate-700 text-center relative"
                      style={{ backgroundColor: color }}
                    >
                      <span className="text-white font-semibold text-sm">
                        {displayText}
                      </span>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default DifferenceHeatmap;


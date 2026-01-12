import React, { useState } from 'react';
import type { HistogramData, ErrorEvent } from '../types';

interface HeatmapProps {
  histogram: HistogramData;
  errors: ErrorEvent[];
  onCellClick?: (deltaIdx: number, tIdx: number, events: ErrorEvent[]) => void;
  onMoveClick?: (error: ErrorEvent) => void;
}

const Heatmap: React.FC<HeatmapProps> = ({ histogram, errors, onCellClick, onMoveClick }) => {
  const { delta_bins, t_bins, counts } = histogram;
  const [hoveredCell, setHoveredCell] = useState<{deltaIdx: number; tIdx: number} | null>(null);
  const [tooltipPos, setTooltipPos] = useState<{x: number; y: number}>({x: 0, y: 0});
  
  // Find max count for color scaling
  const maxCount = Math.max(...counts.flat());
  
  // Helper function to interpolate between two RGB colors
  const interpolateColor = (color1: number[], color2: number[], factor: number): string => {
    const r = Math.round(color1[0] + (color2[0] - color1[0]) * factor);
    const g = Math.round(color1[1] + (color2[1] - color1[1]) * factor);
    const b = Math.round(color1[2] + (color2[2] - color1[2]) * factor);
    return `rgb(${r}, ${g}, ${b})`;
  };
  
  // Continuous color scale function with smooth interpolation
  const getColor = (count: number): string => {
    if (maxCount === 0) return 'rgb(51, 65, 85)'; // slate-700
    
    const intensity = count / maxCount;
    
    // Define color stops: [R, G, B]
    const colorStops = [
      [51, 65, 85],      // 0% - slate-700 (dark but visible)
      [71, 85, 105],     // 15% - slate-600
      [99, 102, 241],    // 30% - indigo-500
      [139, 92, 246],    // 50% - violet-500
      [236, 72, 153],    // 70% - pink-500
      [239, 68, 68]      // 100% - red-500
    ];
    
    const stopPositions = [0, 0.15, 0.3, 0.5, 0.7, 1.0];
    
    // Find which two colors to interpolate between
    for (let i = 0; i < stopPositions.length - 1; i++) {
      if (intensity <= stopPositions[i + 1]) {
        const rangeStart = stopPositions[i];
        const rangeEnd = stopPositions[i + 1];
        const rangeSize = rangeEnd - rangeStart;
        const positionInRange = (intensity - rangeStart) / rangeSize;
        
        return interpolateColor(colorStops[i], colorStops[i + 1], positionInRange);
      }
    }
    
    // Fallback to the last color
    return `rgb(${colorStops[colorStops.length - 1].join(', ')})`;
  };
  
  // Get delta bounds from label
  const getDeltaBounds = (label: string): [number, number] => {
    if (label === '800+') return [800, Infinity];
    const [min, max] = label.split('-').map(Number);
    return [min, max];
  };
  
  // Get t bounds from label
  const getTBounds = (label: string): [number, number] => {
    if (label === '32+') return [32, Infinity];
    const [min, max] = label.split('-').map(Number);
    return [min, max];
  };
  
  // Get errors for a specific cell
  const getErrorsForCell = (deltaIdx: number, tIdx: number): ErrorEvent[] => {
    const deltaLabel = delta_bins[deltaIdx];
    const tLabel = t_bins[tIdx];
    
    const [deltaMin, deltaMax] = getDeltaBounds(deltaLabel);
    const [tMin, tMax] = getTBounds(tLabel);
    
    return errors.filter(error => {
      const delta = error.delta_cp;
      const t = error.t_plies;
      
      return delta >= deltaMin && delta < deltaMax && 
             t >= tMin && t < tMax;
    });
  };
  
  const handleCellClick = (deltaIdx: number, tIdx: number) => {
    const cellErrors = getErrorsForCell(deltaIdx, tIdx);
    if (onCellClick && cellErrors.length > 0) {
      onCellClick(deltaIdx, tIdx, cellErrors);
    }
  };
  
  const handleCellHover = (deltaIdx: number, tIdx: number, event: React.MouseEvent) => {
    setHoveredCell({ deltaIdx, tIdx });
    setTooltipPos({ x: event.clientX, y: event.clientY });
  };
  
  const handleCellLeave = () => {
    setHoveredCell(null);
  };
  
  return (
    <div className="relative">
      {/* Heatmap Table */}
      <div className="overflow-x-auto">
        <table className="border-collapse">
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
                  {deltaBin} cp
                </td>
                {t_bins.map((tBin, tIdx) => {
                  const count = counts[deltaIdx][tIdx];
                  const color = getColor(count);
                  
                  return (
                    <td
                      key={tIdx}
                      className="p-4 border border-slate-700 text-center cursor-pointer hover:opacity-80 transition-opacity relative"
                      style={{ backgroundColor: color }}
                      onClick={() => handleCellClick(deltaIdx, tIdx)}
                      onMouseEnter={(e) => handleCellHover(deltaIdx, tIdx, e)}
                      onMouseLeave={handleCellLeave}
                    >
                      <span className="text-white font-semibold text-sm">
                        {count > 0 ? count : ''}
                      </span>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      
      {/* Legend - Continuous Gradient */}
      <div className="mt-6">
        <div className="flex items-center gap-4">
          <span className="text-slate-400 text-sm">Opportunity Frequency:</span>
          <div className="flex items-center gap-2 flex-1 max-w-md">
            <span className="text-slate-400 text-xs">Low</span>
            <div 
              className="h-6 flex-1 rounded"
              style={{
                background: 'linear-gradient(to right, rgb(51, 65, 85), rgb(71, 85, 105), rgb(99, 102, 241), rgb(139, 92, 246), rgb(236, 72, 153), rgb(239, 68, 68))'
              }}
            ></div>
            <span className="text-slate-400 text-xs">High</span>
          </div>
        </div>
      </div>
      
      {/* Custom Tooltip */}
      {hoveredCell && (
        <div
          className="fixed z-50 bg-slate-800 border border-slate-600 rounded-lg shadow-xl p-4 max-w-md pointer-events-none"
          style={{
            left: tooltipPos.x + 15,
            top: tooltipPos.y + 15,
          }}
        >
          <div className="text-white font-semibold mb-2">Missed Opportunities</div>
          <div className="max-h-64 overflow-y-auto">
            {getErrorsForCell(hoveredCell.deltaIdx, hoveredCell.tIdx).map((error, idx) => (
              <div 
                key={idx} 
                className="py-2 border-b border-slate-700 last:border-0 hover:bg-slate-700 cursor-pointer rounded px-2"
                onClick={() => onMoveClick && onMoveClick(error)}
              >
                <div className="flex justify-between items-center">
                  <span className="text-slate-200 font-mono">{error.move_san}</span>
                  <span className="text-green-400 text-sm">+{error.delta_cp}cp</span>
                </div>
                <div className="text-slate-400 text-xs mt-1">
                  Move {error.ply_index + 1}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default Heatmap;


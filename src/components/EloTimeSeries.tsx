import React, { useMemo, useState, useCallback } from 'react';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import type { GameWithMoves } from '../types';

interface Props {
  gamesWithMoves: GameWithMoves[];
}

const GAME_TYPE_COLORS: Record<string, string> = {
  bullet: '#ef4444',
  blitz: '#f59e0b',
  rapid: '#34d399',
  classical: '#818cf8',
  daily: '#ec4899',
  unknown: '#94a3b8',
};

function classifyTimeControl(tc?: string): string {
  if (!tc) return 'unknown';
  const parts = tc.split('+');
  const base = parseInt(parts[0], 10);
  if (isNaN(base)) return 'unknown';
  const inc = parts.length > 1 ? parseInt(parts[1], 10) : 0;
  const total = base + 40 * inc;
  if (total < 180) return 'bullet';
  if (total < 600) return 'blitz';
  if (total < 1800) return 'rapid';
  if (tc.includes('/')) return 'daily';
  return 'classical';
}

const EloTimeSeries: React.FC<Props> = ({ gamesWithMoves }) => {
  const [hiddenTypes, setHiddenTypes] = useState<Set<string>>(new Set());

  const { chartData, gameTypes, minElo, maxElo } = useMemo(() => {
    if (!gamesWithMoves || gamesWithMoves.length === 0)
      return { chartData: [], gameTypes: [], minElo: 0, maxElo: 0 };

    const sorted = [...gamesWithMoves]
      .filter(g => g.player_elo != null)
      .sort((a, b) => new Date(a.end_time).getTime() - new Date(b.end_time).getTime());

    if (sorted.length < 2)
      return { chartData: [], gameTypes: [], minElo: 0, maxElo: 0 };

    const typesSet = new Set<string>();
    let lo = Infinity, hi = -Infinity;

    const data = sorted.map((g, i) => {
      const gt = classifyTimeControl(g.time_control);
      typesSet.add(gt);
      const elo = g.player_elo!;
      lo = Math.min(lo, elo);
      hi = Math.max(hi, elo);
      let dateStr = '';
      try { dateStr = new Date(g.end_time).toLocaleDateString(); } catch { dateStr = g.end_time; }
      const point: Record<string, any> = { index: i, date: dateStr };
      point[gt] = elo;
      return point;
    });

    const typesArr = Array.from(typesSet).sort();
    return { chartData: data, gameTypes: typesArr, minElo: lo, maxElo: hi };
  }, [gamesWithMoves]);

  const handleLegendClick = useCallback((dataKey: string) => {
    setHiddenTypes(prev => {
      const next = new Set(prev);
      if (next.has(dataKey)) next.delete(dataKey);
      else next.add(dataKey);
      return next;
    });
  }, []);

  if (chartData.length < 2) return null;

  const padding = Math.max(50, Math.round((maxElo - minElo) * 0.1));

  const tickInterval = Math.max(1, Math.floor(chartData.length / 6));

  return (
    <div className="bg-slate-800 p-6 rounded-lg shadow-lg mb-8">
      <h2 className="text-2xl font-bold text-white mb-2">ELO Rating Over Time</h2>
      <p className="text-sm text-slate-400 mb-6">
        Rating progression across analyzed games — click legend to toggle
      </p>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={chartData} margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
          <XAxis
            dataKey="index"
            type="number"
            domain={[0, chartData.length - 1]}
            tick={{ fill: '#94a3b8', fontSize: 11 }}
            tickLine={{ stroke: '#475569' }}
            axisLine={{ stroke: '#475569' }}
            ticks={Array.from({ length: Math.ceil(chartData.length / tickInterval) }, (_, i) => {
              const idx = i * tickInterval;
              return idx < chartData.length ? idx : chartData.length - 1;
            }).filter((v, i, a) => a.indexOf(v) === i)}
            tickFormatter={(idx: number) => chartData[idx]?.date || ''}
          />
          <YAxis
            tick={{ fill: '#94a3b8', fontSize: 11 }}
            tickLine={{ stroke: '#475569' }}
            axisLine={{ stroke: '#475569' }}
            domain={[minElo - padding, maxElo + padding]}
          />
          <Tooltip
            contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #475569', borderRadius: '8px' }}
            labelStyle={{ color: '#f1f5f9' }}
            formatter={(value: any, name: any) => [value, name]}
            labelFormatter={(_label: any, payload: any) => {
              if (payload && payload.length > 0) return payload[0].payload.date;
              return String(_label);
            }}
          />
          <Legend
            onClick={(e: any) => handleLegendClick(e.dataKey)}
            formatter={(value: string) => (
              <span style={{ color: hiddenTypes.has(value) ? '#475569' : GAME_TYPE_COLORS[value] || '#94a3b8', cursor: 'pointer' }}>
                {value}
              </span>
            )}
          />
          {gameTypes.map(gt => (
            <Line
              key={gt}
              type="monotone"
              dataKey={gt}
              stroke={GAME_TYPE_COLORS[gt] || '#94a3b8'}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4 }}
              connectNulls
              hide={hiddenTypes.has(gt)}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
};

export default EloTimeSeries;

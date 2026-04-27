import React, { useMemo, useState, useCallback } from 'react';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import type { GameWithMoves } from '../types';

interface Props {
  gamesWithMoves: GameWithMoves[];
}

// One color per (variant × time class) combination. We compose them as
// `variant_timeclass`, e.g. "chess_blitz", "chess960_blitz", "bughouse_bullet".
// Anything not pre-mapped falls back to a deterministic gray.
const SERIES_COLORS: Record<string, string> = {
  // Standard chess
  chess_bullet:    '#ef4444',
  chess_blitz:     '#f59e0b',
  chess_rapid:     '#34d399',
  chess_classical: '#818cf8',
  chess_daily:     '#ec4899',
  // Chess960
  chess960_bullet:    '#fb7185',
  chess960_blitz:     '#fbbf24',
  chess960_rapid:     '#4ade80',
  chess960_classical: '#a78bfa',
  chess960_daily:     '#f472b6',
  // Other variants — single color per variant, time-class shade ignored visually
  bughouse_bullet:    '#22d3ee',
  bughouse_blitz:     '#22d3ee',
  bughouse_rapid:     '#22d3ee',
  kingofthehill_bullet:    '#facc15',
  kingofthehill_blitz:     '#facc15',
  kingofthehill_rapid:     '#facc15',
  crazyhouse_bullet:  '#fde047',
  crazyhouse_blitz:   '#fde047',
  crazyhouse_rapid:   '#fde047',
  threecheck_bullet:  '#a3e635',
  threecheck_blitz:   '#a3e635',
  threecheck_rapid:   '#a3e635',
  oddschess_bullet:   '#fb923c',
  oddschess_blitz:    '#fb923c',
  oddschess_rapid:    '#fb923c',
};

const FALLBACK_COLORS = [
  '#94a3b8', '#a78bfa', '#fb923c', '#f472b6', '#22d3ee',
  '#84cc16', '#fbbf24', '#fb7185', '#60a5fa', '#fde047',
];

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

function makeSeriesKey(rules: string | undefined, tc: string | undefined): string {
  const variant = (rules || 'chess').toLowerCase();
  return `${variant}_${classifyTimeControl(tc)}`;
}

// Pretty-print a series key for the legend / tooltip.
function formatSeriesLabel(key: string): string {
  const [variant, klass] = key.split('_');
  const variantLabel = variant === 'chess'
    ? 'Standard'
    : variant.charAt(0).toUpperCase() + variant.slice(1);
  const klassLabel = klass.charAt(0).toUpperCase() + klass.slice(1);
  return `${variantLabel} · ${klassLabel}`;
}

const EloTimeSeries: React.FC<Props> = ({ gamesWithMoves }) => {
  const [hiddenSeries, setHiddenSeries] = useState<Set<string>>(new Set());

  const { chartData, seriesKeys, colorFor, minElo, maxElo } = useMemo(() => {
    const empty = {
      chartData: [] as Record<string, any>[],
      seriesKeys: [] as string[],
      colorFor: (_k: string) => '#94a3b8',
      minElo: 0,
      maxElo: 0,
    };
    if (!gamesWithMoves || gamesWithMoves.length === 0) return empty;

    const sorted = [...gamesWithMoves]
      .filter(g => g.player_elo != null)
      .sort((a, b) => new Date(a.end_time).getTime() - new Date(b.end_time).getTime());

    if (sorted.length < 2) return empty;

    const seriesSet = new Set<string>();
    let lo = Infinity, hi = -Infinity;

    const data = sorted.map((g, i) => {
      const key = makeSeriesKey(g.rules, g.time_control);
      seriesSet.add(key);
      const elo = g.player_elo!;
      lo = Math.min(lo, elo);
      hi = Math.max(hi, elo);
      let dateStr = '';
      try { dateStr = new Date(g.end_time).toLocaleDateString(); } catch { dateStr = g.end_time; }
      const point: Record<string, any> = { index: i, date: dateStr };
      point[key] = elo;
      return point;
    });

    const seriesArr = Array.from(seriesSet).sort();
    const fallbackColors = new Map<string, string>();
    let nextFallback = 0;
    const colorFor = (k: string): string => {
      if (SERIES_COLORS[k]) return SERIES_COLORS[k];
      if (!fallbackColors.has(k)) {
        fallbackColors.set(k, FALLBACK_COLORS[nextFallback % FALLBACK_COLORS.length]);
        nextFallback += 1;
      }
      return fallbackColors.get(k)!;
    };

    return { chartData: data, seriesKeys: seriesArr, colorFor, minElo: lo, maxElo: hi };
  }, [gamesWithMoves]);

  const handleLegendClick = useCallback((dataKey: string) => {
    setHiddenSeries(prev => {
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
        Rating progression across analyzed games — split by variant and time control. Click legend to toggle.
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
            formatter={(value: any, name: any) => [value, formatSeriesLabel(String(name))]}
            labelFormatter={(_label: any, payload: any) => {
              if (payload && payload.length > 0) return payload[0].payload.date;
              return String(_label);
            }}
          />
          <Legend
            onClick={(e: any) => handleLegendClick(e.dataKey)}
            formatter={(value: string) => (
              <span style={{
                color: hiddenSeries.has(value) ? '#475569' : colorFor(value),
                cursor: 'pointer',
              }}>
                {formatSeriesLabel(value)}
              </span>
            )}
          />
          {seriesKeys.map(key => (
            <Line
              key={key}
              type="monotone"
              dataKey={key}
              stroke={colorFor(key)}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4 }}
              connectNulls
              hide={hiddenSeries.has(key)}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
};

export default EloTimeSeries;

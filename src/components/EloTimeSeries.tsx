import React, { useMemo } from 'react';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import type { GameWithMoves } from '../types';

interface Props {
  gamesWithMoves: GameWithMoves[];
}

const EloTimeSeries: React.FC<Props> = ({ gamesWithMoves }) => {
  const data = useMemo(() => {
    if (!gamesWithMoves || gamesWithMoves.length === 0) return [];

    const sorted = [...gamesWithMoves]
      .filter(g => g.player_elo != null)
      .sort((a, b) => new Date(a.end_time).getTime() - new Date(b.end_time).getTime());

    return sorted.map((g, i) => {
      let dateStr = '';
      try {
        dateStr = new Date(g.end_time).toLocaleDateString();
      } catch {
        dateStr = g.end_time;
      }
      return {
        index: i,
        date: dateStr,
        elo: g.player_elo!,
      };
    });
  }, [gamesWithMoves]);

  if (data.length < 2) return null;

  const minElo = Math.min(...data.map(d => d.elo));
  const maxElo = Math.max(...data.map(d => d.elo));
  const padding = Math.max(50, Math.round((maxElo - minElo) * 0.1));

  return (
    <div className="bg-slate-800 p-6 rounded-lg shadow-lg mb-8">
      <h2 className="text-2xl font-bold text-white mb-2">ELO Rating Over Time</h2>
      <p className="text-sm text-slate-400 mb-6">
        Rating progression across analyzed games (chronological order)
      </p>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={data} margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
          <XAxis
            dataKey="date"
            tick={{ fill: '#94a3b8', fontSize: 11 }}
            tickLine={{ stroke: '#475569' }}
            axisLine={{ stroke: '#475569' }}
            interval="preserveStartEnd"
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
            formatter={(value: any) => [value, 'ELO']}
            labelFormatter={(_label: any, payload: any) => {
              if (payload && payload.length > 0) {
                return payload[0].payload.date;
              }
              return String(_label);
            }}
          />
          <Line
            type="monotone"
            dataKey="elo"
            stroke="#34d399"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, fill: '#34d399' }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
};

export default EloTimeSeries;

import React, { useMemo } from 'react';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import type { ErrorEvent, GameWithMoves } from '../types';

interface Props {
  errors: ErrorEvent[];
  gamesWithMoves: GameWithMoves[];
}

interface DataPoint {
  windowIndex: number;
  moveLabel: string;
  missedPct: number;
  lastDate: string;
}

const MissedRateTimeSeries: React.FC<Props> = ({ errors, gamesWithMoves }) => {
  const data = useMemo(() => {
    if (!gamesWithMoves || gamesWithMoves.length === 0) return [];

    const sorted = [...gamesWithMoves].sort(
      (a, b) => new Date(a.end_time).getTime() - new Date(b.end_time).getTime()
    );

    const missedByGame = new Map<string, number>();
    for (const e of errors) {
      if (e.converted_actual === 0) {
        missedByGame.set(e.game_url, (missedByGame.get(e.game_url) || 0) + 1);
      }
    }

    const points: DataPoint[] = [];
    let movesInWindow = 0;
    let missedInWindow = 0;
    let windowStart = 0;
    let lastEndTime = '';

    for (const game of sorted) {
      const pm = game.player_moves || 0;
      if (pm === 0) continue;

      const gameMissed = missedByGame.get(game.game_url) || 0;

      movesInWindow += pm;
      missedInWindow += gameMissed;
      lastEndTime = game.end_time;

      while (movesInWindow >= 100) {
        const fraction = 100 / movesInWindow;
        const missedForPoint = missedInWindow * fraction;

        const pct = (missedForPoint / 100) * 100;

        const idx = points.length;
        const endMove = (idx + 1) * 100;

        let dateStr = '';
        if (lastEndTime) {
          try {
            dateStr = new Date(lastEndTime).toLocaleDateString();
          } catch {
            dateStr = lastEndTime;
          }
        }

        points.push({
          windowIndex: idx,
          moveLabel: `${windowStart + 1}-${endMove}`,
          missedPct: Math.round(pct * 100) / 100,
          lastDate: dateStr,
        });

        movesInWindow -= 100;
        missedInWindow -= missedInWindow * fraction;
        windowStart = endMove;
      }
    }

    return points;
  }, [errors, gamesWithMoves]);

  if (data.length < 2) return null;

  return (
    <div className="bg-slate-800 p-6 rounded-lg shadow-lg mb-8">
      <h2 className="text-2xl font-bold text-white mb-2">Missed Opportunity Rate Over Time</h2>
      <p className="text-sm text-slate-400 mb-6">
        Missed opportunity % per 100 player moves (non-overlapping windows, chronological order)
      </p>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={data} margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
          <XAxis
            dataKey="moveLabel"
            tick={{ fill: '#94a3b8', fontSize: 11 }}
            tickLine={{ stroke: '#475569' }}
            axisLine={{ stroke: '#475569' }}
            interval="preserveStartEnd"
          />
          <YAxis
            tick={{ fill: '#94a3b8', fontSize: 11 }}
            tickLine={{ stroke: '#475569' }}
            axisLine={{ stroke: '#475569' }}
            tickFormatter={(v: number) => `${v}%`}
            domain={[0, 'auto']}
          />
          <Tooltip
            contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #475569', borderRadius: '8px' }}
            labelStyle={{ color: '#f1f5f9' }}
            formatter={(value: any) => [`${value}%`, 'Missed %']}
            labelFormatter={(_label: any, payload: any) => {
              if (payload && payload.length > 0) {
                const p = payload[0].payload as DataPoint;
                return `Moves ${p.moveLabel} — ${p.lastDate}`;
              }
              return String(_label);
            }}
          />
          <Line
            type="monotone"
            dataKey="missedPct"
            stroke="#818cf8"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, fill: '#818cf8' }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
};

export default MissedRateTimeSeries;

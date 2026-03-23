import React, { useMemo } from 'react';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import type { ErrorEvent, GameWithMoves } from '../types';
import { isExcludedError } from './Heatmap';

interface Props {
  errors: ErrorEvent[];
  gamesWithMoves: GameWithMoves[];
}

interface DataPoint {
  index: number;
  pct: number;
  date: string;
}

const WINDOW = 100;

const RollingMissedRate: React.FC<Props> = ({ errors, gamesWithMoves }) => {
  const data = useMemo(() => {
    if (!gamesWithMoves || gamesWithMoves.length === 0 || !errors || errors.length === 0) return [];

    const sorted = [...gamesWithMoves].sort(
      (a, b) => new Date(a.end_time).getTime() - new Date(b.end_time).getTime()
    );
    const gameEndTimes = new Map<string, string>();
    for (const g of sorted) {
      gameEndTimes.set(g.game_url, g.end_time);
    }

    const allOpps = errors
      .filter(e => !isExcludedError(e))
      .map(e => ({
        missed: e.converted_actual === 0 ? 1 : 0,
        game_url: e.game_url,
        end_time: gameEndTimes.get(e.game_url) || '',
      }))
      .sort((a, b) => {
        const ta = new Date(a.end_time).getTime() || 0;
        const tb = new Date(b.end_time).getTime() || 0;
        return ta - tb;
      });

    if (allOpps.length < WINDOW) return [];

    const points: DataPoint[] = [];
    let missedSum = 0;
    for (let i = 0; i < allOpps.length; i++) {
      missedSum += allOpps[i].missed;
      if (i >= WINDOW) missedSum -= allOpps[i - WINDOW].missed;
      if (i >= WINDOW - 1) {
        const pct = (missedSum / WINDOW) * 100;
        let dateStr = '';
        try { dateStr = new Date(allOpps[i].end_time).toLocaleDateString(); } catch { dateStr = ''; }
        points.push({
          index: points.length,
          pct: Math.round(pct * 100) / 100,
          date: dateStr,
        });
      }
    }
    return points;
  }, [errors, gamesWithMoves]);

  if (data.length < 2) return null;

  return (
    <div className="bg-slate-800 p-6 rounded-lg shadow-lg mb-8">
      <h2 className="text-2xl font-bold text-white mb-2">Rolling Missed Opportunity Rate</h2>
      <p className="text-sm text-slate-400 mb-6">
        % of missed opportunities over a rolling window of {WINDOW} opportunities
      </p>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={data} margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
          <XAxis
            dataKey="index"
            tick={{ fill: '#94a3b8', fontSize: 11 }}
            tickLine={{ stroke: '#475569' }}
            axisLine={{ stroke: '#475569' }}
            interval="preserveStartEnd"
            label={{ value: 'Opportunity Window', position: 'insideBottom', offset: -5, fill: '#94a3b8', fontSize: 11 }}
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
                return `Window ending at opportunity #${(p.index + WINDOW)} — ${p.date}`;
              }
              return String(_label);
            }}
          />
          <Line
            type="monotone"
            dataKey="pct"
            stroke="#f472b6"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, fill: '#f472b6' }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
};

export default RollingMissedRate;

import React, { useMemo } from 'react';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import type { ErrorEvent, GameWithMoves } from '../types';
import { isExcludedError } from './Heatmap';

interface Props {
  errors: ErrorEvent[];
  gamesWithMoves: GameWithMoves[];
}

interface DataPoint {
  date: string;
  pct: number;
  totalOpps: number;
}

const WINDOW = 100;

const DailyRollingMissedRate: React.FC<Props> = ({ errors, gamesWithMoves }) => {
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
        end_time: gameEndTimes.get(e.game_url) || '',
      }))
      .filter(o => o.end_time)
      .sort((a, b) => new Date(a.end_time).getTime() - new Date(b.end_time).getTime());

    if (allOpps.length < WINDOW) return [];

    const uniqueDays = new Map<string, number>();
    for (const g of sorted) {
      try {
        const dayStr = new Date(g.end_time).toLocaleDateString();
        const ts = new Date(g.end_time).getTime();
        if (!uniqueDays.has(dayStr) || ts > uniqueDays.get(dayStr)!) {
          uniqueDays.set(dayStr, ts);
        }
      } catch { /* skip */ }
    }

    const dayEntries = Array.from(uniqueDays.entries())
      .sort((a, b) => a[1] - b[1]);

    const points: DataPoint[] = [];

    for (const [dayStr, dayTs] of dayEntries) {
      const dayEnd = new Date(dayTs);
      dayEnd.setHours(23, 59, 59, 999);
      const dayEndMs = dayEnd.getTime();

      let count = 0;
      for (const o of allOpps) {
        if (new Date(o.end_time).getTime() <= dayEndMs) count++;
        else break;
      }

      if (count < WINDOW) continue;

      const windowStart = count - WINDOW;
      let missedSum = 0;
      for (let i = windowStart; i < count; i++) {
        missedSum += allOpps[i].missed;
      }

      const pct = (missedSum / WINDOW) * 100;
      points.push({
        date: dayStr,
        pct: Math.round(pct * 100) / 100,
        totalOpps: count,
      });
    }

    return points;
  }, [errors, gamesWithMoves]);

  if (data.length < 2) return null;

  return (
    <div className="bg-slate-800 p-6 rounded-lg shadow-lg mb-8">
      <h2 className="text-2xl font-bold text-white mb-2">Daily Rolling Missed Opportunity Rate</h2>
      <p className="text-sm text-slate-400 mb-6">
        % of missed opportunities over the last {WINDOW} opportunities as of each day
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
                return `${p.date} — ${p.totalOpps} total opportunities`;
              }
              return String(_label);
            }}
          />
          <Line
            type="monotone"
            dataKey="pct"
            stroke="#fb923c"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, fill: '#fb923c' }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
};

export default DailyRollingMissedRate;

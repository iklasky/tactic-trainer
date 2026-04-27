import { useState, useEffect, useRef, useCallback } from 'react';
import { Loader2, Info, RefreshCw, Search } from 'lucide-react';
import Heatmap from './components/Heatmap';
import { isExcludedError } from './components/Heatmap';
import DifferenceHeatmap from './components/DifferenceHeatmap';
import ChessBoardViewer from './components/ChessBoardViewer';
import EloTimeSeries from './components/EloTimeSeries';
import RollingMissedRate from './components/RollingMissedRate';
import DailyRollingMissedRate from './components/DailyRollingMissedRate';
import TrainingTactics from './components/TrainingTactics';
import { fetchAnalysis, fetchPlayers, submitAnalysis, pollJobStatus, fetchActiveJob, fetchQueueInfo } from './api';
import type { ErrorEvent, AnalysisResult } from './types';
import type { JobStatus } from './api';

interface Player {
  username: string;
  opportunities: number;
  games: number;
}

function App() {
  const [loading, setLoading] = useState(false);
  const [analysisResult, setAnalysisResult] = useState<AnalysisResult | null>(null);
  const [fieldAverageResult, setFieldAverageResult] = useState<AnalysisResult | null>(null);
  const [selectedEvents, setSelectedEvents] = useState<ErrorEvent[]>([]);
  const [showEventDetails, setShowEventDetails] = useState(false);
  const [cellDetailFilter, setCellDetailFilter] = useState<'missed' | 'found'>('missed');
  const [selectedError, setSelectedError] = useState<ErrorEvent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [players, setPlayers] = useState<Player[]>([]);
  const [selectedPlayer, setSelectedPlayer] = useState<string>('');
  const [searchInput, setSearchInput] = useState<string>('');
  const [searchError, setSearchError] = useState<string | null>(null);
  const [fieldLoading, setFieldLoading] = useState<boolean>(false);
  const [viewMode, setViewMode] = useState<'count' | 'percentage'>('percentage');
  const [fieldViewMode, setFieldViewMode] = useState<'count' | 'percentage'>('percentage');
  const [minElo, setMinElo] = useState<number>(0);
  const [maxElo, setMaxElo] = useState<number>(3000);
  const [tempMinElo, setTempMinElo] = useState<number>(0);
  const [tempMaxElo, setTempMaxElo] = useState<number>(3000);

  // Pull Data state
  const [pullUsername, setPullUsername] = useState('');
  const [pullNumGames, setPullNumGames] = useState(500);
  const [pullLoading, setPullLoading] = useState(false);
  const [pullError, setPullError] = useState<string | null>(null);
  const [activeJob, setActiveJob] = useState<JobStatus | null>(null);
  const [queueJobsAhead, setQueueJobsAhead] = useState(0);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const selectedPlayerRef = useRef(selectedPlayer);

  useEffect(() => {
    selectedPlayerRef.current = selectedPlayer;
  }, [selectedPlayer]);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const startPolling = useCallback((jobId: string, _username: string) => {
    stopPolling();
    let lastDone = 0;
    pollRef.current = setInterval(async () => {
      try {
        const status = await pollJobStatus(jobId);
        setActiveJob(status);

        if (status.games_done > lastDone) {
          lastDone = status.games_done;
          loadAnalysis(status.username, true);
          loadPlayers(false);
        }

        if (status.status === 'pending') {
          try {
            const qi = await fetchQueueInfo(jobId);
            setQueueJobsAhead(qi.position);
          } catch { /* ignore */ }
        } else {
          setQueueJobsAhead(0);
        }

        if (status.status === 'completed' || status.status === 'failed') {
          stopPolling();
          await loadPlayers(false);
          await loadAnalysis(status.username, true);
        }
      } catch {
        // keep polling on transient errors
      }
    }, 3000);
  }, [stopPolling]);

  const handlePullData = async () => {
    if (!pullUsername.trim()) return;
    setPullLoading(true);
    setPullError(null);
    setActiveJob(null);
    stopPolling();

    const username = pullUsername.trim();

    setSelectedPlayer(username);
    try {
      await loadPlayers(false);
      await loadAnalysis(username, true);
    } catch {
      // ok if nothing exists yet
    }

    // Check if there's already an active job for this user (tab was closed)
    try {
      const existing = await fetchActiveJob(username);
      if (existing.active && existing.job_id) {
        const resumedJob: JobStatus = {
          job_id: existing.job_id,
          username: existing.username || username,
          status: (existing.status as JobStatus['status']) || 'running',
          total_games: existing.total_games || 0,
          games_done: existing.games_done || 0,
          games_failed: existing.games_failed || 0,
          pct_done: existing.pct_done || 0,
        };
        setActiveJob(resumedJob);
        setPullLoading(false);
        startPolling(existing.job_id, username);
        return;
      }
    } catch {
      // ignore — proceed to submit
    }

    try {
      const result = await submitAnalysis(username, pullNumGames);

      if (!result.job_id) {
        setPullLoading(false);
        setPullError(null);
        setActiveJob(null);
        return;
      }

      const jobId = result.job_id!;
      const initial: JobStatus = {
        job_id: jobId,
        username,
        status: 'pending',
        total_games: result.total_games,
        games_done: 0,
        games_failed: 0,
        pct_done: 0,
      };
      setActiveJob(initial);
      setPullLoading(false);
      startPolling(jobId, username);
    } catch (e: any) {
      setPullError(e.message || 'Failed to submit analysis');
      setPullLoading(false);
    }
  };

  // Cleanup polling on unmount
  useEffect(() => () => stopPolling(), [stopPolling]);

  // Load players on mount (no auto-select — user must choose)
  useEffect(() => {
    loadPlayers(false);
  }, []);
  
  // Load analysis when player selection changes; also check for active jobs
  useEffect(() => {
    if (!selectedPlayer) return;

    loadAnalysis(selectedPlayer);
    loadFieldAverage();
    setSelectedEvents([]);
    setShowEventDetails(false);
    setSelectedError(null);

    // Check for an active batch job so we can resume the progress bar
    if (!pollRef.current) {
      fetchActiveJob(selectedPlayer).then((existing) => {
        if (existing.active && existing.job_id) {
          const resumed: JobStatus = {
            job_id: existing.job_id,
            username: existing.username || selectedPlayer,
            status: (existing.status as JobStatus['status']) || 'running',
            total_games: existing.total_games || 0,
            games_done: existing.games_done || 0,
            games_failed: existing.games_failed || 0,
            pct_done: existing.pct_done || 0,
          };
          setActiveJob(resumed);
          startPolling(existing.job_id, selectedPlayer);
        }
      }).catch(() => {});
    }
  }, [selectedPlayer]);
  
  // Reload field average when ELO range changes
  useEffect(() => {
    if (players.length > 0) {
      loadFieldAverage();
    }
  }, [minElo, maxElo]);
  
  // Sync temp values with actual values
  useEffect(() => {
    setTempMinElo(minElo);
    setTempMaxElo(maxElo);
  }, [minElo, maxElo]);
  
  const loadPlayers = async (autoSelect = true) => {
    try {
      const data = await fetchPlayers();
      setPlayers(data.players || []);
      if (autoSelect && data.players && data.players.length > 0) {
        setSelectedPlayer(data.players[0].username);
      }
    } catch (error) {
      console.error('Failed to load players:', error);
    }
  };
  
  const loadAnalysis = async (username?: string, silent = false) => {
    if (!silent) {
      setLoading(true);
      setError(null);
    }
    
    try {
      const result = await fetchAnalysis(username);
      setAnalysisResult(result);
    } catch (err: any) {
      if (!silent) {
        console.error('Failed to load analysis:', err);
        setError(err.message || 'Failed to load analysis');
      }
    } finally {
      if (!silent) {
        setLoading(false);
      }
    }
  };
  
  const loadFieldAverage = async () => {
    setFieldLoading(true);
    try {
      // Fetch analysis for all players (no username filter) with ELO range
      const result = await fetchAnalysis(undefined, minElo, maxElo);
      setFieldAverageResult(result);
    } catch (err: any) {
      console.error('Failed to load field average:', err);
    } finally {
      setFieldLoading(false);
    }
  };

  const eloRangeLabel = (() => {
    if (minElo <= 0 && maxElo >= 3000) return 'All players';
    if (minElo <= 0) return `Up to ${maxElo} ELO`;
    if (maxElo >= 3000) return `${minElo}+ ELO`;
    return `${minElo} – ${maxElo} ELO`;
  })();
  
  const handlePlayerSearch = useCallback(async () => {
    const q = searchInput.trim();
    if (!q) return;

    // Always refresh the player list so newly-finished pulls are visible
    let list = players;
    try {
      const data = await fetchPlayers();
      list = data.players || [];
      setPlayers(list);
    } catch {
      // fall back to whatever we already have
    }

    const ql = q.toLowerCase();
    const match = list.find(p => p.username.toLowerCase() === ql);
    if (match) {
      setSearchError(null);
      setSelectedPlayer(match.username);
    } else {
      setSearchError(`"${q}" has no processed games on Tactic Trainer.`);
      setSelectedPlayer('');
      setAnalysisResult(null);
    }
  }, [searchInput, players]);

  const handleCellClick = (_deltaIdx: number, _tIdx: number, events: ErrorEvent[]) => {
    setSelectedEvents(events);
    setShowEventDetails(events.length > 0);
    setSelectedError(null); // Clear board when clicking cell
    
    // Scroll to cell details
    setTimeout(() => {
      const cellDetailsElement = document.getElementById('cell-details');
      if (cellDetailsElement) {
        cellDetailsElement.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    }, 100);
  };
  
  const handleMoveClick = (error: ErrorEvent) => {
    setSelectedError(error);
    // Keep showEventDetails true so table stays visible
    
    // Scroll to board below the table
    setTimeout(() => {
      const boardElement = document.getElementById('chess-board-viewer');
      if (boardElement) {
        boardElement.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    }, 100);
  };
  
  return (
    <div className="min-h-screen bg-slate-900 text-slate-50">
      <div className="max-w-7xl mx-auto px-4 py-8">
        {/* Header */}
        <div className="mb-12">
          <h1 className="text-4xl font-bold mb-2 text-white">Tactic Trainer</h1>
          <p className="text-slate-400 text-lg">
            Discover missed scoring opportunities and conversion patterns
          </p>
        </div>
        
        {/* Info Card */}
        <div className="bg-slate-800 p-6 rounded-lg shadow-lg mb-8 border-l-4 border-indigo-500">
          <div className="flex items-start gap-4">
            <Info className="w-6 h-6 text-indigo-400 flex-shrink-0 mt-1" />
            <div>
              <h3 className="text-lg font-semibold text-white mb-2">How it works</h3>
              <ul className="text-slate-300 space-y-2 text-sm">
                <li>• Analyzes your most recent games using Stockfish</li>
                <li>• Identifies when opponents made mistakes (eval gain ≥100 centipawns for you)</li>
                <li>• Checks if you converted the advantage or missed the opportunity</li>
                <li>• Shows how many moves the engine needs to convert each opportunity to material</li>
                <li>• Visualizes patterns: which scoring chances are you missing?</li>
              </ul>
            </div>
          </div>
        </div>
        
        {/* Pull Data Card */}
        <div className="bg-slate-800 p-6 rounded-lg shadow-lg mb-8 border-l-4 border-emerald-500">
          <h3 className="text-lg font-semibold text-white mb-4">Pull & Analyze Games</h3>
          <div className="flex flex-wrap items-end gap-4">
            <div className="flex-1 min-w-[200px]">
              <label className="block text-sm text-slate-400 mb-1">Chess.com Username</label>
              <div className="relative">
                <input
                  type="text"
                  value={pullUsername}
                  onChange={(e) => setPullUsername(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handlePullData()}
                  placeholder="e.g. hikaru"
                  className="w-full bg-slate-700 border border-slate-600 rounded-lg px-4 py-3 text-white focus:outline-none focus:ring-2 focus:ring-emerald-500"
                />
                <Search className="absolute right-3 top-3.5 w-5 h-5 text-slate-500" />
              </div>
            </div>
            <div className="w-32">
              <label className="block text-sm text-slate-400 mb-1">Games</label>
              <input
                type="number"
                value={pullNumGames}
                onChange={(e) => setPullNumGames(Math.max(1, Math.min(500, Number(e.target.value))))}
                min={1}
                max={500}
                className="w-full bg-slate-700 border border-slate-600 rounded-lg px-4 py-3 text-white focus:outline-none focus:ring-2 focus:ring-emerald-500"
              />
            </div>
            <button
              onClick={handlePullData}
              disabled={pullLoading || !pullUsername.trim() || (activeJob !== null && activeJob.status !== 'completed' && activeJob.status !== 'failed')}
              className="bg-emerald-600 hover:bg-emerald-700 disabled:bg-slate-600 disabled:cursor-not-allowed text-white px-6 py-3 rounded-lg font-semibold transition-colors flex items-center gap-2"
            >
              {pullLoading ? (
                <>
                  <Loader2 className="w-5 h-5 animate-spin" />
                  Fetching...
                </>
              ) : (
                'Pull Data'
              )}
            </button>
          </div>

          {pullError && (
            <div className="mt-4 bg-red-900/20 border border-red-500 text-red-200 p-3 rounded-lg text-sm">
              {pullError}
            </div>
          )}

          {activeJob && (
            <div className="mt-4">
              <div className="flex justify-between text-sm text-slate-300 mb-2">
                <span>
                  Analyzing {activeJob.username}'s games — {activeJob.status === 'completed' ? 'Done!' : activeJob.status}
                </span>
                <span>
                  {activeJob.games_done}/{activeJob.total_games} games
                  {activeJob.games_failed > 0 && ` (${activeJob.games_failed} failed)`}
                </span>
              </div>
              <div className="w-full bg-slate-700 rounded-full h-3">
                <div
                  className={`h-3 rounded-full transition-all duration-500 ${
                    activeJob.status === 'completed'
                      ? 'bg-emerald-500'
                      : activeJob.status === 'failed'
                      ? 'bg-red-500'
                      : 'bg-indigo-500'
                  }`}
                  style={{ width: `${activeJob.pct_done}%` }}
                />
              </div>
              {activeJob.status === 'pending' && queueJobsAhead > 0 && (
                <p className="text-sm text-amber-400 mt-2">
                  {activeJob.username}'s job is #{queueJobsAhead + 1} in queue ({queueJobsAhead} job{queueJobsAhead !== 1 ? 's' : ''} ahead)
                </p>
              )}
              {activeJob.status === 'completed' && (
                <p className="text-sm text-emerald-400 mt-2">
                  Analysis complete! Results are now loaded below.
                </p>
              )}
            </div>
          )}
        </div>

        {/* Player Search and Stats Card */}
        <div className="bg-slate-800 p-6 rounded-lg shadow-lg mb-8">
          <div className="grid md:grid-cols-[1fr_auto_auto] gap-4 items-end">
            {/* Player Search */}
            <div>
              <label htmlFor="player-search" className="block text-sm font-medium text-slate-400 mb-2">
                Look up Player
              </label>
              <div className="relative">
                <input
                  id="player-search"
                  type="text"
                  value={searchInput}
                  onChange={(e) => {
                    setSearchInput(e.target.value);
                    if (searchError) setSearchError(null);
                  }}
                  onKeyDown={(e) => e.key === 'Enter' && handlePlayerSearch()}
                  placeholder="Enter exact chess.com username"
                  className="w-full bg-slate-700 border border-slate-600 rounded-lg px-4 py-3 text-white text-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
                <Search className="absolute right-3 top-3.5 w-5 h-5 text-slate-500" />
              </div>
            </div>

            {/* Search Button */}
            <button
              onClick={handlePlayerSearch}
              disabled={!searchInput.trim()}
              className="bg-indigo-500 hover:bg-indigo-600 disabled:bg-slate-600 disabled:cursor-not-allowed text-white px-6 py-3 rounded-lg flex items-center gap-2 font-semibold transition-colors"
            >
              <Search className="w-5 h-5" />
              Search
            </button>

            {/* Reload Button (only relevant once a player is loaded) */}
            {selectedPlayer && (
              <button
                onClick={() => loadAnalysis(selectedPlayer)}
                disabled={loading}
                className="bg-slate-700 hover:bg-slate-600 disabled:bg-slate-800 disabled:cursor-not-allowed text-white px-4 py-3 rounded-lg flex items-center gap-2 font-semibold transition-colors"
              >
                {loading ? (
                  <Loader2 className="w-5 h-5 animate-spin" />
                ) : (
                  <RefreshCw className="w-5 h-5" />
                )}
                Reload
              </button>
            )}
          </div>

          {searchError && (
            <div className="mt-4 bg-red-900/20 border border-red-500 text-red-200 p-3 rounded-lg text-sm">
              {searchError}
            </div>
          )}

          {selectedPlayer && (
            <div className="mt-4 text-slate-300">
              <span className="text-slate-400 text-sm">Currently viewing: </span>
              <span className="font-semibold text-white">{selectedPlayer}</span>
            </div>
          )}

          {/* Stats */}
          {selectedPlayer && analysisResult && (() => {
              const filteredErrors = analysisResult.errors.filter(e => !isExcludedError(e));
              const filteredMissed = filteredErrors.filter(e => e.converted_actual === 0).length;
              const filteredTotal = filteredErrors.length;
              return (
                <div className="grid grid-cols-4 gap-4 mt-6 pt-6 border-t border-slate-700">
                  <div>
                    <div className="text-slate-400 text-sm mb-1">Games Analyzed</div>
                    <div className="text-2xl font-bold text-white">
                      {analysisResult.total_games_analyzed || analysisResult.games_analyzed}
                    </div>
                  </div>
                  <div>
                    <div className="text-slate-400 text-sm mb-1">Missed Opportunities</div>
                    <div className="text-2xl font-bold text-indigo-400">{filteredMissed}</div>
                  </div>
                  <div>
                    <div className="text-slate-400 text-sm mb-1">Missed Opportunities / Total Opportunities</div>
                    <div className="text-2xl font-bold text-pink-400">
                      {filteredTotal > 0
                        ? `${((filteredMissed / filteredTotal) * 100).toFixed(1)}%`
                        : '0%'}
                    </div>
                  </div>
                  <div>
                    <div className="text-slate-400 text-sm mb-1">Avg Missed Opportunity Size</div>
                    <div className="text-2xl font-bold text-amber-400">
                      {(() => {
                        const missed = filteredErrors.filter(e => e.converted_actual === 0);
                        if (missed.length === 0) return '—';
                        const avg = missed.reduce((sum, e) => sum + e.delta_cp, 0) / missed.length;
                        return `${Math.round(avg)} cp`;
                      })()}
                    </div>
                  </div>
                </div>
              );
            })()}
        </div>
        
        {/* Loading State */}
        {loading && !analysisResult && (
          <div className="flex items-center justify-center py-20">
            <div className="text-center">
              <Loader2 className="w-12 h-12 animate-spin text-indigo-500 mx-auto mb-4" />
              <p className="text-slate-400">Loading analysis...</p>
            </div>
          </div>
        )}
        
        {/* Error State */}
        {error && (
          <div className="bg-red-900/20 border border-red-500 text-red-200 p-4 rounded-lg">
            {error}
          </div>
        )}
        
        {/* Analysis Results */}
        {selectedPlayer && analysisResult && !loading && (
          <>
            {/* Heatmap - 3-up Comparison */}
            <div className="bg-slate-800 p-6 rounded-lg shadow-lg mb-8">
              <h2 className="text-2xl font-bold text-white mb-6">Missed Opportunity Analysis</h2>

              <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
                {/* Player's Heatmap */}
                <div className="flex flex-col">
                  <div className="flex items-center gap-2 mb-2 min-h-[28px]">
                    <h3 className="text-lg font-semibold text-slate-300">
                      {selectedPlayer}'s Opportunities
                    </h3>
                  </div>
                  {(() => {
                    const pe = analysisResult.errors.filter(e => !isExcludedError(e));
                    const pm = pe.filter(e => e.converted_actual === 0).length;
                    const pct = pe.length > 0 ? ((pm / pe.length) * 100).toFixed(1) : '0';
                    return (
                      <p className="text-sm text-slate-400 mb-4 min-h-[20px]">
                        Overall missed: <span className="text-pink-400 font-semibold">{pct}%</span> ({pm}/{pe.length})
                      </p>
                    );
                  })()}
                  <Heatmap
                    histogram={analysisResult.histogram}
                    errors={analysisResult.errors}
                    onCellClick={handleCellClick}
                    onMoveClick={handleMoveClick}
                    viewMode={viewMode}
                    onViewModeChange={setViewMode}
                  />
                </div>

                {/* Field Average Heatmap */}
                <div className="flex flex-col">
                  <div className="flex items-center gap-2 mb-2 min-h-[28px]">
                    <h3 className="text-lg font-semibold text-slate-300">
                      Field Average ({eloRangeLabel})
                    </h3>
                    {fieldLoading && (
                      <Loader2 className="w-4 h-4 animate-spin text-indigo-400" />
                    )}
                  </div>
                  {fieldAverageResult ? (
                    <>
                      {(() => {
                        const fe = fieldAverageResult.errors.filter(e => !isExcludedError(e));
                        const fm = fe.filter(e => e.converted_actual === 0).length;
                        const pct = fe.length > 0 ? ((fm / fe.length) * 100).toFixed(1) : '0';
                        return (
                          <p className="text-sm text-slate-400 mb-4 min-h-[20px]">
                            Overall missed: <span className="text-pink-400 font-semibold">{pct}%</span> ({fm}/{fe.length})
                          </p>
                        );
                      })()}
                      <div className={fieldLoading ? 'opacity-50 transition-opacity' : 'transition-opacity'}>
                        <Heatmap
                          histogram={fieldAverageResult.histogram}
                          errors={fieldAverageResult.errors}
                          onCellClick={() => {}}
                          onMoveClick={() => {}}
                          viewMode={fieldViewMode}
                          onViewModeChange={setFieldViewMode}
                        />
                      </div>
                    </>
                  ) : (
                    <>
                      <p className="text-sm text-slate-400 mb-4 min-h-[20px]">&nbsp;</p>
                      <div className="flex items-center justify-center h-64 bg-slate-900/40 rounded-lg border border-slate-700">
                        <div className="text-center text-slate-400">
                          <Loader2 className="w-8 h-8 animate-spin text-indigo-500 mx-auto mb-2" />
                          Loading field average...
                        </div>
                      </div>
                    </>
                  )}

                  {/* ELO Range Slider — sized to match this column's heatmap */}
                  <div className="mt-6 p-4 bg-slate-700 rounded-lg">
                    <div className="flex justify-between items-center mb-3">
                      <div className="text-sm font-medium text-slate-300">
                        ELO Range Filter
                      </div>
                      <div className="text-sm text-slate-400">
                        {tempMinElo} - {tempMaxElo}
                      </div>
                    </div>

                    <div className="relative pt-1 pb-4">
                      <div className="absolute top-0 left-0 w-full h-2 bg-slate-600 rounded-full" />

                      <div
                        className="absolute top-0 h-2 bg-indigo-500 rounded-full pointer-events-none"
                        style={{
                          left: `${(tempMinElo / 3000) * 100}%`,
                          right: `${100 - (tempMaxElo / 3000) * 100}%`
                        }}
                      />

                      <input
                        type="range"
                        min="0"
                        max="3000"
                        step="50"
                        value={tempMinElo}
                        onChange={(e) => {
                          const val = Number(e.target.value);
                          if (val < tempMaxElo) setTempMinElo(val);
                        }}
                        onMouseUp={() => setMinElo(tempMinElo)}
                        onTouchEnd={() => setMinElo(tempMinElo)}
                        className="absolute top-0 w-full h-2 bg-transparent appearance-none cursor-pointer pointer-events-none [&::-webkit-slider-thumb]:pointer-events-auto [&::-moz-range-thumb]:pointer-events-auto [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-white [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-indigo-500 [&::-webkit-slider-thumb]:cursor-pointer [&::-webkit-slider-thumb]:shadow-md [&::-moz-range-thumb]:appearance-none [&::-moz-range-thumb]:w-4 [&::-moz-range-thumb]:h-4 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:bg-white [&::-moz-range-thumb]:border-2 [&::-moz-range-thumb]:border-indigo-500 [&::-moz-range-thumb]:cursor-pointer [&::-moz-range-thumb]:border-0 [&::-moz-range-thumb]:shadow-md"
                        style={{ zIndex: tempMinElo > tempMaxElo - 100 ? 5 : 3 }}
                      />

                      <input
                        type="range"
                        min="0"
                        max="3000"
                        step="50"
                        value={tempMaxElo}
                        onChange={(e) => {
                          const val = Number(e.target.value);
                          if (val > tempMinElo) setTempMaxElo(val);
                        }}
                        onMouseUp={() => setMaxElo(tempMaxElo)}
                        onTouchEnd={() => setMaxElo(tempMaxElo)}
                        className="absolute top-0 w-full h-2 bg-transparent appearance-none cursor-pointer pointer-events-none [&::-webkit-slider-thumb]:pointer-events-auto [&::-moz-range-thumb]:pointer-events-auto [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-white [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-indigo-500 [&::-webkit-slider-thumb]:cursor-pointer [&::-webkit-slider-thumb]:shadow-md [&::-moz-range-thumb]:appearance-none [&::-moz-range-thumb]:w-4 [&::-moz-range-thumb]:h-4 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:bg-white [&::-moz-range-thumb]:border-2 [&::-moz-range-thumb]:border-indigo-500 [&::-moz-range-thumb]:cursor-pointer [&::-moz-range-thumb]:border-0 [&::-moz-range-thumb]:shadow-md"
                        style={{ zIndex: 4 }}
                      />
                    </div>

                    <div className="text-xs text-slate-400 text-center mt-1">
                      Showing field average for players whose ELO was between {minElo} and {maxElo}
                    </div>
                  </div>
                </div>

                {/* Difference Heatmap (Performance Comparison) */}
                <div className="flex flex-col">
                  <div className="flex items-center gap-2 mb-2 min-h-[28px]">
                    <h3 className="text-lg font-semibold text-slate-300">
                      Performance Comparison
                    </h3>
                  </div>
                  <p className="text-sm text-slate-400 mb-4 min-h-[20px]">
                    Field % − Player %  (green = better, red = worse)
                  </p>
                  {/* invisible "View" toggle placeholder so the grid below lines up
                      vertically with the Player and Field heatmaps */}
                  <div className="mb-4 flex items-center gap-3 invisible" aria-hidden="true">
                    <label className="text-slate-300 text-sm font-medium">View:</label>
                    <div className="inline-flex rounded-lg border border-slate-600 overflow-hidden">
                      <button className="px-4 py-2 text-sm font-medium">%</button>
                      <button className="px-4 py-2 text-sm font-medium border-l border-slate-600">Count</button>
                    </div>
                  </div>
                  {fieldAverageResult ? (
                    <div className={fieldLoading ? 'opacity-50 transition-opacity' : 'transition-opacity'}>
                      <DifferenceHeatmap
                        playerHistogram={analysisResult.histogram}
                        playerErrors={analysisResult.errors}
                        fieldHistogram={fieldAverageResult.histogram}
                        fieldErrors={fieldAverageResult.errors}
                      />
                    </div>
                  ) : (
                    <div className="flex items-center justify-center h-64 bg-slate-900/40 rounded-lg border border-slate-700">
                      <div className="text-center text-slate-400">
                        <Loader2 className="w-8 h-8 animate-spin text-indigo-500 mx-auto mb-2" />
                        Computing comparison...
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Training Tactics — biased puzzle set from the user's own opportunities */}
            <TrainingTactics
              username={selectedPlayer}
              minElo={minElo}
              maxElo={maxElo}
              eloRangeLabel={eloRangeLabel}
            />

            {/* Time Series Charts */}
            {analysisResult.games_with_moves && analysisResult.games_with_moves.length > 0 && (
              <>
                <RollingMissedRate
                  errors={analysisResult.errors}
                  gamesWithMoves={analysisResult.games_with_moves}
                />
                <DailyRollingMissedRate
                  errors={analysisResult.errors}
                  gamesWithMoves={analysisResult.games_with_moves}
                />
                <EloTimeSeries
                  gamesWithMoves={analysisResult.games_with_moves}
                />
              </>
            )}
            
            {/* Event Details Table */}
            {showEventDetails && selectedEvents.length > 0 && (() => {
              const missedInCell = selectedEvents.filter(e => e.converted_actual === 0);
              const foundInCell = selectedEvents.filter(e => e.converted_actual === 1);
              const displayEvents = cellDetailFilter === 'missed' ? missedInCell : foundInCell;
              return (
              <div id="cell-details" className="bg-slate-800 p-6 rounded-lg shadow-lg mb-8">
                <div className="flex justify-between items-center mb-4">
                  <div className="flex items-center gap-4">
                    <h3 className="text-xl font-bold text-white">
                      Cell Details
                    </h3>
                    <div className="inline-flex rounded-lg border border-slate-600 overflow-hidden">
                      <button
                        onClick={() => setCellDetailFilter('missed')}
                        className={`px-3 py-1.5 text-sm font-medium transition-colors ${
                          cellDetailFilter === 'missed'
                            ? 'bg-red-600 text-white'
                            : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
                        }`}
                      >
                        Missed ({missedInCell.length})
                      </button>
                      <button
                        onClick={() => setCellDetailFilter('found')}
                        className={`px-3 py-1.5 text-sm font-medium transition-colors border-l border-slate-600 ${
                          cellDetailFilter === 'found'
                            ? 'bg-emerald-600 text-white'
                            : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
                        }`}
                      >
                        Found ({foundInCell.length})
                      </button>
                    </div>
                  </div>
                  <button
                    onClick={() => setShowEventDetails(false)}
                    className="text-slate-400 hover:text-white transition-colors"
                  >
                    Close
                  </button>
                </div>
                
                <div className="max-h-96 overflow-y-auto">
                  {displayEvents.length === 0 ? (
                    <div className="text-slate-400 text-center py-8">
                      No {cellDetailFilter === 'missed' ? 'missed' : 'successfully found'} opportunities in this cell
                    </div>
                  ) : (
                  <table className="w-full text-sm">
                    <thead className="bg-slate-700 sticky top-0">
                      <tr>
                        <th className="p-2 text-left text-slate-300">Move</th>
                        <th className="p-2 text-left text-slate-300">Delta (cp)</th>
                        <th className="p-2 text-left text-slate-300">Realized (moves)</th>
                        <th className="p-2 text-left text-slate-300">Method</th>
                        <th className="p-2 text-left text-slate-300">Game</th>
                      </tr>
                    </thead>
                    <tbody>
                      {displayEvents.map((event, idx) => (
                        <tr 
                          key={idx}
                          onClick={() => handleMoveClick(event)}
                          className={`border-t border-slate-700 cursor-pointer transition-colors ${
                            event.converted_actual === 0
                              ? 'bg-red-950/30 hover:bg-red-900/40'
                              : 'bg-emerald-950/30 hover:bg-emerald-900/40'
                          }`}
                        >
                          <td className="p-2 text-white">{event.move_san}</td>
                          <td className="p-2 text-white">
                            {event.opportunity_kind === 'mate' ? 'Checkmate' : event.delta_cp}
                          </td>
                          <td className="p-2 text-white">{event.t_plies}</td>
                          <td className="p-2 text-slate-300 text-xs">
                            {event.conversion_method === 'resignation' && (
                              <span className="bg-amber-800/50 text-amber-300 px-1.5 py-0.5 rounded">resign</span>
                            )}
                            {event.conversion_method === 'pv_following' && (
                              <span className="bg-blue-800/50 text-blue-300 px-1.5 py-0.5 rounded">PV</span>
                            )}
                            {event.conversion_method === 'actual' && (
                              <span className="bg-emerald-800/50 text-emerald-300 px-1.5 py-0.5 rounded">actual</span>
                            )}
                            {event.conversion_method === 'missed' && (
                              <span className="bg-red-800/50 text-red-300 px-1.5 py-0.5 rounded">missed</span>
                            )}
                            {!event.conversion_method && '—'}
                          </td>
                          <td className="p-2">
                            <a 
                              href={event.game_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-indigo-400 hover:text-indigo-300 underline"
                              onClick={(e) => e.stopPropagation()}
                            >
                              View
                            </a>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  )}
                </div>
              </div>
              );
            })()}
            
            {/* Chess Board Viewer */}
            {selectedError && (
              <div id="chess-board-viewer">
                <ChessBoardViewer error={selectedError} />
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export default App;


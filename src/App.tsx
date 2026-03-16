import { useState, useEffect, useRef, useCallback } from 'react';
import { Loader2, Info, RefreshCw, Search } from 'lucide-react';
import Heatmap from './components/Heatmap';
import DifferenceHeatmap from './components/DifferenceHeatmap';
import ChessBoardViewer from './components/ChessBoardViewer';
import MissedRateTimeSeries from './components/MissedRateTimeSeries';
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
  const [selectedError, setSelectedError] = useState<ErrorEvent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [players, setPlayers] = useState<Player[]>([]);
  const [selectedPlayer, setSelectedPlayer] = useState<string>('');
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
  const [queueGamesAhead, setQueueGamesAhead] = useState(0);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

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
            const qi = await fetchQueueInfo();
            setQueueGamesAhead(qi.games_ahead);
          } catch { /* ignore */ }
        } else {
          setQueueGamesAhead(0);
        }

        if (status.status === 'completed' || status.status === 'failed') {
          stopPolling();
          await loadPlayers(false);
          if (status.username) {
            setSelectedPlayer(status.username);
            await loadAnalysis(status.username, true);
          }
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
      await loadAnalysis(username);
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
  
  // Load analysis when player selection changes
  useEffect(() => {
    if (selectedPlayer && players.length > 0) {
      loadAnalysis(selectedPlayer);
      loadFieldAverage();
      setSelectedEvents([]);
      setShowEventDetails(false);
      setSelectedError(null);
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
    try {
      // Fetch analysis for all players (no username filter) with ELO range
      const result = await fetchAnalysis(undefined, minElo, maxElo);
      setFieldAverageResult(result);
    } catch (err: any) {
      console.error('Failed to load field average:', err);
    }
  };
  
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
              {activeJob.status === 'pending' && queueGamesAhead > 0 && (
                <p className="text-sm text-amber-400 mt-2">
                  {queueGamesAhead} game{queueGamesAhead !== 1 ? 's' : ''} from other users are being processed ahead of yours...
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

        {/* Player Selection and Stats Card */}
        {players.length > 0 && (
          <div className="bg-slate-800 p-6 rounded-lg shadow-lg mb-8">
            <div className="grid md:grid-cols-[1fr_auto] gap-6 items-end">
              {/* Player Selection */}
              <div>
                <label htmlFor="player-select" className="block text-sm font-medium text-slate-400 mb-2">
                  Select Player
                </label>
                <select
                  id="player-select"
                  value={selectedPlayer}
                  onChange={(e) => setSelectedPlayer(e.target.value)}
                  className="w-full bg-slate-700 border border-slate-600 rounded-lg px-4 py-3 text-white text-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
                >
                  {!selectedPlayer && (
                    <option value="">-- Select a player --</option>
                  )}
                  {players.map((player) => (
                    <option key={player.username} value={player.username}>
                      {player.username} ({player.opportunities} opportunities, {player.games} games)
                    </option>
                  ))}
                </select>
              </div>
              
              {/* Reload Button */}
              <button
                onClick={() => loadAnalysis(selectedPlayer)}
                disabled={loading}
                className="bg-indigo-500 hover:bg-indigo-600 disabled:bg-slate-600 disabled:cursor-not-allowed text-white px-6 py-3 rounded-lg flex items-center gap-2 font-semibold transition-colors"
              >
                {loading ? (
                  <>
                    <Loader2 className="w-5 h-5 animate-spin" />
                    Loading...
                  </>
                ) : (
                  <>
                    <RefreshCw className="w-5 h-5" />
                    Reload
                  </>
                )}
              </button>
            </div>
            
            {/* Stats */}
            {analysisResult && (
              <div className="grid grid-cols-4 gap-4 mt-6 pt-6 border-t border-slate-700">
                <div>
                  <div className="text-slate-400 text-sm mb-1">Games Analyzed</div>
                  <div className="text-2xl font-bold text-white">
                    {analysisResult.total_games_analyzed || analysisResult.games_analyzed}
                  </div>
                </div>
                <div>
                  <div className="text-slate-400 text-sm mb-1">Missed Opportunities</div>
                  <div className="text-2xl font-bold text-indigo-400">{analysisResult.missed_count}</div>
                </div>
                <div>
                  <div className="text-slate-400 text-sm mb-1">Missed Opportunities / Total Opportunities</div>
                  <div className="text-2xl font-bold text-pink-400">
                    {(analysisResult.total_opportunities || analysisResult.total_errors) > 0
                      ? `${((analysisResult.missed_count / (analysisResult.total_opportunities || analysisResult.total_errors)) * 100).toFixed(1)}%`
                      : '0%'}
                  </div>
                </div>
                <div>
                  <div className="text-slate-400 text-sm mb-1">Missed Opportunities / Total Moves</div>
                  <div className="text-2xl font-bold text-amber-400">
                    {(analysisResult.total_player_moves || 0) > 0
                      ? `${((analysisResult.missed_count / analysisResult.total_player_moves!) * 100).toFixed(2)}%`
                      : '—'}
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
        
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
            {/* Heatmap - Side by Side Comparison */}
            <div className="bg-slate-800 p-6 rounded-lg shadow-lg mb-8">
              <h2 className="text-2xl font-bold text-white mb-6">Missed Opportunity Analysis</h2>
              
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Player's Heatmap */}
                <div>
                  <h3 className="text-lg font-semibold text-slate-300 mb-4">
                    {selectedPlayer}'s Opportunities
                  </h3>
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
                {fieldAverageResult && (
                  <div>
                    <h3 className="text-lg font-semibold text-slate-300 mb-4">
                      Field Average (All Players)
                    </h3>
                    
                    <Heatmap
                      histogram={fieldAverageResult.histogram}
                      errors={fieldAverageResult.errors}
                      onCellClick={() => {}} // No interaction for field average
                      onMoveClick={() => {}} // No interaction for field average
                      viewMode={fieldViewMode}
                      onViewModeChange={setFieldViewMode}
                    />
                    
                    {/* ELO Range Slider */}
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
                        {/* Track */}
                        <div className="absolute top-0 left-0 w-full h-2 bg-slate-600 rounded-full" />
                        
                        {/* Active range */}
                        <div 
                          className="absolute top-0 h-2 bg-indigo-500 rounded-full pointer-events-none"
                          style={{
                            left: `${(tempMinElo / 3000) * 100}%`,
                            right: `${100 - (tempMaxElo / 3000) * 100}%`
                          }}
                        />
                        
                        {/* Min thumb */}
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
                        
                        {/* Max thumb */}
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
                        Showing games where player rating was between {minElo} and {maxElo}
                      </div>
                    </div>
                  </div>
                )}
              </div>
              
              {/* Difference Heatmap */}
              {fieldAverageResult && (
                <div className="mt-8">
                  <h3 className="text-lg font-semibold text-slate-300 mb-2 text-center">
                    Performance Comparison
                  </h3>
                  <p className="text-sm text-slate-400 mb-4 text-center">
                    Difference: Field Average % - Player % (Green = Better than average, Red = Worse than average)
                  </p>
                  <div className="flex justify-center">
                    <DifferenceHeatmap
                      playerHistogram={analysisResult.histogram}
                      playerErrors={analysisResult.errors}
                      fieldHistogram={fieldAverageResult.histogram}
                      fieldErrors={fieldAverageResult.errors}
                    />
                  </div>
                </div>
              )}
            </div>

            {/* Time Series Chart */}
            {analysisResult.games_with_moves && analysisResult.games_with_moves.length > 0 && (
              <MissedRateTimeSeries
                errors={analysisResult.errors}
                gamesWithMoves={analysisResult.games_with_moves}
              />
            )}
            
            {/* Event Details Table */}
            {showEventDetails && selectedEvents.length > 0 && (
              <div id="cell-details" className="bg-slate-800 p-6 rounded-lg shadow-lg mb-8">
                <div className="flex justify-between items-center mb-4">
                  <h3 className="text-xl font-bold text-white">
                    Cell Details ({selectedEvents.length} errors)
                  </h3>
                  <button
                    onClick={() => setShowEventDetails(false)}
                    className="text-slate-400 hover:text-white transition-colors"
                  >
                    Close
                  </button>
                </div>
                
                <div className="max-h-96 overflow-y-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-slate-700 sticky top-0">
                      <tr>
                        <th className="p-2 text-left text-slate-300">Move</th>
                        <th className="p-2 text-left text-slate-300">Delta (cp)</th>
                        <th className="p-2 text-left text-slate-300">Realized (moves)</th>
                        <th className="p-2 text-left text-slate-300">Game</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selectedEvents.map((event, idx) => (
                        <tr 
                          key={idx}
                          onClick={() => handleMoveClick(event)}
                          className="border-t border-slate-700 hover:bg-slate-700 cursor-pointer transition-colors"
                        >
                          <td className="p-2 text-white">{event.move_san}</td>
                          <td className="p-2 text-white">
                            {event.opportunity_kind === 'mate' ? 'Checkmate' : event.delta_cp}
                          </td>
                          <td className="p-2 text-white">{event.t_plies_raw || event.t_plies}</td>
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
                </div>
              </div>
            )}
            
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


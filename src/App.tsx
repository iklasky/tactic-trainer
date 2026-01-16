import { useState, useEffect } from 'react';
import { Loader2, Info, RefreshCw } from 'lucide-react';
import Heatmap from './components/Heatmap';
import ChessBoardViewer from './components/ChessBoardViewer';
import { fetchAnalysis, fetchPlayers } from './api';
import type { ErrorEvent, AnalysisResult } from './types';

interface Player {
  username: string;
  opportunities: number;
  games: number;
}

function App() {
  const [loading, setLoading] = useState(false);
  const [analysisResult, setAnalysisResult] = useState<AnalysisResult | null>(null);
  const [selectedEvents, setSelectedEvents] = useState<ErrorEvent[]>([]);
  const [showEventDetails, setShowEventDetails] = useState(false);
  const [selectedError, setSelectedError] = useState<ErrorEvent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [players, setPlayers] = useState<Player[]>([]);
  const [selectedPlayer, setSelectedPlayer] = useState<string>('');
  const [viewMode, setViewMode] = useState<'count' | 'percentage'>('count');
  
  // Load players and analysis on mount
  useEffect(() => {
    loadGames();
    loadPlayers();
  }, []);
  
  // Load analysis when player selection changes
  useEffect(() => {
    if (players.length > 0) {
      loadAnalysis(selectedPlayer);
      // Clear cell details and board when switching players
      setSelectedEvents([]);
      setShowEventDetails(false);
      setSelectedError(null);
    }
  }, [selectedPlayer]);
  
  const loadGames = async () => {
    try {
      const data = await fetchGames();
      setGamesData(data);
    } catch (error) {
      console.error('Failed to load games:', error);
    }
  };
  
  const loadPlayers = async () => {
    try {
      const data = await fetchPlayers();
      setPlayers(data.players || []);
      // Auto-select first player if available
      if (data.players && data.players.length > 0) {
        setSelectedPlayer(data.players[0].username);
      }
    } catch (error) {
      console.error('Failed to load players:', error);
    }
  };
  
  const loadAnalysis = async (username?: string) => {
    setLoading(true);
    setError(null);
    
    try {
      const result = await fetchAnalysis(username);
      setAnalysisResult(result);
    } catch (err: any) {
      console.error('Failed to load analysis:', err);
      setError(err.message || 'Failed to load analysis');
    } finally {
      setLoading(false);
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
              <div className="grid grid-cols-3 gap-4 mt-6 pt-6 border-t border-slate-700">
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
                  <div className="text-slate-400 text-sm mb-1">Missed Opportunity %</div>
                  <div className="text-2xl font-bold text-pink-400">
                    {(analysisResult.total_opportunities || analysisResult.total_errors) > 0
                      ? `${((analysisResult.missed_count / (analysisResult.total_opportunities || analysisResult.total_errors)) * 100).toFixed(1)}%`
                      : '0%'}
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
        {analysisResult && !loading && (
          <>
            {/* Heatmap */}
            <div className="bg-slate-800 p-6 rounded-lg shadow-lg mb-8">
              <h2 className="text-2xl font-bold text-white mb-6">Missed Opportunity Heatmap</h2>
              <Heatmap
                histogram={analysisResult.histogram}
                errors={analysisResult.errors}
                onCellClick={handleCellClick}
                onMoveClick={handleMoveClick}
                viewMode={viewMode}
                onViewModeChange={setViewMode}
              />
            </div>
            
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


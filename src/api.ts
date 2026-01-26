const API_BASE = (import.meta as any).env?.PROD ? '' : 'http://localhost:5000';

export async function fetchGames() {
  const response = await fetch(`${API_BASE}/api/games`);
  if (!response.ok) throw new Error('Failed to fetch games');
  return response.json();
}

export async function fetchPlayers() {
  const response = await fetch(`${API_BASE}/api/players`);
  if (!response.ok) throw new Error('Failed to fetch players');
  return response.json();
}

export async function fetchAnalysis(username?: string, minElo?: number, maxElo?: number) {
  const params = new URLSearchParams();
  
  if (username) {
    params.append('username', username);
  }
  
  if (minElo !== undefined && minElo > 0) {
    params.append('min_elo', minElo.toString());
  }
  
  if (maxElo !== undefined && maxElo < 3000) {
    params.append('max_elo', maxElo.toString());
  }
  
  const url = `${API_BASE}/api/analysis${params.toString() ? '?' + params.toString() : ''}`;
  
  const response = await fetch(url);
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.error || 'Failed to fetch analysis');
  }
  return response.json();
}


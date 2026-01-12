const API_BASE = import.meta.env.PROD ? '' : 'http://localhost:5000';

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

export async function fetchAnalysis(username?: string) {
  const url = username 
    ? `${API_BASE}/api/analysis?username=${encodeURIComponent(username)}`
    : `${API_BASE}/api/analysis`;
  
  const response = await fetch(url);
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.error || 'Failed to fetch analysis');
  }
  return response.json();
}


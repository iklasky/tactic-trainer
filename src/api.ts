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

// ── New: analysis submission + polling ────────────────────────────────────

export interface JobStatus {
  job_id: string;
  username: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  total_games: number;
  games_done: number;
  games_failed: number;
  pct_done: number;
}

export async function submitAnalysis(username: string, numGames: number = 500): Promise<{ job_id: string | null; total_games: number; skipped?: number; message?: string }> {
  const response = await fetch(`${API_BASE}/api/submit-analysis`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, num_games: numGames }),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Failed to submit analysis');
  return data;
}

export async function pollJobStatus(jobId: string): Promise<JobStatus> {
  const response = await fetch(`${API_BASE}/api/job-status/${jobId}`);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Failed to fetch job status');
  return data;
}

export async function searchUser(username: string): Promise<{ exists: boolean; username: string }> {
  const response = await fetch(`${API_BASE}/api/search-user?username=${encodeURIComponent(username)}`);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Failed to search user');
  return data;
}


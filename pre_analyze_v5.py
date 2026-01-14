"""
Pre-analysis script V5 (macOS-focused safety + multiprocessing)

Features:
- Supports CP and MATE opportunities via ChessAnalyzerV5
- Mate opportunities are labeled via opportunity_kind='mate' and mate_in
- t_plies for mate is plies-to-checkmate along perfect play within horizon
- CP opportunities use 3-ply hold rule but report t_plies as FIRST ply of hold window

Performance:
- Multiprocessing: each worker has its own Stockfish process (Threads=1)
- A single writer in parent process appends to CSV incrementally

Safety (highest priority):
- Monitor system RAM usage and kill the entire run if > 80%
- Periodically print system RAM/CPU + per-worker RSS/CPU

Notes:
- This script is designed for macOS (uses vm_stat/sysctl/ps/pgrep).
- You can run with caffeinate:
    caffeinate -i python -u pre_analyze_v5.py
"""

from __future__ import annotations

import csv
import json
import os
import signal
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import requests

from chess_analyzer_v5 import ChessAnalyzerV5


USER_AGENT = "TacticTrainer/1.0 (Contact: github.com/iklasky/tactic-trainer)"


@dataclass
class Task:
    username: str
    game_index: int
    pgn: str
    white_player: str
    black_player: str
    game_url: str


def run_cmd(cmd: List[str]) -> str:
    return subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode("utf-8", errors="ignore")


def get_memory_pressure_macos() -> Tuple[str, Optional[float]]:
    """
    Returns (pressure_level, free_pct).

    pressure_level: one of "Normal" | "Warning" | "Critical" | "Unknown"
    free_pct: system-wide free percentage if available.

    Uses `memory_pressure`, which is more aligned with real system stress than vm_stat,
    because macOS aggressively caches memory.
    """
    try:
        out = run_cmd(["memory_pressure", "-l", "1"])
    except Exception:
        return "Unknown", None

    level = "Unknown"
    free_pct: Optional[float] = None
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("System-wide memory pressure:"):
            # e.g. "System-wide memory pressure: Normal"
            level = line.split(":", 1)[1].strip() or "Unknown"
        if line.startswith("System-wide memory free percentage:"):
            # e.g. "System-wide memory free percentage: 12%"
            try:
                v = line.split(":", 1)[1].strip()
                v = v.replace("%", "").strip()
                free_pct = float(v)
            except Exception:
                free_pct = None
    return level, free_pct


def get_ps_stats(pid: int) -> Tuple[float, float]:
    """
    Returns (rss_mb, cpu_pct) for a pid using `ps`.
    """
    try:
        out = run_cmd(["ps", "-o", "rss=,%cpu=", "-p", str(pid)]).strip()
        if not out:
            return 0.0, 0.0
        parts = out.split()
        rss_kb = float(parts[0])
        cpu_pct = float(parts[1]) if len(parts) > 1 else 0.0
        return rss_kb / 1024.0, cpu_pct
    except Exception:
        return 0.0, 0.0


def get_children_pids(pid: int) -> List[int]:
    try:
        out = run_cmd(["pgrep", "-P", str(pid)]).strip()
        if not out:
            return []
        return [int(x) for x in out.splitlines() if x.strip().isdigit()]
    except Exception:
        return []


def get_tree_stats(pid: int) -> Tuple[float, float]:
    """
    Sum RSS/CPU for pid + its direct children (good enough for Stockfish subprocess).
    """
    rss, cpu = get_ps_stats(pid)
    for c in get_children_pids(pid):
        r2, c2 = get_ps_stats(c)
        rss += r2
        cpu += c2
    return rss, cpu


def fetch_recent_games(username: str, num_games: int) -> List[Dict]:
    archives_url = f"https://api.chess.com/pub/player/{username}/games/archives"
    headers = {"User-Agent": USER_AGENT}
    r = requests.get(archives_url, headers=headers, timeout=30)
    r.raise_for_status()
    archives = r.json().get("archives", [])
    if not archives:
        return []

    games: List[Dict] = []
    for archive_url in reversed(archives):
        if len(games) >= num_games:
            break
        rr = requests.get(archive_url, headers=headers, timeout=30)
        if rr.status_code != 200:
            continue
        games.extend(rr.json().get("games", []))
        time.sleep(0.25)

    return games[-num_games:]


# Worker globals (created once per process)
_ANALYZER: Optional[ChessAnalyzerV5] = None


def _worker_init():
    global _ANALYZER
    _ANALYZER = ChessAnalyzerV5()


def _analyze_task(task: Task) -> Tuple[Task, List[Dict]]:
    global _ANALYZER
    if _ANALYZER is None:
        _ANALYZER = ChessAnalyzerV5()
    opps = _ANALYZER.analyze_game(task.pgn, task.username)
    # Attach indexing for stable CSV
    for idx, o in enumerate(opps):
        o["game_index"] = task.game_index
        o["event_index"] = idx
        # Prefer URL from API payload if present
        if task.game_url and not o.get("game_url"):
            o["game_url"] = task.game_url
        # Carry opponent names (helps logging)
        o.setdefault("white_player", task.white_player)
        o.setdefault("black_player", task.black_player)
    return task, opps


def _kill_pool(executor: ProcessPoolExecutor):
    try:
        executor.shutdown(cancel_futures=True)
    except Exception:
        pass


def main():
    # ---- Config ----
    USERNAMES = ["k2f4x", "key_kay", "jtkms"]
    GAMES_PER_USER = 100
    OUTPUT_CSV = "analysis_results_v5.csv"
    INPUT_JSON = "fetched_games_v5.json"

    # Worker count (safety-first): default to 6, override via env
    max_workers = int(os.environ.get("TT_WORKERS", "6"))
    # Safety: RAM limit percent
    max_ram_pct = float(os.environ.get("TT_MAX_RAM_PCT", "80"))
    # Monitor interval seconds
    monitor_interval = float(os.environ.get("TT_MONITOR_SEC", "3"))

    print("=" * 80, flush=True)
    print("CHESS TACTIC TRAINER - PRE-ANALYSIS V5", flush=True)
    print("Adds mate opportunities + multiprocessing with safety monitor (macOS)", flush=True)
    print(f"Workers: {max_workers} (set TT_WORKERS to change)", flush=True)
    print(f"RAM kill-switch: {max_ram_pct:.1f}% (set TT_MAX_RAM_PCT to change)", flush=True)
    print("=" * 80, flush=True)

    # ---- Fetch tasks ----
    tasks: List[Task] = []
    game_counter = 0
    if not os.path.exists(INPUT_JSON):
        print(f"❌ Missing input file: {INPUT_JSON}", flush=True)
        print("Run: python fetch_recent_v5.py --users k2f4x key_kay jtkms --n 100 --out fetched_games_v5.json", flush=True)
        return

    with open(INPUT_JSON, "r", encoding="utf-8") as f:
        fetched = json.load(f)

    for u in USERNAMES:
        info = (fetched.get("users") or {}).get(u) or {}
        games = info.get("games") or []
        games = games[-GAMES_PER_USER:]
        print(f"\n📦 Loaded {len(games)} games from {INPUT_JSON} for {u}", flush=True)

        for g in games:
            pgn = g.get("pgn", "")
            if not pgn:
                continue
            white = (g.get("white") or {}).get("username", "")
            black = (g.get("black") or {}).get("username", "")
            url = g.get("url", "") or g.get("game_url", "") or ""
            tasks.append(
                Task(
                    username=u,
                    game_index=game_counter,
                    pgn=pgn,
                    white_player=white,
                    black_player=black,
                    game_url=url,
                )
            )
            game_counter += 1

    if not tasks:
        print("❌ No tasks to analyze (no PGNs fetched).", flush=True)
        return

    # ---- CSV writer ----
    fieldnames = [
        "username",
        "game_url",
        "game_index",
        "event_index",
        "opportunity_kind",  # "cp" or "mate"
        "opportunity_cp",    # int or empty
        "mate_in",           # int or empty
        "target_pawns",
        "t_turns_engine",
        "converted_actual",
        "t_turns_actual",
        "opponent_move_ply_index",
        "opponent_move_san",
        "opponent_move_uci",
        "best_reply_san",
        "best_reply_uci",
        "fen_before",
        "fen_after",
        "pv_moves",
        "pv_evals",
        "eval_before",
        "white_player",
        "black_player",
        "player_color",
        "time_control",
        "game_result",
        "end_time",
    ]

    # Ensure incremental output
    csv_file = open(OUTPUT_CSV, "w", newline="", encoding="utf-8")
    writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
    writer.writeheader()
    csv_file.flush()

    # ---- Run pool ----
    start = time.time()
    completed = 0
    total = len(tasks)
    opp_total = 0
    opp_cp = 0
    opp_mate = 0
    missed_total = 0

    # Track worker pids for per-worker stats
    worker_pids: List[int] = []

    def print_monitor_line():
        level, free_pct = get_memory_pressure_macos()
        # Map the old "max RAM %" idea to a free % threshold:
        # if max_ram_pct is 80, then min free % is 20.
        min_free_pct = max(0.0, 100.0 - max_ram_pct)
        free_str = "n/a" if free_pct is None else f"{free_pct:.1f}%"
        line = f"🧠 Memory pressure: {level} | free: {free_str} (kill if < {min_free_pct:.1f}% or Warning/Critical)"
        if worker_pids:
            parts = []
            for pid in worker_pids:
                rss, cpu = get_tree_stats(pid)
                parts.append(f"pid {pid}: {rss:.0f}MB {cpu:.0f}%")
            line += " | " + " ; ".join(parts)
        print(line, flush=True)
        # Return kill decision inputs
        return level, free_pct

    with ProcessPoolExecutor(max_workers=max_workers, initializer=_worker_init) as ex:
        futures = {ex.submit(_analyze_task, t): t for t in tasks}

        # Capture worker pids after pool starts by looking for child pids of this process.
        # This isn't perfect, but works well on macOS where the pool spawns children.
        time.sleep(1.0)
        worker_pids = get_children_pids(os.getpid())

        last_monitor = 0.0

        try:
            for fut in as_completed(futures):
                now = time.time()
                if now - last_monitor >= monitor_interval:
                    last_monitor = now
                    level, free_pct = print_monitor_line()
                    min_free_pct = max(0.0, 100.0 - max_ram_pct)
                    kill_for_pressure = level in ("Warning", "Critical")
                    kill_for_free = (free_pct is not None) and (free_pct < min_free_pct)
                    if kill_for_pressure or kill_for_free:
                        reason = []
                        if kill_for_pressure:
                            reason.append(f"pressure={level}")
                        if kill_for_free:
                            reason.append(f"free={free_pct:.1f}% < {min_free_pct:.1f}%")
                        reason_str = ", ".join(reason) if reason else "threshold"
                        print(f"🛑 Memory safety trigger ({reason_str}) — killing entire run for safety.", flush=True)
                        _kill_pool(ex)
                        # Hard kill any remaining worker children
                        for pid in worker_pids:
                            try:
                                os.kill(pid, signal.SIGTERM)
                            except Exception:
                                pass
                        raise SystemExit(2)

                task, opps = fut.result()
                completed += 1

                # Log which game
                opp_name = (
                    task.black_player if task.white_player.lower() == task.username.lower() else task.white_player
                )
                print(f"\n🎮 {completed}/{total}: {task.username} vs {opp_name}", flush=True)
                print(f"  Opportunities: {len(opps)}", flush=True)

                for row in opps:
                    # Normalize empty values for CSV
                    if row.get("opportunity_cp") is None:
                        row["opportunity_cp"] = ""
                    if row.get("mate_in") is None:
                        row["mate_in"] = ""
                    if row.get("t_turns_actual") is None:
                        row["t_turns_actual"] = ""

                    writer.writerow({k: row.get(k, "") for k in fieldnames})

                csv_file.flush()

                # Totals
                opp_total += len(opps)
                for o in opps:
                    if o.get("converted_actual", 0) == 0:
                        missed_total += 1
                    if o.get("opportunity_kind") == "mate":
                        opp_mate += 1
                    else:
                        opp_cp += 1

                elapsed = time.time() - start
                rate = completed / elapsed if elapsed > 0 else 0
                eta = (total - completed) / rate if rate > 0 else 0
                print(
                    f"  Totals: {opp_total} opps ({missed_total} missed) | cp={opp_cp} mate={opp_mate} | "
                    f"elapsed {elapsed/60:.1f}m | ETA {eta/60:.1f}m",
                    flush=True,
                )

        finally:
            csv_file.close()

    print("\n✅ DONE", flush=True)
    print(f"Output: {OUTPUT_CSV}", flush=True)


if __name__ == "__main__":
    main()



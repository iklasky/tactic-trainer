"""
AWS Batch + S3 helpers for tactic-trainer.

This module is the ONLY place that knows about AWS.  app_v2.py calls:

    job_id = batch.submit_analysis(username, games, conn)

and then polls:

    status = batch.get_job_status(job_id, conn)

──────────────────────────────────────────────────────────────────────────────
Required env vars (set in Sevalla / .env):
  S3_BUCKET           tactic-trainer-manifests-prod  (or whatever you named it)
  BATCH_JOB_QUEUE     tactic-trainer-queue
  BATCH_JOB_DEF       tactic-trainer-worker-def      (Batch will use latest ACTIVE revision)
  AWS_DEFAULT_REGION  us-east-2  (or set via AWS_REGION / IAM role on the host)

Optional:
  BATCH_ARRAY_MAX     max Batch array size (default 500 — one slot per game)
──────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any, Dict, List, Optional

import boto3

# ── Config from env ────────────────────────────────────────────────────────
S3_BUCKET       = os.environ.get("S3_BUCKET", "tactic-trainer-manifests-prod")
JOB_QUEUE       = os.environ.get("BATCH_JOB_QUEUE", "tactic-trainer-queue")
JOB_DEFINITION  = os.environ.get("BATCH_JOB_DEF",   "tactic-trainer-worker-def")
BATCH_ARRAY_MAX = int(os.environ.get("BATCH_ARRAY_MAX", "500"))

# AWS minimum array size is 2; single-game requests fall back to a regular job
_BATCH_MIN_ARRAY = 2


# ── Public API ─────────────────────────────────────────────────────────────

def submit_analysis(username: str, games: List[Dict[str, str]], conn) -> str:
    """
    Upload a manifest to S3, create a tt_jobs row, submit an AWS Batch
    array job, and return the job_id (UUID string).

    `games` is a list of dicts that MUST have at least:
        {"url": "<chess.com game URL>", "pgn": "<PGN string>"}

    Additional keys (e.g. "elo") are preserved in the manifest and
    available to the worker but currently unused by analysis logic.

    This function is intentionally source-agnostic: the caller decides
    how to populate `games` (chess.com API, database, local file, …).
    """
    job_id      = str(uuid.uuid4())
    total_games = len(games)

    # ── 1. Build and upload manifest ───────────────────────────────────────
    manifest = {
        "job_id":   job_id,
        "username": username,
        "games":    games,           # [{url, pgn, ...}, ...]
    }
    s3_key = f"manifests/{job_id}.json"
    s3_uri = f"s3://{S3_BUCKET}/{s3_key}"

    s3 = boto3.client("s3")
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=s3_key,
        Body=json.dumps(manifest, ensure_ascii=False).encode("utf-8"),
        ContentType="application/json",
    )

    # ── 2. Insert tt_jobs row (status = 'pending') ─────────────────────────
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tt_jobs (job_id, username, manifest_s3_uri, total_games)
            VALUES (%s, %s, %s, %s)
            """,
            (job_id, username, s3_uri, total_games),
        )
    conn.commit()

    # ── 3. Submit Batch array job ──────────────────────────────────────────
    batch   = boto3.client("batch")
    # Batch array size must be >= 2.  If only 1 game, still submit array of 1
    # (worker checks ARRAY_INDEX >= total and exits cleanly for the spare slot).
    array_size = max(total_games, _BATCH_MIN_ARRAY)
    # Cap at account max (configurable, default 500)
    array_size = min(array_size, BATCH_ARRAY_MAX)

    response = batch.submit_job(
        jobName=f"tt-{username[:20]}-{job_id[:8]}",
        jobQueue=JOB_QUEUE,
        jobDefinition=JOB_DEFINITION,
        arrayProperties={"size": array_size},
        containerOverrides={
            "environment": [
                {"name": "JOB_ID",           "value": job_id},
                {"name": "MANIFEST_S3_URI",  "value": s3_uri},
            ]
        },
    )

    batch_job_id = response["jobId"]

    # ── 4. Store AWS Batch job ID for observability ───────────────────────
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE tt_jobs SET batch_job_id = %s WHERE job_id = %s",
            (batch_job_id, job_id),
        )
    conn.commit()

    return job_id


def get_job_status(job_id: str, conn) -> Optional[Dict[str, Any]]:
    """
    Return current progress for a job_id straight from Postgres.
    Returns None if the job_id is unknown.

    Shape:
        {
          "job_id":        str,
          "username":      str,
          "status":        "pending" | "running" | "completed" | "failed",
          "total_games":   int,
          "games_done":    int,
          "games_failed":  int,
          "pct_done":      float,   # 0–100
        }
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT job_id, username, status, total_games, games_done, games_failed
              FROM tt_jobs
             WHERE job_id = %s
            """,
            (job_id,),
        )
        row = cur.fetchone()

    if row is None:
        return None

    job_id_db, username, status, total, done, failed = row
    pct = round((done / total * 100) if total else 0, 1)

    return {
        "job_id":       job_id_db,
        "username":     username,
        "status":       status,
        "total_games":  total,
        "games_done":   done,
        "games_failed": failed,
        "pct_done":     pct,
    }

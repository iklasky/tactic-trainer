"""
Local test script — upload a 1-game manifest to S3 and submit a real Batch job.

Usage:
    python3 test_batch_real_game.py

What it does:
  1. Pulls the first game for 'k2f4x' from fetched_games_v5.json
  2. Uploads a manifest to S3 (manifests/<job_id>.json)
  3. Submits an AWS Batch array job (array size 2, slot 0 analyzes the game,
     slot 1 exits cleanly since ARRAY_INDEX >= total)
  4. Prints the job_id and a CloudWatch Logs link to watch progress

After the job finishes (~4 min), check results in your Sevalla Postgres:
    SELECT * FROM tt_games WHERE username = 'k2f4x' LIMIT 20;
    SELECT * FROM tt_opportunities WHERE username = 'k2f4x' LIMIT 20;
    SELECT * FROM tt_jobs WHERE job_id = '<printed job_id>';
"""

import json
import uuid

import boto3

# ── Config ─────────────────────────────────────────────────────────────────
S3_BUCKET      = "tactic-trainer-manifests-prod"
JOB_QUEUE      = "tactic-trainer-queue"
JOB_DEFINITION = "tactic-trainer-worker-def"
REGION         = "us-east-2"
USERNAME       = "k2f4x"
GAME_INDEX     = 0   # which game from fetched_games_v5.json to test with

# ── Load one real game ──────────────────────────────────────────────────────
print("Loading game from fetched_games_v5.json...")
with open("fetched_games_v5.json") as f:
    data = json.load(f)

game_entry = data["users"][USERNAME]["games"][GAME_INDEX]
print(f"  URL : {game_entry['url']}")
print(f"  PGN : {len(game_entry['pgn'])} chars")

# ── Build manifest ──────────────────────────────────────────────────────────
job_id   = str(uuid.uuid4())
manifest = {
    "job_id":   job_id,
    "username": USERNAME,
    "games": [
        {"url": game_entry["url"], "pgn": game_entry["pgn"]}
    ],
}
s3_key = f"manifests/{job_id}.json"
s3_uri = f"s3://{S3_BUCKET}/{s3_key}"

# ── Upload manifest to S3 ───────────────────────────────────────────────────
print(f"\nUploading manifest → {s3_uri}")
s3 = boto3.client("s3", region_name=REGION)
s3.put_object(
    Bucket=S3_BUCKET,
    Key=s3_key,
    Body=json.dumps(manifest, ensure_ascii=False).encode("utf-8"),
    ContentType="application/json",
)
print("  Uploaded.")

# ── Submit Batch array job ──────────────────────────────────────────────────
print(f"\nSubmitting Batch array job (array size 2)...")
batch = boto3.client("batch", region_name=REGION)
resp  = batch.submit_job(
    jobName=f"tt-real-game-test-{job_id[:8]}",
    jobQueue=JOB_QUEUE,
    jobDefinition=JOB_DEFINITION,
    arrayProperties={"size": 2},
    containerOverrides={
        "environment": [
            {"name": "JOB_ID",          "value": job_id},
            {"name": "MANIFEST_S3_URI", "value": s3_uri},
        ]
    },
)

batch_job_id = resp["jobId"]
print(f"  Batch job ID : {batch_job_id}")
print(f"  Our job_id   : {job_id}")

print(f"""
──────────────────────────────────────────────────────────────
Next steps:

1. Watch the job in the AWS Batch console:
   https://us-east-2.console.aws.amazon.com/batch/home?region=us-east-2#jobs

2. It will take ~4 minutes to run (Stockfish analysis).
   Slot 0 analyzes the game. Slot 1 exits immediately (no game for it).

3. When slot 0 succeeds, check CloudWatch Logs for the worker output:
   Log group : /aws/batch/job
   Log stream: tactic-trainer-worker-def/default/<stream id>
   (link is on the child job page under the Logging tab)

4. Check results in your Sevalla Postgres DB:
   SELECT * FROM tt_games WHERE username = '{USERNAME}' LIMIT 20;
   SELECT game_url, opportunity_kind, opportunity_cp
     FROM tt_opportunities
    WHERE username = '{USERNAME}'
    LIMIT 20;

──────────────────────────────────────────────────────────────
""")

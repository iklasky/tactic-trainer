import os
from typing import Optional

import psycopg2

from db_schema import CREATE_SQL


def get_database_url() -> Optional[str]:
    """
    Prefer DATABASE_URL (common on PaaS). Fallback to composing from PG* vars if present.
    """
    url = os.environ.get("DATABASE_URL")
    if url:
        return url

    host = os.environ.get("PGHOST")
    user = os.environ.get("PGUSER")
    password = os.environ.get("PGPASSWORD")
    dbname = os.environ.get("PGDATABASE")
    port = os.environ.get("PGPORT", "5432")

    if not (host and user and password and dbname):
        return None

    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


def db_enabled() -> bool:
    return get_database_url() is not None


def get_conn():
    url = get_database_url()
    if not url:
        raise RuntimeError("Database not configured (set DATABASE_URL or PGHOST/PGUSER/PGPASSWORD/PGDATABASE).")
    # psycopg2 will parse sslmode if included in url query or via PGSSLMODE env var.
    return psycopg2.connect(url)


def ensure_schema() -> None:
    """
    Idempotently create tables/indexes needed by the app.
    Safe to call on every boot.
    """
    if not db_enabled():
        return
    conn = get_conn()
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute(CREATE_SQL)
        conn.commit()
    finally:
        conn.close()



"""
Migration script: Soft Delete for Job Postings
------------------------------------------------
1. Adds `deleted_at` (timestamptz) column to the `jobs` table.
2. Drops the old CASCADE foreign key on `applications.job_id`.
3. Recreates it as ON DELETE RESTRICT (prevents accidental hard-deletes).

Safe to run multiple times (idempotent).
"""

import os
import httpx
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = (os.getenv("SUPABASE_URL") or "").rstrip("/")
SERVICE_KEY = os.getenv("SERVICE_KEY") or os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SERVICE_KEY:
    print("Error: Missing SUPABASE_URL or SERVICE_KEY in .env")
    exit(1)

headers = {
    "apikey": SERVICE_KEY,
    "Authorization": f"Bearer {SERVICE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}


def run_sql(sql, description):
    """Execute raw SQL via PostgREST rpc or direct connection."""
    print(f"  → {description}...")
    response = httpx.post(
        f"{SUPABASE_URL}/rest/v1/rpc/",
        headers=headers,
        json={"query": sql},
        timeout=30.0,
    )
    # PostgREST doesn't expose arbitrary SQL via rpc.
    # We'll use the pg_net extension or fall back to psycopg2.
    return response


def run_sql_via_psycopg2(sql, description):
    """Execute raw SQL via psycopg2 direct connection."""
    import psycopg2

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        db_host = os.getenv("DB_HOST", "localhost")
        db_port = os.getenv("DB_PORT", "5432")
        db_name = os.getenv("DB_NAME", "postgres")
        db_user = os.getenv("DB_USER", "postgres")
        db_pass = os.getenv("DB_PASSWORD", "")
        db_url = f"postgresql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"

    print(f"  > {description}...")
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(sql)
    cur.close()
    conn.close()
    print(f"    OK")


def main():
    print("=" * 60)
    print("Migration: Soft Delete for Job Postings")
    print("=" * 60)

    # Step 1: Add deleted_at column
    print("\n[1/3] Adding 'deleted_at' column to jobs table...")
    run_sql_via_psycopg2(
        """
        ALTER TABLE public.jobs
        ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ DEFAULT NULL;
        """,
        "ADD COLUMN deleted_at",
    )

    # Step 2: Drop old CASCADE foreign key
    print("\n[2/3] Dropping old CASCADE foreign key on applications.job_id...")
    run_sql_via_psycopg2(
        """
        ALTER TABLE public.applications
        DROP CONSTRAINT IF EXISTS applications_job_id_fkey;
        """,
        "DROP CONSTRAINT applications_job_id_fkey",
    )

    # Step 3: Recreate as ON DELETE RESTRICT
    print("\n[3/3] Recreating foreign key as ON DELETE RESTRICT...")
    run_sql_via_psycopg2(
        """
        ALTER TABLE public.applications
        ADD CONSTRAINT applications_job_id_fkey
        FOREIGN KEY (job_id) REFERENCES public.jobs(id) ON DELETE RESTRICT;
        """,
        "ADD CONSTRAINT ON DELETE RESTRICT",
    )

    print("\n" + "=" * 60)
    print("Migration complete!")
    print("  • jobs.deleted_at column added")
    print("  • applications.job_id FK changed to ON DELETE RESTRICT")
    print("  • Deleting a job with applications will now be BLOCKED")
    print("  • Use soft delete (SET deleted_at) instead")
    print("=" * 60)


if __name__ == "__main__":
    main()

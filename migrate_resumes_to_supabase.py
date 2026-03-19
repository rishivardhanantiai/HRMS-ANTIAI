import os
import mimetypes
import tempfile
from pathlib import Path

import httpx
from dotenv import load_dotenv
from werkzeug.utils import secure_filename

from utils.db import get_db, release_db


def build_local_resume_dirs(project_root):
    dirs = [project_root / "uploads" / "resumes"]
    if os.getenv("VERCEL") == "1":
        dirs.append(Path(tempfile.gettempdir()) / "uploads" / "resumes")
    return dirs


def find_local_resume_file(filename, local_dirs):
    for local_dir in local_dirs:
        candidate = local_dir / filename
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def upload_file_to_supabase(local_path, object_key, bucket, supabase_url, supabase_key):
    mime_type, _ = mimetypes.guess_type(str(local_path))
    content_type = mime_type or "application/octet-stream"
    upload_url = f"{supabase_url}/storage/v1/object/{bucket}/{object_key}"
    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": content_type,
        "x-upsert": "false",
    }

    with open(local_path, "rb") as f:
        response = httpx.post(upload_url, content=f.read(), headers=headers, timeout=30.0)

    if response.status_code not in (200, 201):
        raise RuntimeError(f"Upload failed ({response.status_code}): {response.text[:200]}")

    return f"{supabase_url}/storage/v1/object/public/{bucket}/{object_key}"


def is_legacy_local_resume_url(value):
    if not value:
        return False
    normalized = str(value).strip()
    if normalized.startswith("http://") or normalized.startswith("https://"):
        return False
    return True


def extract_filename(legacy_value):
    return os.path.basename(str(legacy_value).strip())


def main():
    load_dotenv()

    supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    supabase_key = os.getenv("SUPABASE_KEY")
    bucket = os.getenv("SUPABASE_RESUME_BUCKET", "resumes")

    if not supabase_url or not supabase_key:
        raise RuntimeError("Missing SUPABASE_URL or SUPABASE_KEY in environment")

    project_root = Path(__file__).resolve().parent
    local_dirs = build_local_resume_dirs(project_root)

    conn, cur = get_db(True)
    try:
        cur.execute(
            """
            SELECT id, resume_url
            FROM applications
            WHERE resume_url IS NOT NULL
            ORDER BY id ASC
            """
        )
        rows = cur.fetchall()

        total = 0
        migrated = 0
        skipped_http = 0
        missing_file = 0
        failed_upload = 0

        for row in rows:
            total += 1
            app_id = row["id"]
            resume_url = row.get("resume_url")

            if not is_legacy_local_resume_url(resume_url):
                skipped_http += 1
                continue

            filename = secure_filename(extract_filename(resume_url))
            if not filename:
                missing_file += 1
                print(f"[missing] id={app_id} invalid filename from resume_url={resume_url}")
                continue

            local_file = find_local_resume_file(filename, local_dirs)
            if not local_file:
                missing_file += 1
                print(f"[missing] id={app_id} file not found: {filename}")
                continue

            object_key = f"applications/migrated_{app_id}_{filename}"
            try:
                public_url = upload_file_to_supabase(
                    local_file,
                    object_key,
                    bucket,
                    supabase_url,
                    supabase_key,
                )
            except Exception as exc:
                failed_upload += 1
                print(f"[error] id={app_id} upload failed: {exc}")
                continue

            cur.execute(
                "UPDATE applications SET resume_url = %s WHERE id = %s",
                (public_url, app_id),
            )
            migrated += 1
            print(f"[ok] id={app_id} migrated -> {public_url}")

        conn.commit()

        print("\nMigration complete")
        print(f"Total scanned: {total}")
        print(f"Already remote (http/https): {skipped_http}")
        print(f"Migrated: {migrated}")
        print(f"Missing local file: {missing_file}")
        print(f"Failed uploads: {failed_upload}")
    finally:
        release_db(conn, cur)


if __name__ == "__main__":
    main()

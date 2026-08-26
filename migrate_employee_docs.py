import os
from utils.db import get_db, release_db
import urllib.parse

def migrate():
    conn, cur = get_db(True)
    try:
        # Add new columns if they don't exist
        print("Adding new columns...")
        cur.execute("""
            ALTER TABLE employee_documents 
            ADD COLUMN IF NOT EXISTS file_name TEXT,
            ADD COLUMN IF NOT EXISTS file_path TEXT,
            ADD COLUMN IF NOT EXISTS bucket_name TEXT,
            ADD COLUMN IF NOT EXISTS public_url TEXT,
            ADD COLUMN IF NOT EXISTS mime_type TEXT,
            ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'active',
            ADD COLUMN IF NOT EXISTS uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
        """)
        
        # Migrate existing data
        print("Migrating existing data...")
        cur.execute("SELECT id, file_url FROM employee_documents WHERE file_path IS NULL")
        records = cur.fetchall()
        for rec in records:
            file_url = rec["file_url"]
            if not file_url:
                continue
                
            # Example URL: https://bbyetktijihwgocynbqu.supabase.co/storage/v1/object/public/resumes/documents/emp_1_1781283597_daily_report_2.pdf
            # Split by /storage/v1/object/public/
            parts = file_url.split("/storage/v1/object/public/")
            if len(parts) == 2:
                path_parts = parts[1].split("/", 1)
                if len(path_parts) == 2:
                    bucket_name = path_parts[0]
                    file_path = path_parts[1]
                    file_name = file_path.split("/")[-1]
                    # decode URL encoded characters in file_name if any
                    file_name = urllib.parse.unquote(file_name)
                    
                    cur.execute("""
                        UPDATE employee_documents 
                        SET bucket_name = %s, file_path = %s, file_name = %s, public_url = %s 
                        WHERE id = %s
                    """, (bucket_name, file_path, file_name, file_url, rec["id"]))
        
        conn.commit()
        print("Migration successful.")
    except Exception as e:
        print("Error during migration:", e)
        conn.rollback()
    finally:
        release_db(conn, cur)

if __name__ == "__main__":
    migrate()

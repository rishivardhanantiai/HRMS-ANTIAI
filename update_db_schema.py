import sys
from utils.db import get_db

def update_schema():
    conn, cur = get_db()
    try:
        # Create letter_template_versions table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS letter_template_versions (
                id SERIAL PRIMARY KEY,
                template_id INTEGER REFERENCES letter_templates(id) ON DELETE CASCADE,
                version_number INTEGER NOT NULL,
                template_content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_by VARCHAR(255)
            )
        """)

        # Alter generated_letters
        cur.execute("ALTER TABLE generated_letters ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'Generated'")
        cur.execute("ALTER TABLE generated_letters ADD COLUMN IF NOT EXISTS pdf_path TEXT")
        cur.execute("ALTER TABLE generated_letters ADD COLUMN IF NOT EXISTS template_id INTEGER")
        
        conn.commit()
        print("Schema updated successfully!")
    except Exception as e:
        print("Error:", e)
        conn.rollback()
    finally:
        cur.close()
        # db_pool.putconn(conn) might be needed, but since it's a one-off script, closing is fine.

if __name__ == '__main__':
    update_schema()

import sys
sys.path.append('.')
from utils.db import get_db, release_db

def upgrade():
    conn, cur = get_db()
    try:
        # Check if column exists
        cur.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name='leave_types' AND column_name='annual_entitlement'
        """)
        exists = cur.fetchone()
        if not exists:
            print("Adding column annual_entitlement to leave_types...")
            cur.execute("ALTER TABLE leave_types ADD COLUMN annual_entitlement INTEGER DEFAULT 15")
            conn.commit()
            print("Column added successfully!")
        else:
            print("Column annual_entitlement already exists in leave_types.")
    except Exception as e:
        print("Error upgrading leave_types table:", e)
        conn.rollback()
    finally:
        release_db(conn, cur)

if __name__ == "__main__":
    upgrade()

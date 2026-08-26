import sqlite3

def init_db():
    conn = sqlite3.connect("hr_management.db")
    cur = conn.cursor()

    # HR users table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS hr_users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL
    )
    """)

    # Default HR user
    cur.execute("""
    INSERT OR IGNORE INTO hr_users (email, password)
    VALUES (?, ?)
    """, ("hr@company.com", "admin123"))

    conn.commit()
    conn.close()

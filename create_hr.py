import sqlite3
from werkzeug.security import generate_password_hash

conn = sqlite3.connect("hr_management.db")
cur = conn.cursor()

email = "hr@company.com"
password = generate_password_hash("admin123")

cur.execute(
    "INSERT OR IGNORE INTO hr_users (email, password) VALUES (?, ?)",
    (email, password)
)

conn.commit()
conn.close()

print("HR user created")

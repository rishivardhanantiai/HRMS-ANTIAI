import os
from utils.db import get_db, release_db

conn, cur = get_db(True)
cur.execute("SELECT id, file_url FROM employee_documents LIMIT 5;")
rows = cur.fetchall()
for row in rows:
    print(row)
release_db(conn, cur)

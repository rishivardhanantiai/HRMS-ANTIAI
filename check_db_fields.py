import os
from utils.db import get_db, release_db

conn, cur = get_db(True)
cur.execute("SELECT id, public_url, file_url, bucket_name, file_path FROM employee_documents WHERE id=1")
row = cur.fetchone()
print(row)
release_db(conn, cur)

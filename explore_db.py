import sys
import json
from utils.db import get_db

def explore():
    conn, cur = get_db(True)
    try:
        tables = ['letter_templates', 'generated_letters', 'employee_documents', 'company_settings']
        schema = {}
        for table in tables:
            cur.execute(f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name = '{table}'")
            schema[table] = cur.fetchall()
        print(json.dumps(schema, indent=2))
    finally:
        release_db(conn, cur)

if __name__ == '__main__':
    explore()

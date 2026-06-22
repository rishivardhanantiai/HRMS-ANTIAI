import psycopg2
from utils.db import get_db, release_db

conn, cur = get_db(True)
try:
    # Get all tables
    cur.execute("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public'
    """)
    tables = [row['table_name'] for row in cur.fetchall()]
    print("TABLES:", tables)
    
    # Get details for key tables
    for table in ['hrms_employees', 'hrms_leave_requests', 'hrms_employee_documents', 'employee_exits', 'employee_fnf_records', 'employee_salary', 'salary_structures']:
        if table in tables:
            cur.execute(f"""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = '{table}'
            """)
            print(f"\nTABLE {table}:")
            for col in cur.fetchall():
                print(f"  {col['column_name']} ({col['data_type']})")
finally:
    release_db(conn, cur)

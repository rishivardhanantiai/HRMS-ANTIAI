import os
from dotenv import load_dotenv
import psycopg2

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

def run_migration():
    if not DATABASE_URL:
        print("DATABASE_URL not found in .env")
        return
    
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        
        with open("update_letters_schema.sql", "r") as f:
            sql = f.read()
            
        cur.execute(sql)
        conn.commit()
        print("Migration successful")
        
    except Exception as e:
        print("Migration failed:", e)
    finally:
        if conn:
            cur.close()
            conn.close()

if __name__ == "__main__":
    run_migration()

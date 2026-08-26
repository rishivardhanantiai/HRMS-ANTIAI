import psycopg2, os
from dotenv import load_dotenv

load_dotenv()
conn = psycopg2.connect(os.getenv('DATABASE_URL'))
cur = conn.cursor()
cur.execute("UPDATE company_settings SET company_website = 'https://www.antiai.ltd/', company_name = 'Anti.ai' WHERE id = 1")
conn.commit()
conn.close()

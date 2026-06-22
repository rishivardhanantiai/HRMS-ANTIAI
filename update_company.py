import psycopg2, os
from dotenv import load_dotenv
load_dotenv()
conn = psycopg2.connect(os.getenv("DATABASE_URL"))
cur = conn.cursor()
cur.execute("""
    UPDATE company_settings SET 
        company_name='ANTI.AI PRIVATE LIMITED', 
        company_address='73 ROSE VILLA RAJENDRA NAGAR BHARATPUR RAJASTHAN, Rajasthan, 321001', 
        company_email='hr@antlai.com', 
        company_phone='+91-0000000000', 
        company_website='www.antlai.com'
    WHERE id=1
""")
conn.commit()
print("Company settings updated")
cur.close()
conn.close()

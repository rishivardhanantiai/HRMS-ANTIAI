import os
import pymysql
pymysql.install_as_MySQLdb()
import psycopg2
import psycopg2.extras
from psycopg2 import pool
from dotenv import load_dotenv

load_dotenv(override=True)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
if DATABASE_URL.startswith("xpostgresql://"):
    DATABASE_URL = DATABASE_URL[1:]

db_pool = None

# =========================
# INIT CONNECTION POOL
# =========================
def init_db_pool():
    global db_pool
    if not db_pool and DATABASE_URL:
        try:
            db_pool = pool.SimpleConnectionPool(
                1,
                20,
                DATABASE_URL
            )
        except Exception as e:
            try:
                db_pool = pool.SimpleConnectionPool(
                    1,
                    20,
                    dsn=DATABASE_URL
                )
            except Exception as pool_err:
                err_msg = str(pool_err)
                import re
                cleaned_err = re.sub(r'(x?postgresql://[^\s"\']+)', '[DATABASE_URL]', err_msg)
                print("Database pool init error:", cleaned_err)
                db_pool = None

# =========================
# GET DATABASE CONNECTION
# =========================
def get_db(dict_cursor=False):
    init_db_pool()
    conn = None
    if db_pool:
        try:
            conn = db_pool.getconn()
        except Exception as e:
            print("Pool getconn error, trying direct connect:", e)
            conn = None
            
    if not conn and DATABASE_URL:
        try:
            conn = psycopg2.connect(DATABASE_URL)
        except Exception as e:
            err_msg = str(e)
            import re
            cleaned_err = re.sub(r'(x?postgresql://[^\s"\']+)', '[DATABASE_URL]', err_msg)
            print("Direct DB connection error:", cleaned_err)
            return None, None

    if not conn:
        return None, None

    if dict_cursor:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    else:
        cur = conn.cursor()

    #  CRITICAL FIX FOR SUPABASE SCHEMA CONFLICT
    if os.getenv("TESTING") == "true":
        cur.execute("SET search_path TO pytest_schema")
    else:
        cur.execute("SET search_path TO public")

    return conn, cur

# =========================
# RELEASE CONNECTION
# =========================
def release_db(conn, cur):
    if cur:
        try:
            cur.close()
        except Exception:
            pass
    if conn and db_pool:
        try:
            db_pool.putconn(conn)
        except Exception:
            pass

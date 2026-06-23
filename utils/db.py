import os
import pymysql
pymysql.install_as_MySQLdb()
import psycopg2
import psycopg2.extras
from psycopg2 import pool
from dotenv import load_dotenv

load_dotenv(override=True)

DATABASE_URL = os.getenv("DATABASE_URL")

db_pool = None

# =========================
# INIT CONNECTION POOL
# =========================
def init_db_pool():
    global db_pool
    if not db_pool:
        try:
            db_pool = pool.SimpleConnectionPool(
                minconn=1,
                maxconn=20,
                dsn=DATABASE_URL,
                sslmode="require"
            )
        except Exception as e:
            print("Database pool init error:", e)
            db_pool = None

# =========================
# GET DATABASE CONNECTION
# =========================
def get_db(dict_cursor=False):
    init_db_pool()
    if not db_pool:
        return None, None
    
    try:
        conn = db_pool.getconn()
    except Exception as e:
        print("Database connection error:", e)
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

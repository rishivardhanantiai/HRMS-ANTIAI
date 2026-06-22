import os
import pymysql
pymysql.install_as_MySQLdb()
import psycopg2
import psycopg2.extras
from psycopg2 import pool
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

db_pool = None

# =========================
# INIT CONNECTION POOL
# =========================
def init_db_pool():
    global db_pool
    if not db_pool:
        db_pool = pool.SimpleConnectionPool(
            minconn=1,
            maxconn=20,
            dsn=DATABASE_URL,
            sslmode="require"
        )

# =========================
# GET DATABASE CONNECTION
# =========================
def get_db(dict_cursor=False):
    init_db_pool()
    conn = db_pool.getconn()

    if dict_cursor:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    else:
        cur = conn.cursor()

    #  CRITICAL FIX FOR SUPABASE SCHEMA CONFLICT
    cur.execute("SET search_path TO public")

    return conn, cur

# =========================
# RELEASE CONNECTION
# =========================
def release_db(conn, cur):
    cur.close()
    db_pool.putconn(conn)

import os
import psycopg2
import psycopg2.extras
from psycopg2 import pool
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

db_pool = None

def init_db_pool():
    global db_pool
    if not db_pool:
        db_pool = pool.SimpleConnectionPool(
            minconn=1,
            maxconn=5,
            dsn=DATABASE_URL,
            sslmode="require"
        )

def get_db(dict_cursor=False):
    init_db_pool()
    conn = db_pool.getconn()
    if dict_cursor:
        return conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    return conn, conn.cursor()

def release_db(conn, cur):
    cur.close()
    db_pool.putconn(conn)

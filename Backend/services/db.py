import psycopg2
from psycopg2.extras import RealDictCursor
from config import Config

def get_connection():
    try:
        conn = psycopg2.connect(
            dbname=Config.DB_NAME,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD,
            host=Config.DB_HOST,
            port=Config.DB_PORT
        )
        return conn
    except Exception as e:
        print("Error al conectar a la base de datos:", e)
        return None

def fetch_all(query, params=None):
    conn = get_connection()
    if conn is None:
        return []
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params or ())
            result = cur.fetchall()
        conn.close()
        return result
    except Exception as e:
        print("Error al ejecutar fetch_all:", e)
        return []

def fetch_one(query, params=None):
    conn = get_connection()
    if conn is None:
        return None
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params or ())
            result = cur.fetchone()
        conn.close()
        return result
    except Exception as e:
        print("Error al ejecutar fetch_one:", e)
        return None

def execute_query(query, params=None):
    conn = get_connection()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(query, params or ())
        conn.close()
        return True
    except Exception as e:
        print("Error al ejecutar query:", e)
        return False

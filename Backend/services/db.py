import psycopg2
from psycopg2.extras import RealDictCursor
from config import Config # Asegúrate de que Config.DB_NAME, etc., estén definidos aquí

def get_connection():
    """
    Establece y devuelve una conexión a la base de datos PostgreSQL.
    """
    conn = None
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
        print(f"Error al conectar a la base de datos: {e}")
        # No se devuelve la conexión si hay un error
        return None

def fetch_all(query, params=None):
    """
    Ejecuta una consulta SELECT y devuelve todas las filas como una lista de diccionarios.
    """
    conn = get_connection()
    if conn is None:
        return [] # Devuelve una lista vacía si no se puede conectar
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params or ())
            result = cur.fetchall()
        conn.close() # Cierra la conexión después de usarla
        return result
    except Exception as e:
        print(f"Error al ejecutar fetch_all: {e}")
        if conn:
            conn.close() # Asegura que la conexión se cierre incluso en caso de error
        return [] # Devuelve una lista vacía en caso de error

def fetch_one(query, params=None):
    """
    Ejecuta una consulta SELECT y devuelve la primera fila como un diccionario.
    """
    conn = get_connection()
    if conn is None:
        return None # Devuelve None si no se puede conectar
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params or ())
            result = cur.fetchone()
        conn.close() # Cierra la conexión después de usarla
        return result
    except Exception as e:
        print(f"Error al ejecutar fetch_one: {e}")
        if conn:
            conn.close() # Asegura que la conexión se cierre incluso en caso de error
        return None # Devuelve None en caso de error

def execute_query(query, params=None):
    """
    Ejecuta una consulta INSERT, UPDATE o DELETE y devuelve el número de filas afectadas.
    Devuelve False en caso de error de conexión o ejecución.
    """
    conn = get_connection()
    if conn is None:
        return False # Fallo en la conexión a la DB
    try:
        with conn: # Esto maneja el commit/rollback automáticamente al salir del bloque
            with conn.cursor() as cur:
                cur.execute(query, params or ())
                rows_affected = cur.rowcount # Obtiene el número de filas afectadas
        conn.close() # Cierra la conexión después de usarla
        return rows_affected # Retorna el número de filas afectadas (0 o más)
    except Exception as e:
        print(f"Error al ejecutar query: {e}")
        # El 'with conn:' ya maneja el rollback si hay una excepción
        if conn:
            conn.close() # Asegura que la conexión se cierre incluso en caso de error
        return False # Indica que la operación falló

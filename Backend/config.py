import os
import psycopg2

class Config:
    # Configuración general
    DEBUG = True
    TESTING = False

    # Base de datos PostgreSQL
    DB_HOST = os.environ.get("DB_HOST", "localhost")
    DB_PORT = os.environ.get("DB_PORT", "5432")
    DB_NAME = os.environ.get("DB_NAME", "geant_network")
    DB_USER = os.environ.get("DB_USER", "geant_user")
    DB_PASSWORD = os.environ.get("DB_PASSWORD", "geant")

    # String de conexión
    @staticmethod
    def get_db_uri():
        return f"dbname={Config.DB_NAME} user={Config.DB_USER} password={Config.DB_PASSWORD} host={Config.DB_HOST} port={Config.DB_PORT}"

# Conexión directa reutilizable
def get_db_connection():
    return psycopg2.connect(Config.get_db_uri())

import os
import psycopg2

class Config:
    # Configuración general
    DEBUG = True
    TESTING = False

    # Base de datos PostgreSQL
    DB_HOST     = os.environ.get("DB_HOST", "localhost")
    DB_PORT     = os.environ.get("DB_PORT", "5432")
    DB_NAME     = os.environ.get("DB_NAME", "geant_network")
    DB_USER     = os.environ.get("DB_USER", "geant_user")
    DB_PASSWORD = os.environ.get("DB_PASSWORD", "geant")

    # URL (o IP:PUERTO) de tu agente Mininet
    MININET_AGENT_URL = os.environ.get("MININET_AGENT_URL", "http://192.168.18.208:5002")

    # String de conexión a la BD
    @staticmethod
    def get_db_uri():
        return (
            f"dbname={Config.DB_NAME} "
            f"user={Config.DB_USER} "
            f"password={Config.DB_PASSWORD} "
            f"host={Config.DB_HOST} "
            f"port={Config.DB_PORT}"
        )

# Conexión directa reutilizable
def get_db_connection():
    return psycopg2.connect(Config.get_db_uri())

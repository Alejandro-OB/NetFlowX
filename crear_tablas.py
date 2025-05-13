import psycopg2

# Conexión a la base de datos
def get_db_connection():
    return psycopg2.connect(
        dbname="geant_network",
        user="geant_user",
        password="geant",
        host="localhost",
        port="5432"
    )

def crear_tablas():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Crear tabla `switches`
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS switches (
            id_switch SERIAL PRIMARY KEY,
            nombre VARCHAR(255) NOT NULL
        )
    """)

    # Crear tabla `enlaces`
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS enlaces (
            id_enlace SERIAL PRIMARY KEY,
            id_origen INT REFERENCES switches(id_switch),
            id_destino INT REFERENCES switches(id_switch),
            ancho_banda INT
        )
    """)

    # Crear tabla `hosts`
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hosts (
            id_host SERIAL PRIMARY KEY,
            nombre VARCHAR(255) NOT NULL,
            switch_asociado INT REFERENCES switches(id_switch),
            es_servidor BOOLEAN
        )
    """)

    # Crear tabla `configuracion`
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS configuracion (
            id_configuracion SERIAL PRIMARY KEY,
            algoritmo_balanceo VARCHAR(255),
            algoritmo_enrutamiento VARCHAR(255),
            fecha_activacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Crear tabla `estadisticas`
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS estadisticas (
            id_estadistica SERIAL PRIMARY KEY,
            id_host INT REFERENCES hosts(id_host),
            tipo VARCHAR(255),
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Crear tabla `pesos_vlc`
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pesos_vlc (
            id_host INT REFERENCES hosts(id_host),
            peso INT
        )
    """)

    # Crear tabla `reglas`
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reglas (
            id SERIAL PRIMARY KEY,
            dpid INTEGER NOT NULL,
            rule_id INTEGER UNIQUE NOT NULL CHECK(rule_id > 0),
            priority INTEGER DEFAULT 1 CHECK(priority > 0),
            eth_type INTEGER NOT NULL CHECK(eth_type > 0),
            ip_proto INTEGER CHECK(ip_proto IS NULL OR ip_proto >= 0),
            ipv4_src TEXT,
            ipv4_dst TEXT,
            tcp_src INTEGER CHECK(tcp_src IS NULL OR tcp_src > 0),
            tcp_dst INTEGER CHECK(tcp_dst IS NULL OR tcp_dst > 0),
            in_port INTEGER CHECK(in_port IS NULL OR in_port > 0),
            actions TEXT NOT NULL CHECK(actions <> '')
        )
    """)

    # Crear tabla `logs`
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id SERIAL PRIMARY KEY,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            dpid INTEGER,
            rule_id INTEGER CHECK(rule_id > 0),
            action TEXT CHECK(action IN ('INSTALADA', 'MODIFICADA', 'ELIMINADA')),
            priority INTEGER CHECK(priority > 0),
            eth_type INTEGER CHECK(eth_type > 0),
            ip_proto INTEGER CHECK(ip_proto IS NULL OR ip_proto >= 0),
            ipv4_src TEXT,
            ipv4_dst TEXT,
            tcp_src INTEGER CHECK(tcp_src IS NULL OR tcp_src > 0),
            tcp_dst INTEGER CHECK(tcp_dst IS NULL OR tcp_dst > 0),
            in_port INTEGER CHECK(in_port IS NULL OR in_port > 0),
            actions TEXT CHECK(actions <> '')
        )
    """)

    conn.commit()
    cursor.close()
    conn.close()
    print("✅ Tablas creadas correctamente.")

# Ejecutar el script de creación de tablas
if __name__ == "__main__":
    crear_tablas()

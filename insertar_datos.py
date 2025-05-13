import psycopg2

# Datos base
ciudades = [
    'London', 'Paris', 'Amsterdam', 'Frankfurt', 'Madrid', 'Lisbon',
    'Rome', 'Zurich', 'Vienna', 'Prague', 'Budapest', 'Warsaw',
    'Athens', 'Sofia', 'Bucharest', 'Brussels', 'Copenhagen',
    'Stockholm', 'Helsinki', 'Dublin', 'Oslo', 'Tallinn', 'Riga'
]

# Coordenadas de cada ciudad
coordenadas = {
    'London': (-0.1, 51.5), 'Paris': (2.35, 48.85), 'Amsterdam': (4.9, 52.37),
    'Frankfurt': (8.7, 50.1), 'Madrid': (-3.7, 40.4), 'Lisbon': (-9.1, 38.7),
    'Rome': (12.5, 41.9), 'Zurich': (8.5, 47.4), 'Vienna': (16.4, 48.2),
    'Prague': (14.4, 50.1), 'Budapest': (19.0, 47.5), 'Warsaw': (21.0, 52.2),
    'Athens': (23.7, 37.9), 'Sofia': (23.3, 42.7), 'Bucharest': (26.1, 44.4),
    'Brussels': (4.3, 50.8), 'Copenhagen': (12.6, 55.7), 'Stockholm': (18.1, 59.3),
    'Helsinki': (24.9, 60.2), 'Dublin': (-6.2, 53.3), 'Oslo': (10.8, 59.9),
    'Tallinn': (24.7, 59.4), 'Riga': (24.1, 56.9)
}

# Enlaces con ancho de banda
enlaces = [
    ('London', 'Paris', 1000), ('Paris', 'Frankfurt', 1000), ('Amsterdam', 'Frankfurt', 1000),
    ('Frankfurt', 'Vienna', 1000), ('Vienna', 'Budapest', 1000), ('Vienna', 'Rome', 1000),
    ('Rome', 'Zurich', 100), ('Zurich', 'Paris', 100), ('Madrid', 'Lisbon', 100),
    ('Madrid', 'Paris', 1000), ('Brussels', 'Amsterdam', 100), ('Amsterdam', 'Copenhagen', 100),
    ('Copenhagen', 'Stockholm', 100), ('Stockholm', 'Helsinki', 100), ('Tallinn', 'Riga', 100),
    ('Riga', 'Warsaw', 100), ('Warsaw', 'Prague', 100), ('Prague', 'Vienna', 100),
    ('Bucharest', 'Budapest', 100), ('Bucharest', 'Sofia', 100), ('Sofia', 'Athens', 100),
    ('Athens', 'Warsaw', 10), ('Dublin', 'London', 10), ('Oslo', 'Stockholm', 100)
]

# Conexión a PostgreSQL
conn = psycopg2.connect(
    dbname="geant_network",
    user="geant_user",
    password="geant",  
    host="localhost",
    port="5432"
)
cur = conn.cursor()

# Insertar switches con coordenadas
switch_ids = {}
for ciudad in ciudades:
    lat, lon = coordenadas[ciudad]  # Obtener coordenadas
    cur.execute("""
        INSERT INTO switches (nombre, latitud, longitud) 
        VALUES (%s, %s, %s) RETURNING id_switch;
    """, (ciudad, lat, lon))
    switch_ids[ciudad] = cur.fetchone()[0]

# Insertar hosts
host_ids = {}
for i, ciudad in enumerate(ciudades):
    id_switch = switch_ids[ciudad]
    for j in range(2):  # Insertar 2 hosts por ciudad (sin marcar si es servidor)
        nombre_host = f"h{i+1}_{j+1}"
        cur.execute(
            "INSERT INTO hosts (nombre, switch_asociado) VALUES (%s, %s) RETURNING id_host;",
            (nombre_host, id_switch)
        )
        host_ids[nombre_host] = cur.fetchone()[0]

# Insertar enlaces
for origen, destino, bw in enlaces:
    id_origen = switch_ids[origen]
    id_destino = switch_ids[destino]
    cur.execute(
        "INSERT INTO enlaces (id_origen, id_destino, ancho_banda) VALUES (%s, %s, %s);",
        (id_origen, id_destino, bw)
    )

conn.commit()
cur.close()
conn.close()

print("✅ Switches, hosts y enlaces insertados correctamente.")

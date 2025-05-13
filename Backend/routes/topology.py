from flask import Blueprint, jsonify, request
from config import get_db_connection

topology_bp = Blueprint('topology', __name__)

@topology_bp.route('/', methods=['GET'])
def obtener_topologia():
    conn = get_db_connection()
    cur = conn.cursor()

    # Obtener switches con coordenadas
    cur.execute("""
        SELECT id_switch, nombre, longitud, latitud
        FROM switches
        WHERE longitud IS NOT NULL AND latitud IS NOT NULL
    """)
    switches = [
        {
            "id": row[0],
            "nombre": row[1],
            "longitud": row[2],
            "latitud": row[3]
        }
        for row in cur.fetchall()
    ]

    # Obtener enlaces con nombres de switches
    cur.execute("""
        SELECT s1.nombre, s2.nombre, e.ancho_banda
        FROM enlaces e
        JOIN switches s1 ON e.id_origen = s1.id_switch
        JOIN switches s2 ON e.id_destino = s2.id_switch
    """)
    enlaces = [
        {
            "origen": row[0],
            "destino": row[1],
            "ancho_banda": row[2]
        }
        for row in cur.fetchall()
    ]

    cur.close()
    conn.close()

    return jsonify({
        "switches": switches,
        "enlaces": enlaces
    })

@topology_bp.route('/enlace', methods=['POST'])
def crear_enlace():
    data = request.get_json()
    id_origen = data.get("id_origen")
    id_destino = data.get("id_destino")
    ancho_banda = data.get("ancho_banda")

    if not id_origen or not id_destino or not ancho_banda:
        return jsonify({"error": "Datos incompletos"}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO enlaces (id_origen, id_destino, ancho_banda) VALUES (%s, %s, %s)",
            (id_origen, id_destino, ancho_banda)
        )
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"message": "Enlace creado correctamente"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@topology_bp.route('/enlace', methods=['DELETE'])
def eliminar_enlace():
    data = request.get_json()
    origen = data.get("origen")
    destino = data.get("destino")

    if not origen or not destino:
        return jsonify({"error": "Faltan datos"}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            DELETE FROM enlaces
            WHERE (id_origen = (SELECT id_switch FROM switches WHERE nombre = %s)
              AND id_destino = (SELECT id_switch FROM switches WHERE nombre = %s))
               OR (id_origen = (SELECT id_switch FROM switches WHERE nombre = %s)
              AND id_destino = (SELECT id_switch FROM switches WHERE nombre = %s))
        """, (origen, destino, destino, origen))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"message": "Enlace eliminado"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

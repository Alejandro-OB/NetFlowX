# routes/topology.py
from flask import Blueprint, jsonify, request
import psycopg2
from config import Config

topology_bp = Blueprint('topology', __name__)

def get_db_conn():
    return psycopg2.connect(Config.get_db_uri())

@topology_bp.route('', methods=['GET'])
def get_topology():
    """
    Devuelve la lista de switches y enlaces.
    """
    conn = get_db_conn()
    cur = conn.cursor()
    # Switches
    cur.execute("SELECT id_switch, nombre, latitud, longitud FROM switches;")
    switches = [
        {"id": r[0], "nombre": r[1], "latitud": float(r[2]), "longitud": float(r[3])}
        for r in cur.fetchall()
    ]
    # Enlaces
    cur.execute("""
        SELECT s1.nombre AS origen, s2.nombre AS destino, e.ancho_banda
        FROM enlaces e
        JOIN switches s1 ON e.id_origen = s1.id_switch
        JOIN switches s2 ON e.id_destino = s2.id_switch;
    """)
    enlaces = [
        {"origen": r[0], "destino": r[1], "ancho_banda": r[2]}
        for r in cur.fetchall()
    ]
    cur.close()
    conn.close()
    return jsonify({"switches": switches, "enlaces": enlaces})

@topology_bp.route('/enlace', methods=['POST'])
def create_enlace():
    """
    Crea un nuevo enlace. JSON esperado: { id_origen, id_destino, ancho_banda }.
    """
    data = request.get_json() or {}
    try:
        io, id_, bw = int(data.get('id_origen')), int(data.get('id_destino')), int(data.get('ancho_banda'))
        if io <= 0 or id_ <= 0 or bw <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "Parámetros inválidos"}), 400

    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO enlaces (id_origen, id_destino, ancho_banda)
        VALUES (%s, %s, %s)
    """, (io, id_, bw))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"message": f"Enlace {io}→{id_} creado con {bw} Mbps"}), 201

@topology_bp.route('/enlace', methods=['PUT'])
def update_enlace():
    """
    Actualiza el ancho de banda de un enlace existente.
    JSON esperado: { id_origen, id_destino, ancho_banda }.
    """
    data = request.get_json() or {}
    try:
        io, id_, bw = int(data.get('id_origen')), int(data.get('id_destino')), int(data.get('ancho_banda'))
        if io <= 0 or id_ <= 0 or bw <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "Parámetros inválidos"}), 400

    conn = get_db_conn()
    cur = conn.cursor()
    # Intentamos primero como dirección directa, luego invertida
    cur.execute("""
        UPDATE enlaces
        SET ancho_banda = %s
        WHERE (id_origen, id_destino) = (%s, %s)
           OR (id_origen, id_destino) = (%s, %s);
    """, (bw, io, id_, id_, io))
    if cur.rowcount == 0:
        conn.rollback()
        cur.close()
        conn.close()
        return jsonify({"error": "Enlace no encontrado"}), 404
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"message": f"Enlace {io}↔{id_} actualizado a {bw} Mbps"}), 200

@topology_bp.route('/enlace', methods=['DELETE'])
def delete_enlace():
    """
    Elimina un enlace. JSON esperado: { origen, destino } (nombres de switch).
    """
    data = request.get_json() or {}
    ori_name, dst_name = data.get('origen'), data.get('destino')
    if not ori_name or not dst_name:
        return jsonify({"error": "Parámetros inválidos"}), 400

    conn = get_db_conn()
    cur = conn.cursor()
    # Tomamos id_switch de cada nombre
    cur.execute("SELECT id_switch FROM switches WHERE nombre=%s", (ori_name,))
    r1 = cur.fetchone()
    cur.execute("SELECT id_switch FROM switches WHERE nombre=%s", (dst_name,))
    r2 = cur.fetchone()
    if not r1 or not r2:
        return jsonify({"error": "Switch no encontrado"}), 404
    io, id_ = r1[0], r2[0]

    cur.execute("""
        DELETE FROM enlaces
        WHERE (id_origen, id_destino) = (%s, %s)
           OR (id_origen, id_destino) = (%s, %s);
    """, (io, id_, id_, io))
    if cur.rowcount == 0:
        conn.rollback()
        cur.close()
        conn.close()
        return jsonify({"error": "Enlace no encontrado"}), 404
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"message": f"Enlace {ori_name}↔{dst_name} eliminado"}), 200


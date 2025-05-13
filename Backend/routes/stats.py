from flask import Blueprint, jsonify, request
from services.db import fetch_all

bp = Blueprint('stats', __name__)

@bp.route('/resumen', methods=['GET'])
def obtener_estadisticas():
    query = """
        SELECT tipo, COUNT(*) AS total
        FROM estadisticas
        GROUP BY tipo;
    """
    data = fetch_all(query)
    return jsonify(data), 200


@bp.route('/logs', methods=['GET'])
def obtener_logs():
    tipo = request.args.get('tipo')
    fecha = request.args.get('fecha')  # formato: YYYY-MM-DD

    condiciones = []
    parametros = []

    if tipo:
        condiciones.append("e.tipo = %s")
        parametros.append(tipo)

    if fecha:
        condiciones.append("DATE(e.timestamp) = %s")
        parametros.append(fecha)

    where_clause = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""

    query = f"""
        SELECT h.nombre AS origen, e.tipo AS tipo_evento, 'Evento registrado' AS mensaje, e.timestamp AS fecha
        FROM estadisticas e
        JOIN hosts h ON e.id_host = h.id_host
        {where_clause}
        ORDER BY e.timestamp DESC
        LIMIT 50;
    """

    data = fetch_all(query, parametros)
    return jsonify(data), 200

from flask import Blueprint, request, jsonify
from services.db import execute_query

import requests
bp = Blueprint('config', __name__)
video_bp = Blueprint('video', __name__)

@bp.route('/', methods=['POST'])
def guardar_configuracion():
    data = request.get_json()

    balanceo = data.get('algoritmo_balanceo')
    enrutamiento = data.get('algoritmo_enrutamiento')

    if not balanceo or not enrutamiento:
        return jsonify({"error": "Faltan datos"}), 400

    query = """
        INSERT INTO configuracion (algoritmo_balanceo, algoritmo_enrutamiento)
        VALUES (%s, %s);
    """
    ok = execute_query(query, (balanceo, enrutamiento))

    if ok:
        return jsonify({"message": "Configuración guardada correctamente"}), 200
    else:
        return jsonify({"error": "No se pudo guardar"}), 500

@bp.route('/pesos', methods=['POST'])
def guardar_pesos():
    data = request.get_json()

    if not isinstance(data, list):
        return jsonify({"error": "Formato inválido"}), 400

    success = True
    for item in data:
        nombre = item.get("servidor")
        peso = item.get("peso")

        if not nombre or peso is None:
            continue

        query = "INSERT INTO pesos_vlc (nombre_servidor, peso) VALUES (%s, %s);"
        ok = execute_query(query, (nombre, peso))
        if not ok:
            success = False

    if success:
        return jsonify({"message": "Pesos guardados correctamente"}), 200
    else:
        return jsonify({"error": "Ocurrió un error al guardar uno o más pesos"}), 500




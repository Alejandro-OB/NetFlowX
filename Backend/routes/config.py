from flask import Blueprint, request, jsonify
from services.db import fetch_all, fetch_one, execute_query
import requests
from datetime import datetime

bp = Blueprint('config', __name__)
video_bp = Blueprint('video', __name__) 


@bp.route('/balanceo', methods=['POST'])
def guardar_algoritmo_balanceo():
    data = request.get_json()
    algoritmo_balanceo = data.get('algoritmo_balanceo')

    if not algoritmo_balanceo:
        return jsonify({"error": "Falta el algoritmo de balanceo"}), 400

    try:

        current_config_row = fetch_one(
            "SELECT algoritmo_balanceo, algoritmo_enrutamiento FROM configuracion ORDER BY fecha_activacion DESC LIMIT 1;"
        )

        algoritmo_enrutamiento_actual = current_config_row['algoritmo_enrutamiento'] if current_config_row and 'algoritmo_enrutamiento' in current_config_row else None

        query = """
            INSERT INTO configuracion (algoritmo_balanceo, algoritmo_enrutamiento)
            VALUES (%s, %s);
        """
        ok = execute_query(query, (algoritmo_balanceo, algoritmo_enrutamiento_actual))

        if ok:
            return jsonify({"message": f"Algoritmo de balanceo '{algoritmo_balanceo}' guardado correctamente"}), 200
        else:
            return jsonify({"error": "No se pudo guardar el algoritmo de balanceo (Error de DB)"}), 500
    except Exception as e:
        print(f"Error al guardar algoritmo de balanceo: {e}")
        return jsonify({"error": "Error interno del servidor al guardar balanceo"}), 500

@bp.route('/enrutamiento', methods=['POST'])
def guardar_algoritmo_enrutamiento():
    data = request.get_json()
    algoritmo_enrutamiento = data.get('algoritmo_enrutamiento')

    if not algoritmo_enrutamiento:
        return jsonify({"error": "Falta el algoritmo de enrutamiento"}), 400

    try:
        algoritmo_enrutamiento = algoritmo_enrutamiento.lower() 

        current_config_row = fetch_one(
            "SELECT algoritmo_balanceo, algoritmo_enrutamiento FROM configuracion ORDER BY fecha_activacion DESC LIMIT 1;"
        )
        algoritmo_balanceo_actual = current_config_row['algoritmo_balanceo'] if current_config_row and 'algoritmo_balanceo' in current_config_row else None

        query = """
            INSERT INTO configuracion (algoritmo_balanceo, algoritmo_enrutamiento)
            VALUES (%s, %s);
        """
        ok = execute_query(query, (algoritmo_balanceo_actual, algoritmo_enrutamiento))

        if ok:
            return jsonify({"message": f"Algoritmo de enrutamiento '{algoritmo_enrutamiento}' guardado correctamente"}), 200
        else:
            return jsonify({"error": "No se pudo guardar el algoritmo de enrutamiento (Error de DB)"}), 500
    except Exception as e:
        print(f"Error al guardar algoritmo de enrutamiento: {e}")
        return jsonify({"error": "Error interno del servidor al guardar enrutamiento"}), 500


@bp.route('/weights', methods=['POST'])
def guardar_pesos():
    data = request.get_json() 

    if not isinstance(data, dict):
        return jsonify({"error": "Formato de pesos inválido. Se espera un objeto JSON."}), 400

    server_names = list(data.keys())
    if not server_names:
        return jsonify({"message": "No se proporcionaron pesos para guardar."}), 200

    try:

        placeholders = ', '.join(['%s'] * len(server_names))
        delete_query = f"DELETE FROM pesos_vlc WHERE nombre_servidor IN ({placeholders});"
        execute_query(delete_query, tuple(server_names))

        insert_values = []
        for nombre_servidor, peso in data.items():
            try:
                peso_int = int(peso)
                insert_values.append((nombre_servidor, peso_int))
            except ValueError:
                print(f"Advertencia: Peso inválido para {nombre_servidor}: {peso}")
                continue
        
        if insert_values:
            values_placeholder = ', '.join(['(%s, %s)'] * len(insert_values))
            insert_query = f"INSERT INTO pesos_vlc (nombre_servidor, peso) VALUES {values_placeholder};"
            
            flat_params = [item for sublist in insert_values for item in sublist]
            
            ok = execute_query(insert_query, tuple(flat_params))
            if not ok:
                raise Exception("Error al insertar pesos en la base de datos")

        return jsonify({"message": "Pesos guardados correctamente"}), 200

    except Exception as e:
        print(f"Error al guardar pesos: {e}")
        return jsonify({"error": "Error interno del servidor al guardar pesos"}), 500

@bp.route('/history', methods=['GET'])
def get_config_history():
    try:
        query = "SELECT algoritmo_balanceo, algoritmo_enrutamiento, fecha_activacion FROM configuracion ORDER BY fecha_activacion DESC;"
        history = fetch_all(query)

        if history:
            for item in history:
                if 'fecha_activacion' in item and isinstance(item['fecha_activacion'], datetime):
                    item['fecha_activacion'] = item['fecha_activacion'].isoformat()

        return jsonify(history), 200
    except Exception as e:
        print(f"Error al obtener historial de configuración: {e}")
        return jsonify({"error": "Error interno del servidor al obtener historial"}), 500

@bp.route('/current', methods=['GET'])
def get_current_config():
    try:
        query = "SELECT algoritmo_balanceo, algoritmo_enrutamiento, fecha_activacion FROM configuracion ORDER BY fecha_activacion DESC LIMIT 1;"
        current_config = fetch_one(query)

        if current_config:
            if 'fecha_activacion' in current_config and isinstance(current_config['fecha_activacion'], datetime):
                current_config['fecha_activacion'] = current_config['fecha_activacion'].isoformat()
            return jsonify(current_config), 200
        else:
            return jsonify({
                "algoritmo_balanceo": None,
                "algoritmo_enrutamiento": None,
                "fecha_activacion": None
            }), 200
    except Exception as e:
        print(f"Error al obtener configuración actual: {e}")
        return jsonify({"error": "Error interno del servidor al obtener configuración actual"}), 500


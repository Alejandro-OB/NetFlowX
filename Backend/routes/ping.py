from flask import Blueprint, jsonify, request, Response
import requests
from services.db import get_connection
from config import Config

ping_bp = Blueprint('ping', __name__)
url_agent = Config.MININET_AGENT_URL
url_backend = f"http://{Config.BACKEND_HOST}:{Config.BACKEND_PORT}"  # Asegúrate de tener esto en config

@ping_bp.route('/ping_between_hosts_stream', methods=['POST'])
def ping_between_hosts():
    """
    Recibe los nombres de los hosts de origen y destino, luego pasa la solicitud al agente
    para que ejecute el ping entre los hosts.
    """
    data = request.get_json()
    origen = data.get('origen')
    destino = data.get('destino')

    if not origen or not destino:
        return jsonify({"error": "Faltan parámetros: origen y destino"}), 400

    # Enviar la solicitud de ping al agente (que ejecutará el comando en Mininet)
    try:
        # El URL de la ruta del agente para realizar el ping entre los hosts
        response = requests.post(url_agent, json={'origen': origen, 'destino': destino})

        if response.status_code != 200:
            return jsonify({"error": "Error al ejecutar el ping en el agente"}), 500

        # Devolver los resultados del ping al frontend
        ping_data = response.json()

        return jsonify({
            'rtt_avg': ping_data.get('rtt_avg'),
            'jitter': ping_data.get('jitter'),
            'route': ping_data.get('route')  # Si es necesario incluir la ruta
        }), 200

    except Exception as e:
        return jsonify({"error": f"Error al comunicarse con el agente: {str(e)}"}), 500
    except Exception as e:
        print(f"[BACKEND] Error en guardar_metricas: {e}")

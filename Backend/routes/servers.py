from flask import Blueprint, jsonify, request
import subprocess
import re
import os
import atexit
import signal
import psycopg2
import time
import requests
from datetime import datetime

# Importa las funciones de la base de datos desde services.db
from services.db import fetch_all, execute_query, fetch_one

servers_bp = Blueprint('servers', __name__)

# --- Configuración de la base de datos PostgreSQL ---
DB_CONFIG = {
    "dbname": os.getenv("DB_NAME", "geant_network"),
    "user": os.getenv("DB_USER", "geant_user"), # Asegúrate de que este usuario tenga permisos para SELECT en 'hosts'
    "password": os.getenv("DB_PASSWORD", "geant"), # Reemplaza con tu contraseña real
    "host": os.getenv("DB_HOST", "192.168.18.151"), # IP de tu servidor PostgreSQL
    "port": os.getenv("DB_PORT", "5432")
}

# URL del agente de Mininet (corriendo en la máquina de Mininet)
MININET_AGENT_URL = os.getenv("MININET_AGENT_URL", "http://192.168.18.157:5002") # Ejemplo: IP de la máquina de Mininet

# No necesitamos el pool de IPs multicast ni las variables relacionadas

@servers_bp.route('/add', methods=['POST'])
def iniciar_servidor_hosts_table():
    data = request.get_json()
    host_name = data.get('host_name')
    server_weight = data.get('server_weight', 1)
    transmission_port = 8080  # Puerto fijo para el servidor HTTP

    if not host_name:
        return jsonify({"error": "Falta el parámetro host_name"}), 400

    if not re.match(r'^[a-zA-Z0-9_-]+$', host_name):
        return jsonify({"error": "Formato de host_name inválido"}), 400

    try:
        host_info = fetch_one("SELECT ipv4 FROM hosts WHERE nombre = %s;", (host_name,))
        if not host_info or 'ipv4' not in host_info:
            return jsonify({"error": f"No se pudo obtener la IP del host '{host_name}' desde la tabla 'hosts'."}), 404

        server_ip = host_info['ipv4']
        print(f"IP del servidor {host_name} obtenida de la DB: {server_ip}")

        # Insertar o actualizar la entrada en la tabla
        query = """
            INSERT INTO servidores_vlc_activos (host_name, ip_destino, puerto, status, server_weight)
            VALUES (%s, %s, %s, 'activo', %s)
            ON CONFLICT (host_name) DO UPDATE SET
                ip_destino = EXCLUDED.ip_destino,
                puerto = EXCLUDED.puerto,
                status = EXCLUDED.status,
                server_weight = EXCLUDED.server_weight,
                last_updated = CURRENT_TIMESTAMP
            RETURNING process_pid;
        """
        result = execute_query(query, (host_name, server_ip, transmission_port, server_weight))
        if not result:
            return jsonify({"error": "No se pudo insertar o actualizar el registro del servidor."}), 500

        # Llamar al agente para iniciar el servidor HTTP
        print(f"Llamando al agente para iniciar servidor HTTP en {host_name}:{transmission_port}")
        try:
            response_agent = requests.post(
                f"{MININET_AGENT_URL}/mininet/start_http_server",
                json={"host": host_name, "puerto": transmission_port}
            )
            if response_agent.ok:
                agent_response = response_agent.json()
                if agent_response.get("success"):
                    pid = agent_response.get("pid")
                    update_pid_query = "UPDATE servidores_vlc_activos SET process_pid = %s WHERE host_name = %s;"
                    execute_query(update_pid_query, (pid, host_name))
                    return jsonify({
                        "message": f"Servidor HTTP iniciado en {server_ip}:{transmission_port}",
                        "server_ip": server_ip,
                        "port": transmission_port
                    }), 200
                else:
                    return jsonify({"error": agent_response.get("error", "Error desconocido del agente.")}), 500
            else:
                return jsonify({"error": f"Fallo al contactar al agente: {response_agent.status_code}"}), 500
        except Exception as e:
            print(f"Error al contactar al agente: {e}")
            return jsonify({"error": "No se pudo contactar al agente de Mininet"}), 500

    except Exception as e:
        print(f"Error general en iniciar_servidor_hosts_table: {e}")
        return jsonify({"error": f"Error interno del servidor: {str(e)}"}), 500


@servers_bp.route('/remove', methods=['POST'])
def remover_servidor_hosts_table():
    data = request.get_json()
    nombre = data.get('host_name')

    if not nombre:
        return jsonify({"error": "Falta el nombre del host"}), 400

    try:
        # Obtener la IP y puerto asignados antes de eliminar
        server_info = fetch_one("SELECT ip_destino, puerto FROM servidores_vlc_activos WHERE host_name = %s;", (nombre,))
        if not server_info:
            print(f"Advertencia: Servidor {nombre} no encontrado en servidores_vlc_activos.")
            return jsonify({"message": "Servidor no encontrado, no se pudo eliminar la entrada."}), 404

        # Eliminar de la tabla servidores_vlc_activos
        query_delete = "DELETE FROM servidores_vlc_activos WHERE host_name = %s;"
        ok_delete = execute_query(query_delete, (nombre,))

        # Llamar al agente de Mininet para detener el proceso HTTP
        print(f"Llamando al agente de Mininet para detener servidor HTTP en {nombre}")
        try:
            response_agent = requests.post(
                f"{MININET_AGENT_URL}/mininet/stop_http_server",
                json={"host": nombre}
            )
            if response_agent.ok:
                agent_response = response_agent.json()
                if agent_response.get("success"):
                    print(f"Servidor HTTP en el agente para {nombre} detenido exitosamente.")
                else:
                    print(f"Advertencia: Agente reportó fallo al detener el servidor HTTP en {nombre}: {agent_response.get('message')}.")
            else:
                print(f"Advertencia: No se pudo conectar/detener el servidor HTTP en el agente para {nombre}. Estado: {response_agent.status_code}, Respuesta: {response_agent.text}")
        except requests.exceptions.RequestException as e:
            print(f"Error de conexión con el agente de Mininet para detener servidor HTTP en {nombre}: {e}")
        except Exception as e:
            print(f"Error inesperado al detener servidor HTTP en el agente para {nombre}: {e}")

        if ok_delete:
            return jsonify({"message": "Servidor eliminado y proceso HTTP detenido."}), 200
        else:
            return jsonify({"error": "No se pudo eliminar el servidor de la tabla. Puede que ya no existiera."}), 500

    except Exception as e:
        print(f"Error en remover_servidor_hosts_table: {e}")
        return jsonify({"error": "Error interno del servidor: " + str(e)}), 500


@servers_bp.route('/active_servers', methods=['GET'])
def get_active_servers():
    """
    Endpoint para obtener la lista de servidores VLC activos.
    """
    try:
        # La columna ip_destino ahora contiene la IP unicast del servidor
        query = "SELECT host_name, video_path, ip_destino, puerto, status, server_weight, last_updated FROM servidores_vlc_activos;"
        active_servers = fetch_all(query)
        for server in active_servers:
            if 'last_updated' in server and server['last_updated'] is not None and isinstance(server['last_updated'], datetime):
                server['last_updated'] = server['last_updated'].isoformat()
            elif 'last_updated' in server and server['last_updated'] is None:
                server['last_updated'] = None 
        return jsonify(active_servers), 200
    except Exception as e:
        print(f"Error al obtener servidores activos: {e}")
        return jsonify({"error": "Error interno del servidor al obtener servidores activos."}), 500
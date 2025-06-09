from flask import Blueprint, jsonify, request
import subprocess
import re
import os
import requests
from datetime import datetime
from routes.stats import registrar_evento


from config import Config
from services.db import fetch_all, fetch_one, execute_query  

servers_bp = Blueprint('servers', __name__)
url_agent = Config.MININET_AGENT_URL

# Variables para asignación de IPs multicast
video_processes = {}
MULTICAST_IP_POOL_START = 0xEF000001
NEXT_MULTICAST_IP_INDEX = 0
ALLOCATED_MULTICAST_IPS = {}

def get_next_multicast_ip():
    """
    Genera la siguiente dirección IP multicast de forma incremental.
    """
    global NEXT_MULTICAST_IP_INDEX
    base_ip = MULTICAST_IP_POOL_START + NEXT_MULTICAST_IP_INDEX
    NEXT_MULTICAST_IP_INDEX += 1
    return f"{((base_ip >> 24) & 0xFF)}.{(base_ip >> 16) & 0xFF}.{(base_ip >> 8) & 0xFF}.{(base_ip & 0xFF)}"

@servers_bp.route('/add', methods=['POST'])
def iniciar_servidor_hosts_table():

    data = request.get_json()
    host_name    = data.get('host_name')
    video_path   = data.get('video_path')
    server_weight = data.get('server_weight', 1)

    # Validaciones básicas
    if not host_name or not video_path:
        return jsonify({"error": "Faltan host_name o video_path"}), 400
    if not re.match(r'^[a-zA-Z0-9_-]+$', host_name):
        return jsonify({"error": "Formato de host_name inválido"}), 400

    try:
        existing_server = fetch_one(
            "SELECT ip_destino, puerto FROM servidores_vlc_activos WHERE host_name = %s;",
            (host_name,)
        )

        if existing_server:
            multicast_ip   = existing_server['ip_destino']
            multicast_port = existing_server['puerto']
        else:
            multicast_ip   = get_next_multicast_ip()
            multicast_port = 5004

        # INSERT o UPDATE en la tabla servidores_vlc_activos
        query_vlc = """
            INSERT INTO servidores_vlc_activos (
                host_name, video_path, ip_destino, puerto, status, server_weight
            ) VALUES (%s, %s, %s, %s, 'activo', %s)
            ON CONFLICT (host_name) DO UPDATE SET
                video_path     = EXCLUDED.video_path,
                ip_destino     = EXCLUDED.ip_destino,
                puerto         = EXCLUDED.puerto,
                status         = EXCLUDED.status,
                server_weight  = EXCLUDED.server_weight,
                last_updated   = CURRENT_TIMESTAMP
            RETURNING process_pid;
        """
        registrar_evento("SERVIDOR_INICIADO", host_name)
        result = execute_query(query_vlc, (host_name, video_path, multicast_ip, multicast_port, server_weight))
        if result is False:
            return jsonify({"error": "No se pudo insertar/actualizar servidor VLC en la base de datos."}), 500

        # Llamada al agente Mininet para iniciar FFmpeg
        response_agent = requests.post(
            f"{url_agent}/mininet/start_ffmpeg_server",
            json={
                "host":         host_name,
                "video_path":   video_path,
                "ip_multicast": multicast_ip,
                "puerto":       multicast_port
            }
        )
        if response_agent.ok:
            agent_response = response_agent.json()
            if agent_response.get("success"):
                ffmpeg_pid = agent_response.get("ffmpeg_pid")
                # Actualizar process_pid en la BD
                execute_query(
                    "UPDATE servidores_vlc_activos SET process_pid = %s WHERE host_name = %s;",
                    (ffmpeg_pid, host_name)
                )
                return jsonify({
                    "message":        "Servidor activado y FFmpeg iniciado.",
                    "multicast_ip":   multicast_ip,
                    "multicast_port": multicast_port
                }), 200
            else:
                return jsonify({"error": f"Agente Mininet falló: {agent_response.get('message')}"}), 500
        else:
            return jsonify({"error": f"Fallo comunicación con agente Mininet (status {response_agent.status_code})."}), 500

    except Exception as e:
        print(f"Error en iniciar_servidor_hosts_table: {e}")
        return jsonify({"error": f"Error interno del servidor: {e}"}), 500

@servers_bp.route('/remove', methods=['POST'])
def remover_servidor_hosts_table():

    data = request.get_json()
    nombre = data.get('host_name')
    if not nombre:
        return jsonify({"error": "Falta el campo host_name"}), 400

    try:
        # Buscar datos del servidor
        server_info = fetch_one(
            "SELECT ip_destino, puerto FROM servidores_vlc_activos WHERE host_name = %s;",
            (nombre,)
        )
        if not server_info:
            return jsonify({"message": "Servidor no encontrado."}), 404

        multicast_ip   = server_info['ip_destino']
        multicast_port = server_info['puerto']

        # Eliminar clientes asociados (BD + agente)
        clientes = fetch_all(
            "SELECT host_cliente FROM clientes_activos WHERE servidor_asignado = %s;",
            (nombre,)
        )
        for cliente in clientes:
            cliente_host = cliente['host_cliente']
            try:
                response_cliente = requests.post(
                    f"{url_agent}/mininet/stop_ffmpeg_client",
                    json={"host": cliente_host}
                )
                if not response_cliente.ok:
                    print(f"Error al detener cliente {cliente_host} via agente.")
            except Exception as err:
                print(f"Excepción al detener cliente {cliente_host}: {err}")

        execute_query(
            "DELETE FROM clientes_activos WHERE servidor_asignado = %s;",
            (nombre,)
        )
        registrar_evento("SERVIDOR_ELIMINADO", nombre)

        # Eliminar el servidor de la BD
        ok_vlc = execute_query("DELETE FROM servidores_vlc_activos WHERE host_name = %s;", (nombre,))

        # Llamada al agente Mininet para detener FFmpeg del servidor
        response_agent = requests.post(
            f"{url_agent}/mininet/stop_ffmpeg_server",
            json={"host": nombre, "ip_multicast": multicast_ip}
        )

        if response_agent.ok:
            agent_response = response_agent.json()
            
            if not agent_response.get("success"):
                print(f"Advertencia: Agente Mininet falló al detener FFmpeg: {agent_response.get('message')}")

        if ok_vlc is False:
            return jsonify({"error": "No se pudo eliminar el servidor VLC de la base de datos."}), 500

        # Liberar IP multicast de ser necesario
        if nombre in ALLOCATED_MULTICAST_IPS:
            del ALLOCATED_MULTICAST_IPS[nombre]

        return jsonify({"message": "Servidor y clientes eliminados correctamente."}), 200

    except Exception as e:
        print(f"Error en remover_servidor_hosts_table: {e}")
        return jsonify({"error": f"Error interno del servidor: {e}"}), 500



@servers_bp.route('/active_servers', methods=['GET'])
def get_active_servers():
    """
    Ruta GET /active_servers:
    Devuelve la lista de todos los servidores VLC activos, con sus campos:
      host_name, video_path, ip_destino, puerto, status, server_weight, last_updated
    Formatea last_updated a ISO 8601 antes de devolver JSON.
    """
    try:
        query = """
            SELECT host_name, video_path, ip_destino, puerto,
                   status, server_weight, last_updated
              FROM servidores_vlc_activos;
        """
        active_servers = fetch_all(query)

        for server in active_servers:
            if server.get('last_updated') is not None and isinstance(server['last_updated'], datetime):
                server['last_updated'] = server['last_updated'].isoformat()
            else:
                server['last_updated'] = None

        return jsonify(active_servers), 200

    except Exception as e:
        print(f"Error al obtener servidores activos: {e}")
        return jsonify({"error": "Error interno al obtener servidores activos."}), 500

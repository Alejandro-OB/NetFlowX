from flask import Blueprint, jsonify, request
import subprocess
import re
import os
import requests 
from datetime import datetime 


from services.db import fetch_all, execute_query, fetch_one # Añadido fetch_one

servers_bp = Blueprint('servers', __name__)

# --- Configuración de la base de datos PostgreSQL ---
DB_CONFIG = {
    "dbname": os.getenv("DB_NAME", "geant_network"),
    "user": os.getenv("DB_USER", "geant_user"),
    "password": os.getenv("DB_PASSWORD", "geant"),
    "host": os.getenv("DB_HOST", "192.168.18.151"), # IP PostgreSQL
    "port": os.getenv("DB_PORT", "5432")
}

MININET_AGENT_URL = os.getenv("MININET_AGENT_URL", "http://192.168.18.208:5002") #IP de la máquina de Mininet

video_processes = {} # { "h1_1": {"video_path": "/path/to/video.mp4", "ip_destino": "10.0.0.2", "puerto": 5004, "status": "activo"} }

# --- Lógica de asignación de IP Multicast ---
# Pool de IPs multicast para asignar a los servidores VLC
MULTICAST_IP_POOL_START = 0xEF000001 
NEXT_MULTICAST_IP_INDEX = 0
ALLOCATED_MULTICAST_IPS = {} 

def get_next_multicast_ip():
    """
    Genera la siguiente IP multicast disponible del pool.
    Nota: Esta implementación es simple y no persiste el índice entre reinicios
    ni maneja la reutilización de IPs de servidores eliminados de forma robusta.
    Para un sistema más avanzado, se debería gestionar en la DB.
    """
    global NEXT_MULTICAST_IP_INDEX
    base_ip = MULTICAST_IP_POOL_START + NEXT_MULTICAST_IP_INDEX
    NEXT_MULTICAST_IP_INDEX += 1
    # Convertir el entero a formato IP (ej. 239.0.0.1)
    return f"{((base_ip >> 24) & 0xFF)}.{(base_ip >> 16) & 0xFF}.{(base_ip >> 8) & 0xFF}.{(base_ip & 0xFF)}"



@servers_bp.route('/add', methods=['POST'])
def iniciar_servidor_hosts_table():
    data = request.get_json()
    host_name = data.get('host_name')
    video_path = data.get('video_path')
    server_weight = data.get('server_weight', 1) # Peso por defecto 1

    if not host_name or not video_path:
        return jsonify({"error": "Faltan host_name o video_path"}), 400
    
    if not re.match(r'^[a-zA-Z0-9_-]+$', host_name):
        return jsonify({"error": "Formato de host_name inválido"}), 400

    try:
        # Asignar una IP y puerto multicast
        existing_server = fetch_one("SELECT ip_destino, puerto FROM servidores_vlc_activos WHERE host_name = %s;", (host_name,))
        
        multicast_ip = None
        multicast_port = 5004 # Puerto multicast 

        if existing_server:
            multicast_ip = existing_server['ip_destino']
            multicast_port = existing_server['puerto']
            print(f"Servidor {host_name} ya tiene IP multicast asignada: {multicast_ip}:{multicast_port}")
        else:
            multicast_ip = get_next_multicast_ip()
            print(f"Asignando nueva IP multicast a {host_name}: {multicast_ip}:{multicast_port}")
        
        # Actualizar o insertar en la tabla servidores_vlc_activos
        query_vlc = """
            INSERT INTO servidores_vlc_activos (host_name, video_path, ip_destino, puerto, status, server_weight)
            VALUES (%s, %s, %s, %s, 'activo', %s)
            ON CONFLICT (host_name) DO UPDATE SET
                video_path = EXCLUDED.video_path,
                ip_destino = EXCLUDED.ip_destino,
                puerto = EXCLUDED.puerto,
                status = EXCLUDED.status,
                server_weight = EXCLUDED.server_weight,
                last_updated = CURRENT_TIMESTAMP
            RETURNING process_pid;
        """
        # execute_query devuelve el resultado de RETURNING si se usa
        result = execute_query(query_vlc, (host_name, video_path, multicast_ip, multicast_port, server_weight))
        ok_vlc = result is not None 

        if not ok_vlc:
            return jsonify({"error": "No se pudo actualizar/insertar en la tabla de servidores VLC activos."}), 500

        # Llamar al agente de Mininet para iniciar el proceso FFmpeg
        print(f"Llamando al agente de Mininet para iniciar FFmpeg en {host_name} a {multicast_ip}:{multicast_port}")
        try:
            response_agent = requests.post(
                f"{MININET_AGENT_URL}/mininet/start_ffmpeg_server",
                json={
                    "host": host_name,
                    "video_path": video_path,
                    "ip_multicast": multicast_ip,
                    "puerto": multicast_port
                }
            )
            if response_agent.ok:
                agent_response = response_agent.json()
                if agent_response.get("success"):
                    ffmpeg_pid = agent_response.get("ffmpeg_pid")
                    # Actualizar el PID del proceso FFmpeg en la base de datos
                    update_pid_query = "UPDATE servidores_vlc_activos SET process_pid = %s WHERE host_name = %s;"
                    execute_query(update_pid_query, (ffmpeg_pid, host_name))
                    print(f"Proceso FFmpeg en el agente para {host_name} iniciado exitosamente con PID {ffmpeg_pid}.")
                    return jsonify({"message": "Servidor activado y FFmpeg iniciado.", "multicast_ip": multicast_ip, "multicast_port": multicast_port}), 200
                else:
                    print(f"Advertencia: Agente reportó fallo al iniciar FFmpeg en {host_name}: {agent_response.get('message')}. Detalles: {agent_response.get('details')}")
                    return jsonify({"error": f"Agente falló al iniciar FFmpeg: {agent_response.get('message')}"}), 500
            else:
                print(f"Advertencia: No se pudo conectar/iniciar FFmpeg en el agente para {host_name}. Estado: {response_agent.status_code}, Respuesta: {response_agent.text}")
                return jsonify({"error": f"Fallo en la comunicación con el agente de Mininet: {response_agent.status_code}"}), 500
        except requests.exceptions.RequestException as e:
            print(f"Error de conexión con el agente de Mininet para iniciar FFmpeg en {host_name}: {e}")
            return jsonify({"error": "Error de conexión con el agente de Mininet."}), 500
        except Exception as e:
            print(f"Error inesperado al iniciar FFmpeg en el agente para {host_name}: {e}")
            return jsonify({"error": "Error interno del servidor al iniciar FFmpeg."}), 500

    except Exception as e:
        print(f"Error en iniciar_servidor_hosts_table: {e}")
        return jsonify({"error": "Error interno del servidor: " + str(e)}), 500

@servers_bp.route('/remove', methods=['POST'])
def remover_servidor_hosts_table():
    data = request.get_json()
    nombre = data.get('host_name')

    if not nombre:
        return jsonify({"error": "Falta el nombre del host"}), 400

    try:
        # Obtener la IP y puerto multicast asignados antes de eliminar de la DB
        server_info = fetch_one("SELECT ip_destino, puerto FROM servidores_vlc_activos WHERE host_name = %s;", (nombre,))
        if server_info:
            multicast_ip = server_info['ip_destino']
            multicast_port = server_info['puerto']
        else:
            print(f"Advertencia: Servidor {nombre} no encontrado en servidores_vlc_activos.")
            return jsonify({"message": "Servidor no encontrado, no se pudo eliminar el rol de servidor o la entrada de VLC activo."}), 404

        # Eliminar de la tabla servidores_vlc_activos
        query_vlc = "DELETE FROM servidores_vlc_activos WHERE host_name = %s;"
        ok_vlc = execute_query(query_vlc, (nombre,))

        # Llamar al agente de Mininet para detener el proceso FFmpeg
        print(f"Llamando al agente de Mininet para detener FFmpeg en {nombre}")
        try:
            response_agent = requests.post(
                f"{MININET_AGENT_URL}/mininet/stop_ffmpeg_server",
                json={"host": nombre}
            )
            if response_agent.ok:
                agent_response = response_agent.json()
                if agent_response.get("success"):
                    print(f"Proceso VLC en el agente para {nombre} detenido exitosamente.")
                else:
                    print(f"Advertencia: Agente reportó fallo al detener proceso VLC en {nombre}: {agent_response.get('message')}. Detalles: {agent_response.get('details')}")
            else:
                print(f"Advertencia: No se pudo conectar/detener el proceso VLC en el agente para {nombre}. Estado: {response_agent.status_code}, Respuesta: {response_agent.text}")
        except requests.exceptions.RequestException as e:
            print(f"Error de conexión con el agente de Mininet para detener VLC en {nombre}: {e}")
        except Exception as e:
            print(f"Error inesperado al detener VLC en el agente para {nombre}: {e}")

        if ok_vlc:
            # Si el servidor fue eliminado de la DB, también liberamos su IP multicast
            if nombre in ALLOCATED_MULTICAST_IPS:
                del ALLOCATED_MULTICAST_IPS[nombre]
            return jsonify({"message": "Servidor eliminado del rol y de la lista de VLC activos."}), 200
        else:
            return jsonify({"error": "No se pudo eliminar el rol de servidor o la entrada de VLC activo. Puede que el host no existiera o ya no tuviera el rol."}), 500

    except Exception as e:
        print(f"Error en remover_servidor_hosts_table: {e}")
        return jsonify({"error": "Error interno del servidor: " + str(e)}), 500

@servers_bp.route('/active_servers', methods=['GET'])
def get_active_servers():
    """
    Endpoint para obtener la lista de servidores VLC activos.
    """
    try:
        query = "SELECT host_name, video_path, ip_destino, puerto, status, server_weight, last_updated FROM servidores_vlc_activos;"
        active_servers = fetch_all(query)
        # Formatear la fecha para la respuesta JSON
        for server in active_servers:
            # CORRECCIÓN: Asegurarse de que 'last_updated' no sea None antes de intentar formatear
            if 'last_updated' in server and server['last_updated'] is not None and isinstance(server['last_updated'], datetime):
                server['last_updated'] = server['last_updated'].isoformat()
            elif 'last_updated' in server and server['last_updated'] is None:
                server['last_updated'] = None # O un valor por defecto si prefieres
        return jsonify(active_servers), 200
    except Exception as e:
        print(f"Error al obtener servidores activos: {e}")
        return jsonify({"error": "Error interno del servidor al obtener servidores activos."}), 500


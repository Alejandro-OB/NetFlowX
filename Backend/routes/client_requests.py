from flask import Blueprint, jsonify
from services.db import fetch_all, fetch_one
import threading
import time
from datetime import datetime # Importar datetime para el formato de fecha

client_requests_bp = Blueprint('client_requests', __name__)

# --- Estado en memoria para Round Robin y Weighted Round Robin ---
# Usando un Lock para la seguridad de los hilos si múltiples solicitudes de clientes llegan concurrentemente
rr_lock = threading.Lock()
rr_index = 0 # Índice para el algoritmo Round Robin

active_servers_cache = [] # Para almacenar datos del servidor: {host_name, ip_destino, puerto, server_weight}
last_cache_update = 0 # Timestamp de la última actualización de la caché de servidores
CACHE_TTL = 10 # segundos para refrescar la lista de servidores de la DB

wrr_server_list = [] # Lista expandida para Weighted Round Robin
last_wrr_list_update = 0 # Timestamp de la última actualización de la lista WRR

def refresh_active_servers_cache():
    """
    Refresca la caché de servidores activos desde la base de datos si ha expirado el TTL.
    """
    global active_servers_cache, last_cache_update
    if time.time() - last_cache_update > CACHE_TTL:
        print("Refrescando la caché de servidores activos...")
        query = "SELECT host_name, ip_destino, puerto, server_weight FROM servidores_vlc_activos WHERE status = 'activo';"
        # fetch_all devuelve una lista de diccionarios si usas DictCursor
        active_servers_cache = fetch_all(query)
        last_cache_update = time.time()
    return active_servers_cache

def generate_wrr_list():
    """
    Genera la lista expandida de servidores para Weighted Round Robin.
    Cada servidor aparece 'server_weight' veces en la lista.
    """
    global wrr_server_list, last_wrr_list_update
    
    # Asegurarse de que la caché de servidores activos esté fresca antes de generar la lista WRR
    servers_from_cache = refresh_active_servers_cache()

    # Regenerar la lista WRR solo si la caché de servidores ha cambiado
    # o si ha pasado el TTL de la lista WRR
    if time.time() - last_wrr_list_update > CACHE_TTL or \
       len(servers_from_cache) != len(active_servers_cache) or \
       any(server not in servers_from_cache for server in active_servers_cache): # Comprobación simple de cambio
        
        print("Generando la lista de servidores WRR...")
        new_wrr_list = []
        for server in servers_from_cache:
            for _ in range(server['server_weight']):
                new_wrr_list.append(server)
        wrr_server_list = new_wrr_list
        last_wrr_list_update = time.time()
    return wrr_server_list

@client_requests_bp.route('/get_multicast_stream_info', methods=['GET'])
def get_multicast_stream_info():
    """
    Endpoint para que los clientes soliciten información del stream multicast.
    Aplica el algoritmo de balanceo de carga configurado (RR o WRR).
    """
    # Mover la declaración global al inicio de la función
    global rr_index 

    try:
        # Obtener el algoritmo de balanceo de carga actual de la configuración
        current_config = fetch_one("SELECT algoritmo_balanceo FROM configuracion ORDER BY fecha_activacion DESC LIMIT 1;")
        algoritmo_balanceo = current_config['algoritmo_balanceo'] if current_config else None

        selected_server = None

        if algoritmo_balanceo == 'RR':
            with rr_lock: # Proteger el acceso al índice RR
                servers = refresh_active_servers_cache()
                if servers:
                    selected_server = servers[rr_index % len(servers)]
                    rr_index = (rr_index + 1) % len(servers) # Incrementar y volver al principio
                else:
                    print("No hay servidores activos para Round Robin.")
        elif algoritmo_balanceo == 'WRR':
            with rr_lock: # Proteger el acceso al índice WRR
                servers_wrr = generate_wrr_list()
                if servers_wrr:
                    selected_server = servers_wrr[rr_index % len(servers_wrr)]
                    rr_index = (rr_index + 1) % len(servers_wrr) # Incrementar y volver al principio
                else:
                    print("No hay servidores activos para Weighted Round Robin.")
        else:
            # Si no hay algoritmo configurado o es desconocido, usar RR por defecto
            print(f"Algoritmo de balanceo desconocido o no configurado ({algoritmo_balanceo}). Usando Round Robin por defecto.")
            servers = refresh_active_servers_cache()
            if servers:
                with rr_lock:
                    selected_server = servers[rr_index % len(servers)]
                    rr_index = (rr_index + 1) % len(servers)
            else:
                    print("No hay servidores activos para Round Robin (por defecto).")


        if selected_server:
            return jsonify({
                "host_name": selected_server['host_name'],
                "multicast_ip": selected_server['ip_destino'],
                "multicast_port": selected_server['puerto']
            }), 200
        else:
            return jsonify({"error": "No hay servidores activos disponibles para streaming."}), 503

    except Exception as e:
        print(f"Error al obtener información del flujo multicast: {e}")
        return jsonify({"error": "Error interno del servidor al procesar la solicitud."}), 500

@client_requests_bp.route('/hosts', methods=['GET'])
def get_mininet_hosts():
    """
    Endpoint para obtener una lista de hosts disponibles desde la tabla 'hosts' de la base de datos.
    """
    try:
        query_hosts = "SELECT nombre FROM hosts;" # Selecciona la columna 'nombre'
        hosts_data = fetch_all(query_hosts) # Ejecuta la consulta a la DB
        
        # Formatea los datos para que coincidan con el formato esperado por el frontend
        # que es {"hosts": [{"name": "h1_1"}, ...]}
        hosts = [{"name": h['nombre']} for h in hosts_data]
        
        return jsonify({"hosts": hosts}), 200
    except Exception as e:
        print(f"Error al obtener la lista de hosts de la base de datos: {e}")
        return jsonify({"error": f"Error interno del servidor al obtener hosts de la DB: {str(e)}"}), 500

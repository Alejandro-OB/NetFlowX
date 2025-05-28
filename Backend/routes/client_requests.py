from flask import Blueprint, jsonify, request
from services.db import fetch_all, fetch_one
import threading
import time
from datetime import datetime # Importar datetime para el formato de fecha
from services.db import execute_query

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

        if algoritmo_balanceo == 'round_robin':
            with rr_lock: # Proteger el acceso al índice RR
                servers = refresh_active_servers_cache()
                if servers:
                    selected_server = servers[rr_index % len(servers)]
                    rr_index = (rr_index + 1) % len(servers) # Incrementar y volver al principio
                else:
                    print("No hay servidores activos para Round Robin.")
        elif algoritmo_balanceo == 'weighted_round_robin':
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

@client_requests_bp.route('/update_client_status', methods=['POST'])
def update_client_status():
    data = request.get_json()
    host_name = data.get('host_name')
    is_client = data.get('is_client')

    if not host_name or is_client is None:
        return jsonify({"error": "Host name and client status are required."}), 400

    try:
        sql_is_client = 'TRUE' if is_client else 'FALSE'
        update_query = "UPDATE hosts SET es_cliente = %s WHERE nombre = %s;"
        execute_query(update_query, (sql_is_client, host_name))
        return jsonify({"success": True, "message": f"Estado de {host_name} actualizado a es_cliente={is_client}"}), 200
    except Exception as e:
        return jsonify({"error": f"Error al actualizar es_cliente: {str(e)}"}), 500

@client_requests_bp.route('/add_active_client', methods=['POST'])
def add_active_client():
    """
    Añade un cliente a la tabla clientes_activos con información completa.
    """
    data = request.get_json()
    host_cliente = data.get('host')
    servidor_asignado = data.get('server_name')
    ip_destino = data.get('server_ip')
    puerto = data.get('port')
    video_solicitado = data.get('video_file')

    if not all([host_cliente, servidor_asignado, ip_destino, puerto, video_solicitado]):
        return jsonify({"error": "Faltan datos requeridos para añadir cliente activo."}), 400

    try:
        timestamp_inicio = datetime.now().isoformat()
        hora_asignacion = datetime.now().isoformat()


        insert_query = """
            INSERT INTO clientes_activos 
            (host_cliente, servidor_asignado, ip_destino, puerto, video_solicitado, timestamp_inicio, estado, hora_asignacion)
            VALUES (%s, %s, %s, %s, %s, %s, 'activo', %s);
        """
        execute_query(insert_query, (
            host_cliente, servidor_asignado, ip_destino, puerto, video_solicitado, timestamp_inicio, hora_asignacion
        ))

        return jsonify({"success": True, "message": f"Cliente {host_cliente} añadido a clientes_activos."}), 201
    except Exception as e:
        return jsonify({"error": f"Error al insertar cliente activo: {str(e)}"}), 500


@client_requests_bp.route('/remove_active_client', methods=['POST'])
def remove_active_client():
    data = request.get_json()
    host_cliente = data.get('host')

    if not host_cliente:
        return jsonify({"error": "Host cliente requerido."}), 400

    try:
        delete_query = "DELETE FROM clientes_activos WHERE host_cliente = %s;"
        execute_query(delete_query, (host_cliente,))
        return jsonify({"success": True, "message": f"Cliente {host_cliente} eliminado."}), 200
    except Exception as e:
        return jsonify({"error": f"Error al eliminar cliente activo: {str(e)}"}), 500

@client_requests_bp.route('/active_clients', methods=['GET'])
def get_active_clients():
    try:
        query = "SELECT host_cliente, servidor_asignado, ip_destino, puerto, video_solicitado FROM clientes_activos;"
        clients_data = fetch_all(query)
        active_clients = [
            {
                "host": c['host_cliente'],
                "server_display_name": c['servidor_asignado'],
                "ip_destino_raw": c['ip_destino'],
                "port": c['puerto'],
                "video": c['video_solicitado']
            }
            for c in clients_data
        ]
        return jsonify({"active_clients": active_clients}), 200
    except Exception as e:
        return jsonify({"error": f"Error al obtener clientes activos: {str(e)}"}), 500

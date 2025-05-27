from flask import Blueprint, jsonify
import threading
import time
from datetime import datetime # Importar datetime para el formato de fecha

# Importar las funciones de conexión y consulta a la base de datos desde services.db
from services.db import fetch_all, fetch_one, execute_query # execute_query no se usa aquí, pero se mantiene por si acaso

client_requests_bp = Blueprint('client_requests', __name__)

# --- Constantes para la VIP ---
# Asegúrate de que esta VIP coincida con la configuración en tu controlador SDN
VIP_IP = "10.0.0.100"
VIP_PORT = 5004 # Puerto de servicio que el cliente usará para conectarse a la VIP

# --- Estado en memoria para Round Robin y Weighted Round Robin ---
# Usando un Lock para la seguridad de los hilos si múltiples solicitudes de clientes llegan concurrentemente
rr_lock = threading.Lock()
rr_index = 0 # Índice para el algoritmo Round Robin

active_servers_cache = [] # Para almacenar datos del servidor: {host_name, ip_destino, puerto, server_weight}
last_cache_update = 0 # Timestamp de la última actualización de la caché de servidores
CACHE_TTL = 10 # segundos para refrescar la lista de servidores de la DB

wrr_server_list = [] # Lista expandida para Weighted Round Robin
last_wrr_list_update = 0 # Timestamp de la última actualización de la lista WRR

# --- Fin de las funciones de base de datos (ahora importadas) ---


def refresh_active_servers_cache():
    """
    Refresca la caché de servidores activos desde la base de datos si ha expirado el TTL.
    """
    global active_servers_cache, last_cache_update
    if time.time() - last_cache_update > CACHE_TTL:
        print("Refrescando la caché de servidores activos...")
        query = "SELECT host_name, ip_destino, puerto, server_weight FROM servidores_vlc_activos WHERE status = 'activo';"
        active_servers_cache = fetch_all(query) # Usar la función fetch_all importada
        last_cache_update = time.time()
        print(f"Caché de servidores activos refrescada: {active_servers_cache}")

def refresh_wrr_list():
    """
    Reconstruye la lista expandida para Weighted Round Robin basada en la caché actual.
    """
    global wrr_server_list, last_wrr_list_update
    if time.time() - last_wrr_list_update > CACHE_TTL: # Reconstruir lista WRR si expira
        print("Reconstruyendo la lista WRR...")
        wrr_server_list = []
        for s_info in active_servers_cache:
            weight = s_info.get('server_weight', 1)
            if weight is None:
                weight = 1
            wrr_server_list.extend([s_info] * weight)
        last_wrr_list_update = time.time()
        print(f"Lista WRR reconstruida (longitud: {len(wrr_server_list)})")


# --- Funciones de Clientes Multicast ---
@client_requests_bp.route('/client/get_multicast_stream_info', methods=['GET'])
def get_multicast_stream_info():
    """
    Endpoint para que el cliente solicite información del stream multicast.
    Selecciona un servidor backend usando balanceo de carga y devuelve la VIP.
    """
    global rr_index

    try:
        refresh_active_servers_cache()

        query_lb_algo = "SELECT algoritmo_balanceo FROM configuracion ORDER BY fecha_activacion DESC LIMIT 1;"
        config_data = fetch_one(query_lb_algo) # Usar la función fetch_one importada
        configured_lb_algorithm = config_data['algoritmo_balanceo'] if config_data and config_data['algoritmo_balanceo'] else 'round_robin'
        print(f"Algoritmo de balanceo de carga configurado: {configured_lb_algorithm}")

        selected_server = None

        with rr_lock:
            if not active_servers_cache:
                print("No hay servidores activos en la caché.")
                return jsonify({"error": "No hay servidores activos disponibles para streaming."}), 503

            if configured_lb_algorithm == 'round_robin':
                if active_servers_cache:
                    selected_server = active_servers_cache[rr_index % len(active_servers_cache)]
                    rr_index = (rr_index + 1) % len(active_servers_cache)
                    print(f"RR: Servidor real seleccionado: {selected_server['host_name']}")
                else:
                    print("RR: No hay servidores activos para Round Robin.")

            elif configured_lb_algorithm == 'weighted_round_robin':
                refresh_wrr_list()

                if wrr_server_list:
                    selected_server = wrr_server_list[rr_index % len(wrr_server_list)]
                    rr_index = (rr_index + 1) % len(wrr_server_list)
                    print(f"WRR: Servidor real seleccionado: {selected_server['host_name']}")
                else:
                    print("WRR: No hay servidores activos con pesos válidos para Weighted Round Robin, fallback a Round Robin.")
                    selected_server = active_servers_cache[rr_index % len(active_servers_cache)]
                    rr_index = (rr_index + 1) % len(active_servers_cache)

            elif configured_lb_algorithm == 'least_connections':
                print("Algoritmo 'least_connections' no implementado en la capa de aplicación, usando Round Robin.")
                selected_server = active_servers_cache[rr_index % len(active_servers_cache)]
                rr_index = (rr_index + 1) % len(active_servers_cache)
            else:
                print(f"Algoritmo '{configured_lb_algorithm}' no reconocido, usando Round Robin.")
                selected_server = active_servers_cache[rr_index % len(active_servers_cache)]
                rr_index = (rr_index + 1) % len(active_servers_cache)

        if selected_server:
            print(f"Balanceador: Cliente redirigido a VIP {VIP_IP}:{VIP_PORT} (servidor real seleccionado: {selected_server['host_name']})")
            return jsonify({
                "host_name": selected_server['host_name'],
                "multicast_ip": VIP_IP,
                "multicast_port": VIP_PORT
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
        query_hosts = "SELECT nombre FROM hosts;"
        hosts_data = fetch_all(query_hosts) # Usar la función fetch_all importada
        
        hosts = [{"name": h['nombre']} for h in hosts_data]
        
        return jsonify({"hosts": hosts}), 200
    except Exception as e:
        print(f"Error al obtener la lista de hosts de la base de datos: {e}")
        return jsonify({"error": f"Error interno del servidor al obtener hosts de la DB: {str(e)}"}), 500


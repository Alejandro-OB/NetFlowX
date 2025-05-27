from flask import Blueprint, jsonify
import threading
import time
from datetime import datetime # Importar datetime para el formato de fecha
from flask import request

# Importar las funciones de conexión y consulta a la base de datos desde services.db
from services.db import fetch_all, fetch_one, execute_query # execute_query no se usa aquí, pero se mantiene por si acaso

client_requests_bp = Blueprint('client_requests', __name__)

@client_requests_bp.route('/hosts', methods=['GET'])
def get_mininet_hosts():
    """
    Endpoint para obtener una lista de hosts disponibles desde la tabla 'hosts' de la base de datos,
    excluyendo aquellos donde es_cliente es TRUE.
    """
    try:
        # Modificar la consulta para excluir hosts donde es_cliente es TRUE
        query_hosts = "SELECT nombre FROM hosts WHERE es_cliente = FALSE;"
        hosts_data = fetch_all(query_hosts)

        hosts = [{"name": h['nombre']} for h in hosts_data]

        return jsonify({"hosts": hosts}), 200
    except Exception as e:
        print(f"Error al obtener la lista de hosts de la base de datos: {e}")
        return jsonify({"error": f"Error interno del servidor al obtener hosts de la DB: {str(e)}"}), 500

@client_requests_bp.route('/update_client_status', methods=['POST'])
def update_client_status():
    """
    Endpoint para actualizar el estado 'es_cliente' de un host en la base de datos.
    """
    data = request.get_json()
    host_name = data.get('host_name')
    is_client = data.get('is_client') # True or False

    if not host_name or is_client is None:
        return jsonify({"error": "Host name and client status are required."}), 400

    try:
        # Actualizar la columna es_cliente en la base de datos
        # Usar %s como placeholder y convertir is_client a 'TRUE' o 'FALSE'
        # o asegurarte de que tu función execute_query maneje bien los booleanos Python
        if is_client:
            sql_is_client = 'TRUE'
        else:
            sql_is_client = 'FALSE'
        
        # Opción 1: Si execute_query maneja bien los booleanos de Python (preferido)
        # update_query = "UPDATE hosts SET es_cliente = %s WHERE nombre = %s;"
        # execute_query(update_query, (is_client, host_name)) # is_client se pasa como booleano de Python

        # Opción 2: Si necesitas pasar 'TRUE'/'FALSE' como string explícitamente (menos flexible)
        update_query = "UPDATE hosts SET es_cliente = %s WHERE nombre = %s;"
        execute_query(update_query, (sql_is_client, host_name)) # sql_is_client es 'TRUE' o 'FALSE' string


        return jsonify({"success": True, "message": f"Estado de {host_name} actualizado a es_cliente={is_client}"}), 200
    except Exception as e:
        print(f"Error al actualizar el estado del cliente en la DB: {e}")
        return jsonify({"error": f"Error interno del servidor al actualizar el estado del cliente: {str(e)}"}), 500


@client_requests_bp.route('/active_clients', methods=['GET'])
def get_active_clients():
    """
    Endpoint para obtener la lista de clientes activos desde la tabla 'clientes_activos'.
    """
    try:
        # La consulta ya selecciona 'servidor_asignado' e 'ip_destino'
        query = "SELECT host_cliente, servidor_asignado, ip_destino, puerto, video_solicitado, timestamp_inicio, estado FROM clientes_activos;"
        clients_data = fetch_all(query) # Asume que fetch_all devuelve una lista de diccionarios o similar
        
        active_clients = []
        for client in clients_data:
            active_clients.append({
                "host": client['host_cliente'],
                # Aquí puedes decidir qué mostrar:
                # Opción A: Mostrar el nombre del servidor asignado
                "server_display_name": client['servidor_asignado'], # Nueva clave para el frontend

                # Opción B: Si quieres mantener 'server_ip' pero mostrar el nombre del host
                # "server_ip": client['servidor_asignado'], # Sobrescribe server_ip con el nombre del host

                # Mantén ip_destino si la necesitas para algo más
                "ip_destino_raw": client['ip_destino'], # Mantén la IP original si la necesitas en el frontend

                "port": client['puerto'],
                "video": client['video_solicitado'],
                "timestamp_inicio": str(client['timestamp_inicio']),
                "estado": client['estado']
            })
        
        return jsonify({"active_clients": active_clients}), 200
    except Exception as e:
        print(f"Error al obtener clientes activos de la DB: {e}")
        return jsonify({"error": f"Error interno del servidor al obtener clientes activos: {str(e)}"}), 500


@client_requests_bp.route('/add_active_client', methods=['POST'])
def add_active_client():
    """
    Endpoint para añadir un nuevo registro a la tabla 'clientes_activos'.
    """
    data = request.get_json()
    host_cliente = data.get('host')
    ip_destino = data.get('server_ip')
    puerto = data.get('port')
    video_solicitado = data.get('video_file')

    if not all([host_cliente, ip_destino, puerto, video_solicitado]):
        return jsonify({"error": "Faltan datos requeridos para añadir cliente activo."}), 400

    try:
        # Usar %s como placeholders para PostgreSQL
        insert_query = """
            INSERT INTO clientes_activos (host_cliente, ip_destino, puerto, video_solicitado)
            VALUES (%s, %s, %s, %s);
        """
        execute_query(insert_query, (host_cliente, ip_destino, puerto, video_solicitado))
        
        return jsonify({"success": True, "message": f"Cliente {host_cliente} añadido a clientes_activos."}), 201
    except Exception as e:
        print(f"Error al añadir cliente activo a la DB: {e}")
        return jsonify({"error": f"Error interno del servidor al añadir cliente activo: {str(e)}"}), 500

@client_requests_bp.route('/remove_active_client', methods=['POST'])
def remove_active_client():
    """
    Endpoint para eliminar un registro de la tabla 'clientes_activos'.
    """
    data = request.get_json()
    host_cliente = data.get('host')

    if not host_cliente:
        return jsonify({"error": "Host cliente requerido para eliminar."}), 400

    try:
        # Asegúrate de que el placeholder sea el correcto para tu DB (ej. %s para psycopg2 con PostgreSQL)
        delete_query = "DELETE FROM clientes_activos WHERE host_cliente = %s;" # <--- ¡Revisa esto!
        execute_query(delete_query, (host_cliente,)) # <--- Asegúrate de pasar la tupla correctamente

        # Opcional: Si quieres un commit explícito (dependiendo de tu configuración de execute_query)
        # db_connection.commit() # Si execute_query no hace commit automáticamente

        return jsonify({"success": True, "message": f"Cliente {host_cliente} eliminado de clientes_activos."}), 200
    except Exception as e:
        print(f"Error al eliminar cliente activo de la DB: {e}") # Este mensaje debería aparecer en tus logs
        return jsonify({"error": f"Error interno del servidor al eliminar cliente activo: {str(e)}"}), 500
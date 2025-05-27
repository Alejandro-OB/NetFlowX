from flask import Blueprint, jsonify, request
import psycopg2
from services.db import fetch_all, execute_query, fetch_one 

topology_bp = Blueprint('topology', __name__)

# CORRECCIÓN: Cambiado el decorador de ruta a '/get' para que coincida con el frontend
@topology_bp.route('/get', methods=['GET'])
def get_topology():
    """
    Endpoint para obtener la información completa de la topología (switches, hosts, enlaces).
    """
    try:
        # Modificación clave: Añadir 'status' a la selección
        switches_data = fetch_all("SELECT id_switch, nombre, switch_label AS dpid, latitud, longitud, status FROM switches;")
        formatted_switches = []
        switches_by_id = {}

        if switches_data:
            for sw in switches_data:
                lat = float(sw['latitud']) if sw['latitud'] is not None else None
                lon = float(sw['longitud']) if sw['longitud'] is not None else None

                formatted_sw_entry = {
                    'id_switch': sw['id_switch'],
                    'nombre': sw['nombre'],
                    'dpid': sw['dpid'],
                    'latitud': lat,
                    'longitud': lon,
                    'status': sw['status']  # Incluir el estado
                }
                formatted_switches.append(formatted_sw_entry)
                switches_by_id[sw['id_switch']] = formatted_sw_entry

        hosts_data = fetch_all("SELECT id_host, nombre, mac, ipv4 AS ip, switch_asociado AS id_switch_conectado FROM hosts;")
        if hosts_data is None:
            hosts_data = []

        enlaces_raw_data = fetch_all("""
            SELECT s1.nombre AS origen_nombre, s2.nombre AS destino_nombre,
                   e.id_origen, e.id_destino, e.ancho_banda
            FROM enlaces e
            JOIN switches s1 ON e.id_origen = s1.id_switch
            JOIN switches s2 ON e.id_destino = s2.id_switch;
        """)

        formatted_enlaces = []
        if enlaces_raw_data:
            for enlace in enlaces_raw_data:
                origen_switch = switches_by_id.get(enlace['id_origen'])
                destino_switch = switches_by_id.get(enlace['id_destino'])

                if origen_switch and destino_switch and \
                   origen_switch['latitud'] is not None and origen_switch['longitud'] is not None and \
                   destino_switch['latitud'] is not None and destino_switch['longitud'] is not None:

                    formatted_enlaces.append({
                        'origen_nombre': enlace['origen_nombre'],
                        'destino_nombre': enlace['destino_nombre'],
                        'id_origen': enlace['id_origen'],
                        'id_destino': enlace['id_destino'],
                        'ancho_banda': enlace['ancho_banda']
                    })
                else:
                    print(f"Advertencia: Enlace {enlace['id_origen']}-{enlace['id_destino']} omitido. Switches o coordenadas inválidas.")

        response_data = {
            "switches": formatted_switches,
            "hosts": hosts_data,
            "enlaces": formatted_enlaces
        }

        return jsonify(response_data), 200

    except Exception as e:
        print(f"Error en get_topology: {e}")
        return jsonify({"error": "Error interno del servidor al obtener la topología: " + str(e)}), 500


@topology_bp.route('/enlace', methods=['POST'])
def create_enlace():
    """
    Crea un nuevo enlace. JSON esperado: { id_origen, id_destino, ancho_banda }.
    """
    data = request.get_json() or {}
    try:
        io, id_, bw = int(data.get('id_origen')), int(data.get('id_destino')), int(data.get('ancho_banda'))
        if io <= 0 or id_ <= 0 or bw <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "Parámetros inválidos"}), 400

    try:
        rows_affected = execute_query("""
            INSERT INTO enlaces (id_origen, id_destino, ancho_banda)
            VALUES (%s, %s, %s)
        """, (io, id_, bw))
        
        if rows_affected > 0: 
            return jsonify({"message": f"Enlace {io}→{id_} creado con {bw} Mbps"}), 201
        else:
            return jsonify({"error": "No se pudo crear el enlace (0 filas afectadas)"}), 500
    except Exception as e:
        print(f"Error al crear enlace: {e}")
        return jsonify({"error": "Error interno del servidor al crear el enlace: " + str(e)}), 500

@topology_bp.route('/enlace', methods=['PUT'])
def update_enlace():
    """
    Actualiza el ancho de banda de un enlace existente.
    JSON esperado: { id_origen, id_destino, ancho_banda }.
    """
    data = request.get_json() or {}
    try:
        io, id_, bw = int(data.get('id_origen')), int(data.get('id_destino')), int(data.get('ancho_banda'))
        if io <= 0 or id_ <= 0 or bw <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "Parámetros inválidos"}), 400

    try:
        rows_affected = execute_query("""
            UPDATE enlaces
            SET ancho_banda = %s
            WHERE (id_origen = %s AND id_destino = %s)
               OR (id_origen = %s AND id_destino = %s);
        """, (bw, io, id_, id_, io)) 
        
        if rows_affected > 0: 
            return jsonify({"message": f"Enlace {io}↔{id_} actualizado a {bw} Mbps"}), 200
        else:
            return jsonify({"error": "Enlace no encontrado o no se realizaron cambios"}), 404
    except Exception as e:
        print(f"Error al actualizar enlace: {e}")
        return jsonify({"error": "Error interno del servidor al actualizar el enlace: " + str(e)}), 500

@topology_bp.route('/enlace', methods=['DELETE'])
def delete_enlace():
    """
    Elimina un enlace. JSON esperado: { id_origen, id_destino } (IDs de switch).
    """
    data = request.get_json() or {}
    # CORRECCIÓN: Obtener id_origen y id_destino del JSON
    origen_id = data.get('id_origen')
    destino_id = data.get('id_destino')

    # Validar que los IDs existan y sean números enteros positivos
    try:
        origen_id = int(origen_id)
        destino_id = int(destino_id)
        if origen_id <= 0 or destino_id <= 0:
            raise ValueError
    except (TypeError, ValueError):
        # Mensaje de error más específico para IDs inválidos
        return jsonify({"error": "Parámetros de ID de enlace inválidos (deben ser enteros positivos)"}), 400

    try:
        # Usar directamente los IDs para la eliminación
        rows_affected = execute_query("""
            DELETE FROM enlaces
            WHERE (id_origen = %s AND id_destino = %s)
               OR (id_origen = %s AND id_destino = %s);
        """, (origen_id, destino_id, destino_id, origen_id))

        if rows_affected > 0:
            # Mensaje de éxito que usa los IDs que fueron enviados
            return jsonify({"message": f"Enlace (IDs: {origen_id}↔{destino_id}) eliminado exitosamente"}), 200
        else:
            return jsonify({"error": "Enlace no encontrado o ya eliminado"}), 404
    except Exception as e:
        print(f"Error al eliminar enlace: {e}")
        return jsonify({"error": "Error interno del servidor al eliminar el enlace: " + str(e)}), 500

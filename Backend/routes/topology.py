from flask import Blueprint, jsonify, request
import psycopg2
import requests
from services.db import fetch_all, execute_query, fetch_one 
from config import Config
url_agent = Config.MININET_AGENT_URL

topology_bp = Blueprint('topology', __name__)

def verificar_agente_y_mininet():
    try:
        resp = requests.get(f"{url_agent}/mininet/status", timeout=3)
        if resp.status_code == 200:
            estado = resp.json()
            return estado.get("running", False)
        return False
    except Exception as e:
        print(f"[ERROR] No se pudo conectar al agente: {e}")
        return False

@topology_bp.route('/get', methods=['GET'])
def get_topology():
    """
    Endpoint para obtener la información completa de la topología (switches, hosts, enlaces).
    """
    try:
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
                    'status': sw['status']  
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

    data = request.get_json() or {}
    if not verificar_agente_y_mininet():
        return jsonify({"error": "Mininet o el agente no están activos. No se puede crear el enlace."}), 503
    
    try:
        io, id_, bw = int(data.get('id_origen')), int(data.get('id_destino')), int(data.get('ancho_banda'))
        if io <= 0 or id_ <= 0 or bw <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "Parámetros inválidos (deben ser enteros positivos)"}), 400

    try:
        # Inserción en 'enlaces'
        rows_affected = execute_query(
            """
            INSERT INTO enlaces (id_origen, id_destino, ancho_banda)
            VALUES (%s, %s, %s)
            """,
            (io, id_, bw)
        )
        if rows_affected <= 0:
            return jsonify({"error": "No se pudo crear el enlace (0 filas afectadas)"}), 500

        #  Calcular el siguiente puerto disponible en SWITCH ORIGEN (io)
        row_origen = fetch_one(
            """
            SELECT GREATEST(
                COALESCE((SELECT MAX(puerto_origen)  FROM puertos WHERE id_origen_switch  = %s), 0),
                COALESCE((SELECT MAX(puerto_destino) FROM puertos WHERE id_destino_switch = %s), 0)
            ) AS max_port
            """,
            (io, io)
        )
        next_port_origen = (row_origen['max_port'] or 0) + 1

        # Calcular el siguiente puerto disponible en SWITCH DESTINO (id_)
        row_destino = fetch_one(
            """
            SELECT GREATEST(
                COALESCE((SELECT MAX(puerto_origen)  FROM puertos WHERE id_origen_switch  = %s), 0),
                COALESCE((SELECT MAX(puerto_destino) FROM puertos WHERE id_destino_switch = %s), 0)
            ) AS max_port
            """,
            (id_, id_)
        )
        next_port_destino = (row_destino['max_port'] or 0) + 1

        # Insertar en 'puertos' el nuevo registro
        execute_query(
            """
            INSERT INTO puertos (
                nodo_origen,
                nodo_destino,
                puerto_origen,
                puerto_destino,
                id_origen_switch,
                id_destino_switch,
                id_origen_host,
                id_destino_host
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                str(io),       # nodo_origen 
                str(id_),      # nodo_destino
                next_port_origen,
                next_port_destino,
                io,            # id_origen_switch
                id_,           # id_destino_switch
                None,          # id_origen_host (NULL)
                None           # id_destino_host (NULL)
            )
        )

        # Notificar al agente Mininet para crear el patch-port en caliente
        agent_data = {}
        try:
            agent_resp = requests.post(
                f"{url_agent}/mininet/add_link",
                json={"id_origen": io, "id_destino": id_, "ancho_banda": bw},
                timeout=5
            )
            if agent_resp.headers.get("Content-Type", "").startswith("application/json"):
                agent_data = agent_resp.json()
            if agent_resp.status_code != 200:
                return jsonify({
                    "message": f"Enlace {io}→{id_} creado en BD con puertos {io}:{next_port_origen} ↔ {id_}:{next_port_destino}, "
                               "pero error al notificar a Mininet.",
                    "agent_error": agent_data
                }), 201
        except Exception as agent_err:
            return jsonify({
                "message": f"Enlace {io}→{id_} creado en BD con puertos {io}:{next_port_origen} ↔ {id_}:{next_port_destino}, "
                           "pero no se pudo comunicar con el agente Mininet.",
                "agent_error": str(agent_err)
            }), 201

        #  Responder con mensaje de éxito completo (BD + agente)
        return jsonify({
            "message": f"Enlace {io}→{id_} creado con {bw} Mbps; "
                       f"puertos asignados: {io}:{next_port_origen} ↔ {id_}:{next_port_destino}",
            "agent": agent_data
        }), 201

    except Exception as e:
        print(f"Error al crear enlace o asignar puertos: {e}")
        return jsonify({"error": "Error interno del servidor: " + str(e)}), 500


@topology_bp.route('/enlace', methods=['PUT'])
def update_enlace():
    """
    Actualiza un enlace existente. Puede actualizar solo el ancho de banda (mismos switches),
    o bien cambiar los switches ORIGINALES a unos NUEVOS, y a la vez actualizar el ancho.
    """
    data = request.get_json() or {}

    if not verificar_agente_y_mininet():
        return jsonify({"error": "Mininet o el agente no están activos. No se puede modificar el enlace."}), 503
    
    old_io   = data.get('old_id_origen')
    old_id_  = data.get('old_id_destino')
    new_io   = data.get('id_origen')
    new_id_  = data.get('id_destino')
    new_bw   = data.get('ancho_banda')

    try:
        new_io  = int(new_io)
        new_id_ = int(new_id_)
        new_bw  = int(new_bw)
        if new_io <= 0 or new_id_ <= 0 or new_bw <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "Parámetros inválidos para nuevos switches o ancho de banda"}), 400

    cambiar_switches = False
    if old_io is not None or old_id_ is not None:
        try:
            old_io  = int(old_io)
            old_id_ = int(old_id_)
            if old_io <= 0 or old_id_ <= 0:
                raise ValueError
            cambiar_switches = True
        except (TypeError, ValueError):
            return jsonify({"error": "Parámetros inválidos para old_id_origen/old_id_destino"}), 400

    if not cambiar_switches:
        old_io  = new_io
        old_id_ = new_id_

    try:
        enlace_existente = fetch_one("""
            SELECT 1 FROM enlaces
            WHERE (id_origen = %s AND id_destino = %s)
               OR (id_origen = %s AND id_destino = %s)
        """, (old_io, old_id_, old_id_, old_io))
        if not enlace_existente:
            return jsonify({"error": f"Enlace antiguo ({old_io}↔{old_id_}) no encontrado"}), 404

        if not cambiar_switches and (old_io == new_io and old_id_ == new_id_):
            rows_affected = execute_query("""
                UPDATE enlaces
                SET ancho_banda = %s
                WHERE (id_origen = %s AND id_destino = %s)
                   OR (id_origen = %s AND id_destino = %s)
            """, (new_bw, old_io, old_id_, old_id_, old_io))

            if rows_affected > 0:
                try:
                    agent_resp = requests.post(
                        f"{url_agent}/mininet/update_link",
                        json={
                            "old_id_origen": old_io,
                            "old_id_destino": old_id_,
                            "new_id_origen": new_io,
                            "new_id_destino": new_id_,
                            "ancho_banda": new_bw
                        },
                        timeout=5
                    )
                    agent_data = {}
                    if agent_resp.headers.get("Content-Type", "").startswith("application/json"):
                        agent_data = agent_resp.json()
                    if agent_resp.status_code != 200:
                        return jsonify({
                            "message": f"Ancho de banda de enlace ({new_io}↔{new_id_}) actualizado en BD a {new_bw} Mbps, pero error al notificar a Mininet.",
                            "agent_error": agent_data
                        }), 200
                except Exception as agent_err:
                    return jsonify({
                        "message": f"Ancho de banda de enlace ({new_io}↔{new_id_}) actualizado en BD a {new_bw} Mbps, pero no se pudo comunicar con el agente Mininet.",
                        "agent_error": str(agent_err)
                    }), 200

                return jsonify({
                    "message": f"Ancho de banda de enlace ({new_io}↔{new_id_}) actualizado a {new_bw} Mbps",
                    "agent": agent_data
                }), 200
            else:
                return jsonify({"error": "No se actualizaron los datos (sin cambios detectados)"}), 400

        execute_query("""
            UPDATE enlaces
            SET id_origen = %s,
                id_destino = %s,
                ancho_banda = %s
            WHERE (id_origen = %s AND id_destino = %s)
               OR (id_origen = %s AND id_destino = %s)
        """, (new_io, new_id_, new_bw, old_io, old_id_, old_id_, old_io))

        fila1 = fetch_one("""
            SELECT GREATEST(
              COALESCE((SELECT MAX(puerto_origen) FROM puertos WHERE id_origen_switch = %s), 0),
              COALESCE((SELECT MAX(puerto_destino) FROM puertos WHERE id_destino_switch = %s), 0)
            ) AS max_port
        """, (new_io, new_io))
        next_port_origen = (fila1['max_port'] or 0) + 1

        fila2 = fetch_one("""
            SELECT GREATEST(
              COALESCE((SELECT MAX(puerto_origen) FROM puertos WHERE id_origen_switch = %s), 0),
              COALESCE((SELECT MAX(puerto_destino) FROM puertos WHERE id_destino_switch = %s), 0)
            ) AS max_port
        """, (new_id_, new_id_))
        next_port_destino = (fila2['max_port'] or 0) + 1

        execute_query("""
            INSERT INTO puertos (
              nodo_origen, nodo_destino, puerto_origen, puerto_destino,
              id_origen_switch, id_destino_switch,
              id_origen_host, id_destino_host
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            str(new_io), str(new_id_),
            next_port_origen, next_port_destino,
            new_io, new_id_,
            None, None
        ))

        agent_resp = requests.post(
            f"{url_agent}/mininet/update_link",
            json={
                "old_id_origen": old_io,
                "old_id_destino": old_id_,
                "new_id_origen": new_io,
                "new_id_destino": new_id_,
                "ancho_banda": new_bw
            },
            timeout=5
        )
        agent_data = {}
        if agent_resp.headers.get("Content-Type", "").startswith("application/json"):
            agent_data = agent_resp.json()

        execute_query("""
            DELETE FROM puertos
            WHERE (id_origen_switch = %s AND id_destino_switch = %s)
               OR (id_origen_switch = %s AND id_destino_switch = %s)
        """, (old_io, old_id_, old_id_, old_io))

        if agent_resp.status_code != 200:
            return jsonify({
                "message": (
                    f"Enlace actualizado en BD, pero error al notificar a Mininet."
                ),
                "agent_error": agent_data
            }), 200

        return jsonify({
            "message": (
                f"Enlace actualizado: ({old_io}↔{old_id_}) → "
                f"({new_io}↔{new_id_}) con {new_bw} Mbps; "
                f"puertos asignados: {new_io}:{next_port_origen} ↔ {new_id_}:{next_port_destino}"
            ),
            "agent": agent_data
        }), 200

    except Exception as e:
        print(f"Error al actualizar enlace o puertos asociados: {e}")
        return jsonify({
            "error": "Error interno del servidor al actualizar enlace: " + str(e)
        }), 500


@topology_bp.route('/enlace', methods=['DELETE'])
def delete_enlace():
    """
    Elimina un enlace. JSON esperado: { id_origen, id_destino } (IDs de switch).
    También elimina la fila correspondiente en la tabla 'puertos' y notifica al agente Mininet.
    """
    data = request.get_json() or {}
    origen_id = data.get('id_origen')
    destino_id = data.get('id_destino')

    try:
        origen_id = int(origen_id)
        destino_id = int(destino_id)
        if origen_id <= 0 or destino_id <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({
            "error": "Parámetros de ID de enlace inválidos (deben ser enteros positivos)"
        }), 400

    try:
        rows_enlace = execute_query("""
            DELETE FROM enlaces
            WHERE (id_origen = %s AND id_destino = %s)
               OR (id_origen = %s AND id_destino = %s);
        """, (origen_id, destino_id, destino_id, origen_id))

        if rows_enlace > 0:
            try:
                agent_resp = requests.post(
                    f"{url_agent}/mininet/delete_link",
                    json={"id_origen": origen_id, "id_destino": destino_id},
                    timeout=5
                )
                agent_data = {}
                if agent_resp.headers.get("Content-Type", "").startswith("application/json"):
                    agent_data = agent_resp.json()

                execute_query("""
                    DELETE FROM puertos
                    WHERE (id_origen_switch = %s AND id_destino_switch = %s)
                       OR (id_origen_switch = %s AND id_destino_switch = %s);
                """, (origen_id, destino_id, destino_id, origen_id))

                if agent_resp.status_code != 200:
                    return jsonify({
                        "message": f"Enlace {origen_id}↔{destino_id} eliminado de BD, pero error al notificar a Mininet.",
                        "agent_error": agent_data
                    }), 200

            except Exception as agent_err:
                return jsonify({
                    "message": f"Enlace {origen_id}↔{destino_id} eliminado de BD, pero no se pudo comunicar con el agente Mininet.",
                    "agent_error": str(agent_err)
                }), 200

            return jsonify({
                "message": f"Enlace (IDs: {origen_id}↔{destino_id}) y registro de puertos asociado eliminado exitosamente.",
                "agent": agent_data
            }), 200
        else:
            return jsonify({
                "error": "Enlace no encontrado o ya eliminado"
            }), 404

    except Exception as e:
        print(f"Error al eliminar enlace o puertos asociados: {e}")
        return jsonify({
            "error": "Error interno del servidor al eliminar el enlace: " + str(e)
        }), 500



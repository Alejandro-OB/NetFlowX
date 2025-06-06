from flask import Blueprint, jsonify, request
import psycopg2
import psycopg2.extras
import collections
import heapq
import logging

from config import Config

dijkstra_bp = Blueprint('dijkstra', __name__)
logger = logging.getLogger(__name__)

# -------------------------------------------------------------------
# Diccionarios de topología (llenados en load_topology)
network_graph      = collections.defaultdict(dict)
switches_by_dpid   = {}   # { dpid_int: switch_nombre }
host_to_switch_map = {}   # { mac: { 'dpid': int, 'port': int, 'ip': str, 'name': str } }

# Mapeos auxiliares
id_map           = {}  # { id_switch: dpid_int }
id_to_name       = {}  # { id_switch: switch_nombre }
hosts_id_to_name = {}  # { id_host: host_nombre }
# -------------------------------------------------------------------

def _get_db_connection():
    try:
        return psycopg2.connect(Config.get_db_uri())
    except Exception as e:
        logger.error(f"Error conectando a la BD: {e}")
        return None


def load_topology():
    """
    Carga switches, hosts, puertos y enlaces en memory_graph, switches_by_dpid y host_to_switch_map.
    """
    global network_graph, switches_by_dpid, host_to_switch_map
    global id_map, id_to_name, hosts_id_to_name

    conn = _get_db_connection()
    if not conn:
        return

    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # 1) Cargar switches
        cur.execute("SELECT id_switch, nombre FROM switches")
        id_map.clear()
        id_to_name.clear()
        switches_by_dpid.clear()
        network_graph.clear()

        for row in cur.fetchall():
            dpid_str = "{:016x}".format(row['id_switch'])
            dpid_int = int(dpid_str, 16)

            id_map[row['id_switch']]     = dpid_int
            id_to_name[row['id_switch']] = row['nombre']
            switches_by_dpid[dpid_int]   = row['nombre']
            network_graph[dpid_int]      = {}

        # 2) Cargar hosts (para nombre y mapeo MAC→switch+puerto)
        cur.execute("SELECT id_host, nombre, switch_asociado, ipv4 AS ip, mac FROM hosts")
        hosts_id_to_name.clear()
        temp_host_rows = cur.fetchall()
        for row in temp_host_rows:
            hosts_id_to_name[row['id_host']] = row['nombre']

        # 3) Cargar puertos (usando las columnas FK)
        cur.execute("""
            SELECT
              id_origen_switch,
              id_origen_host,
              id_destino_switch,
              id_destino_host,
              puerto_origen,
              puerto_destino
            FROM puertos;
        """)
        puertos_dict = collections.defaultdict(dict)

        for row in cur.fetchall():
            # Nombre de origen
            if row['id_origen_switch'] is not None:
                origin_name = id_to_name.get(row['id_origen_switch'])
            else:
                origin_name = hosts_id_to_name.get(row['id_origen_host'])

            # Nombre de destino
            if row['id_destino_switch'] is not None:
                dest_name = id_to_name.get(row['id_destino_switch'])
            else:
                dest_name = hosts_id_to_name.get(row['id_destino_host'])

            if origin_name and dest_name:
                puertos_dict[origin_name][dest_name] = (
                    row['puerto_origen'],
                    row['puerto_destino']
                )

        # 4) Cargar enlaces en network_graph
        cur.execute("SELECT id_origen, id_destino, ancho_banda FROM enlaces")
        for row in cur.fetchall():
            id1   = row['id_origen']
            id2   = row['id_destino']
            ancho = row['ancho_banda']

            d1 = id_map.get(id1)
            d2 = id_map.get(id2)
            name1 = id_to_name.get(id1)
            name2 = id_to_name.get(id2)

            if d1 is None or d2 is None or name1 is None or name2 is None:
                continue

            cost = 1.0 / float(ancho) if ancho > 0 else float('inf')

            # puertos entre name1 y name2
            po12 = (
                puertos_dict.get(name1, {}).get(name2, (None, None))[0]
                or puertos_dict.get(name2, {}).get(name1, (None, None))[1]
                or 1
            )
            pi21 = (
                puertos_dict.get(name1, {}).get(name2, (None, None))[1]
                or puertos_dict.get(name2, {}).get(name1, (None, None))[0]
                or 1
            )
            po21 = (
                puertos_dict.get(name2, {}).get(name1, (None, None))[0]
                or puertos_dict.get(name1, {}).get(name2, (None, None))[1]
                or 1
            )
            pi12 = (
                puertos_dict.get(name2, {}).get(name1, (None, None))[1]
                or puertos_dict.get(name1, {}).get(name2, (None, None))[0]
                or 1
            )

            # Añadir aristas bidireccionales
            network_graph[d1][d2] = {
                'cost': cost,
                'port_out': po12,
                'port_in_neighbor': pi21
            }
            network_graph[d2][d1] = {
                'cost': cost,
                'port_out': po21,
                'port_in_neighbor': pi12
            }

        # 5) Construir host_to_switch_map
        host_to_switch_map.clear()
        for row in temp_host_rows:
            host_name   = row['nombre']
            switch_id   = row['switch_asociado']
            dpid        = id_map.get(switch_id)
            switch_name = id_to_name.get(switch_id)

            if dpid is None or switch_name is None:
                continue

            # Puerto en el switch al host
            port_host = 1
            if puertos_dict.get(switch_name, {}).get(host_name):
                port_host = puertos_dict[switch_name][host_name][0] or 1
            elif puertos_dict.get(host_name, {}).get(switch_name):
                port_host = puertos_dict[host_name][switch_name][1] or 1

            host_to_switch_map[row['mac']] = {
                'dpid': dpid,
                'port': port_host,
                'ip':   row['ip'],
                'name': host_name
            }

        logger.info(f"Topología cargada con {len(network_graph)} switches.")
    except Exception as e:
        logger.error(f"Error al cargar topología: {e}")
    finally:
        conn.close()


def calculate_dijkstra_path(start_dpid, end_dpid):
    """
    Dijkstra minimizando la suma de (1/ancho_banda) en cada enlace.
    Devuelve una lista de tuplas: [(dpid0, None, None), (dpid1, port_out, port_in), ...].
    """
    distances = {node: float('inf') for node in network_graph}
    distances[start_dpid] = 0
    heap = [(0, start_dpid, [(start_dpid, None, None)])]
    visited = set()

    while heap:
        cost, current, path = heapq.heappop(heap)
        if current in visited:
            continue
        visited.add(current)

        if current == end_dpid:
            return path

        for neighbor, link in network_graph[current].items():
            if neighbor in visited:
                continue
            new_cost = cost + link['cost']
            if new_cost < distances[neighbor]:
                distances[neighbor] = new_cost
                po = link.get('port_out')
                pi = link.get('port_in_neighbor')
                new_path = path + [(neighbor, po, pi)]
                heapq.heappush(heap, (new_cost, neighbor, new_path))

    return None


def calculate_shortest_path(start_dpid, end_dpid):
    """
    BFS puro: encuentra ruta con menor número de saltos.
    Devuelve lista de tuplas [(dpid0, None, None), (dpid1, port_out, port_in), ...].
    """
    visited = {start_dpid}
    queue = collections.deque()
    queue.append([(start_dpid, None, None)])

    while queue:
        path = queue.popleft()
        current = path[-1][0]

        if current == end_dpid:
            return path

        for neighbor, link in network_graph[current].items():
            if neighbor not in visited:
                visited.add(neighbor)
                po = link.get('port_out')
                pi = link.get('port_in_neighbor')
                new_path = path + [(neighbor, po, pi)]
                queue.append(new_path)

    return None



@dijkstra_bp.route('/calculate_path', methods=['POST'])
def calculate_path():
    """
    Espera JSON:
      { "src_mac": "AA:BB:CC:DD:EE:FF", "dst_mac": "11:22:33:44:55:66" }
    Lee 'algoritmo_enrutamiento' de la tabla configuracion:
      - "dijkstra"       → calculate_dijkstra_path
      - "shortest_path"  → calculate_shortest_path
    Reconstruye la ruta en la misma estructura que el código original:
      [ { "dpid":..., "out_port":..., "in_port":... }, ... ]
    """
    data = request.get_json(force=True)
    src_mac = data.get('src_mac')
    dst_mac = data.get('dst_mac')
    load_topology()
    
    src_info = host_to_switch_map.get(src_mac)
    dst_info = host_to_switch_map.get(dst_mac)
    if not src_info or not dst_info:
        return jsonify({"error": "MAC de origen o destino no encontrados"}), 400

    src_dpid = src_info['dpid']
    dst_dpid = dst_info['dpid']
    dst_port = dst_info['port']

    # 1) Leer algoritmo de la tabla 'configuracion'
    algoritmo = 'dijkstra'
    conn = _get_db_connection()
    if conn:
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cur.execute(
                "SELECT algoritmo_enrutamiento "
                "FROM configuracion "
                "ORDER BY fecha_activacion DESC "
                "LIMIT 1"
            )
            row = cur.fetchone()
            if row:
                alg = row['algoritmo_enrutamiento']
                if alg in ['dijkstra', 'shortest_path']:
                    algoritmo = alg
                else:
                    print(
                        f"[WARNING] Algoritmo desconocido en configuracion: {alg}. Usando 'dijkstra'."
                    )
            cur.close()
        except Exception as e:
            print(f"[ERROR] Error al leer configuracion: {e}")
        finally:
            conn.close()
    #print(f"Usando algoritmo de enrutamiento: {algoritmo}")
    # 2) Calcular ruta según algoritmo
    if algoritmo == 'shortest_path':
        raw_path = calculate_shortest_path(src_dpid, dst_dpid)
    else:
        raw_path = calculate_dijkstra_path(src_dpid, dst_dpid)

    if raw_path is None:
        return jsonify({"error": "No se encontró camino entre los nodos."}), 404

    # 3) Reconstruir en la misma estructura original
    formatted_path = []
    # raw_path = [(dpid0,None,None), (dpid1, port_out, port_in), ...]
    for i in range(len(raw_path)):
        dpid, out_p, in_p = raw_path[i]
        entry = {"dpid": dpid}

        if i == 0:
            # Primer salto: no hay in_port
            entry["in_port"] = None
            if len(raw_path) > 1:
                # Puerto de salida es port_out del primer enlace
                next_dpid = raw_path[i+1][0]
                link = network_graph.get(dpid, {}).get(next_dpid)
                entry["out_port"] = link["port_out"] if link else -1
            else:
                # Si start == end, salta directo al host
                entry["out_port"] = dst_port
        else:
            # Para i > 0, in_port viene de raw_path[i][2]
            entry["in_port"] = in_p if in_p is not None else -1

            if i < len(raw_path) - 1:
                # Puerto de salida hacia el siguiente switch
                next_dpid = raw_path[i+1][0]
                link_next = network_graph.get(dpid, {}).get(next_dpid)
                entry["out_port"] = link_next["port_out"] if link_next else -1
            else:
                # Último salto: el puerto de salida es el puerto del host destino
                entry["out_port"] = dst_port

        formatted_path.append(entry)

    return jsonify({"path": formatted_path}), 200


@dijkstra_bp.route('/calculate_multicast_tree', methods=['POST'])
def calculate_multicast_tree():
    """
    Calcula el árbol multicast a partir de un switch fuente hacia múltiples switches destino.
    Si algún enlace o puerto requerido no existe, se devuelve un error y NO se devuelve el árbol incompleto.
    """
    data = request.get_json(force=True)
    source_dpid = data.get('source_dpid')
    member_dpids = data.get('member_dpids')

    if source_dpid is None or not isinstance(member_dpids, list) or not member_dpids:
        return jsonify({"error": "source_dpid o member_dpids faltantes o mal formateados"}), 400

    load_topology()
    tree = {}

    for dst_dpid in member_dpids:
        if not isinstance(dst_dpid, int):
            continue

        path = calculate_dijkstra_path(source_dpid, dst_dpid)
        if not path:
            return jsonify({"error": f"No se encontró ruta hacia {dst_dpid}"}), 400

        for i in range(len(path) - 1):
            current_dpid = path[i][0]
            next_dpid = path[i + 1][0]

            enlace = network_graph.get(current_dpid, {}).get(next_dpid)
            if not enlace:
                return jsonify({"error": f"Enlace no encontrado entre {current_dpid} y {next_dpid}"}), 400

            port_out = enlace.get('port_out')
            if not isinstance(port_out, int) or port_out <= 0:
                return jsonify({"error": f"Puerto inválido entre {current_dpid} y {next_dpid}"}), 400

            tree.setdefault(current_dpid, set()).add(port_out)

    # Convertir a JSON serializable
    serialized_tree = {str(dpid): list(ports) for dpid, ports in tree.items()}

    # Agregar salida final hacia cada host conectado a los switches destino (hojas)
    for leaf_dpid in member_dpids:
        leaf_str = str(leaf_dpid)
        if leaf_str in serialized_tree:
            continue

        port_cliente = None
        for mac, info in host_to_switch_map.items():
            if info.get('dpid') == leaf_dpid:
                port_cliente = info.get('port')
                break

        if not isinstance(port_cliente, int) or port_cliente <= 0:
            return jsonify({"error": f"No se encontró puerto hacia cliente en switch {leaf_dpid}"}), 400

        serialized_tree[leaf_str] = [port_cliente]

    return jsonify({"tree": serialized_tree}), 200



@dijkstra_bp.route('/save_route', methods=['POST'])
def save_route():
    data = request.get_json()
    host_origen = data.get('host_origen')
    host_destino = data.get('host_destino')
    ruta = data.get('ruta')
    #print(f"Datos recibidos: {data}")

    algoritmo = 'dijkstra'
    conn = _get_db_connection()
    if conn:
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cur.execute(
                "SELECT algoritmo_enrutamiento "
                "FROM configuracion "
                "ORDER BY fecha_activacion DESC "
                "LIMIT 1"
            )
            row = cur.fetchone()
            if row:
                alg = row['algoritmo_enrutamiento']
                if alg in ['dijkstra', 'shortest_path']:
                    algoritmo = alg
                else:
                    print(
                        f"[WARNING] Algoritmo desconocido en configuracion: {alg}. Usando 'dijkstra'."
                    )
            cur.close()
        except Exception as e:
            print(f"[ERROR] Error al leer configuracion: {e}")
        finally:
            conn.close()
    if not all([host_origen, host_destino, ruta]):
        return jsonify({"error": "Faltan parámetros: host_origen, host_destino, ruta"}), 400

    try:
        # Verificar que los valores de host_origen y host_destino sean correctos
        logger.info(f"Guardando ruta entre {host_origen} y {host_destino}")

        # Obtener el ID de los hosts en la base de datos por nombre
        conn = _get_db_connection()
        cur = conn.cursor()

        # Consultar el ID del host de origen
        logger.info(f"Consultando ID para el host de origen: {host_origen}")
        cur.execute("SELECT id_host FROM hosts WHERE nombre = %s;", (host_origen,))
        origen_id = cur.fetchone()
        if not origen_id:
            return jsonify({"error": f"No se encontró el host de origen: {host_origen}"}), 404
        origen_id = origen_id[0]
        logger.info(f"ID de origen: {origen_id}")

        # Consultar el ID del host de destino
        logger.info(f"Consultando ID para el host de destino: {host_destino}")
        cur.execute("SELECT id_host FROM hosts WHERE nombre = %s;", (host_destino,))
        destino_id = cur.fetchone()
        if not destino_id:
            return jsonify({"error": f"No se encontró el host de destino: {host_destino}"}), 404
        destino_id = destino_id[0]
        logger.info(f"ID de destino: {destino_id}")

        # Insertar la ruta en la tabla rutas_ping
        cur.execute(
            "INSERT INTO rutas_ping (host_origen, host_destino, descripcion, algoritmo_enrutamiento) VALUES (%s, %s, %s, %s) RETURNING id_ruta;",
            (origen_id, destino_id, ruta, algoritmo)
        )
        id_ruta = cur.fetchone()[0]
        conn.commit()

        cur.close()
        conn.close()

        return jsonify({"success": True, "message": f"Ruta guardada con ID {id_ruta}"}), 200

    except Exception as e:
        logger.error(f"Error al guardar la ruta: {e}")
        return jsonify({"error": f"Error al guardar la ruta: {e}"}), 500

load_topology()

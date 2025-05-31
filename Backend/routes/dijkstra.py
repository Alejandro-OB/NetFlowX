from flask import Blueprint, jsonify, request
import psycopg2
import psycopg2.extras
import collections
import heapq
import logging

from config import Config

# Crear el blueprint
# ==========================
# Este archivo modifica la ruta /calculate_multicast_tree para incluir siempre

# Blueprint de Flask
dijkstra_bp = Blueprint('dijkstra', __name__)
logger = logging.getLogger(__name__)

# Diccionarios de topología
network_graph = collections.defaultdict(dict)
switches_by_dpid = {}
host_to_switch_map = {}  # Map: MAC -> { 'dpid': int, 'port': int, 'ip': str, 'name': str }


def _get_db_connection():
    try:
        return psycopg2.connect(Config.get_db_uri())
    except Exception as e:
        logger.error(f"Error de conexión a la base de datos: {e}")
        return None


def load_topology():
    global network_graph, switches_by_dpid, host_to_switch_map
    conn = _get_db_connection()
    if not conn:
        return
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # Cargar switches
        cur.execute("SELECT id_switch, nombre FROM switches")
        id_map = {}
        id_to_name = {}
        for row in cur.fetchall():
            dpid_str = "{:016x}".format(row['id_switch'])
            dpid_int = int(dpid_str, 16)
            switches_by_dpid[dpid_int] = row['nombre']
            id_map[row['id_switch']] = dpid_int
            id_to_name[row['id_switch']] = row['nombre']
            network_graph[dpid_int] = {}

        # Construir diccionario de puertos (host-switch y switch-switch)
        cur.execute("SELECT nodo_origen, nodo_destino, puerto_origen, puerto_destino FROM puertos")
        puertos_dict = collections.defaultdict(dict)
        for row in cur.fetchall():
            puertos_dict[row['nodo_origen']][row['nodo_destino']] = (row['puerto_origen'], row['puerto_destino'])

        # Cargar enlaces (bidireccionales) en network_graph
        cur.execute("SELECT id_origen, id_destino, ancho_banda FROM enlaces")
        for row in cur.fetchall():
            d1 = id_map.get(row['id_origen'])
            d2 = id_map.get(row['id_destino'])
            name1 = id_to_name.get(row['id_origen'])
            name2 = id_to_name.get(row['id_destino'])

            if d1 and d2 and name1 and name2:
                cost = 1.0 / float(row['ancho_banda']) if row['ancho_banda'] > 0 else float('inf')

                # Obtener puertos entre switches (origen->destino y destino->origen)
                po12 = puertos_dict.get(name1, {}).get(name2, (None, None))[0] or puertos_dict.get(name2, {}).get(name1, (None, None))[1] or 1
                pi21 = puertos_dict.get(name1, {}).get(name2, (None, None))[1] or puertos_dict.get(name2, {}).get(name1, (None, None))[0] or 1
                po21 = puertos_dict.get(name2, {}).get(name1, (None, None))[0] or puertos_dict.get(name1, {}).get(name2, (None, None))[1] or 1
                pi12 = puertos_dict.get(name2, {}).get(name1, (None, None))[1] or puertos_dict.get(name1, {}).get(name2, (None, None))[0] or 1

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

        # Cargar hosts y mapearlos a switches/puertos
        cur.execute("SELECT nombre, switch_asociado, ipv4 AS ip, mac FROM hosts")
        for row in cur.fetchall():
            dpid = id_map.get(row['switch_asociado'])
            switch_name = id_to_name.get(row['switch_asociado'])
            host_name = row['nombre']
            if dpid and switch_name:
                port_host = 1
                if puertos_dict.get(switch_name, {}).get(host_name):
                    port_host = puertos_dict[switch_name][host_name][0] or 1
                elif puertos_dict.get(host_name, {}).get(switch_name):
                    port_host = puertos_dict[host_name][switch_name][1] or 1

                host_to_switch_map[row['mac']] = {
                    'dpid': dpid,
                    'port': port_host,
                    'ip': row['ip'],
                    'name': host_name
                }

        logger.info(f"Topología cargada con {len(network_graph)} switches.")
        for dpid, neighbors in network_graph.items():
            logger.debug(f"Switch {dpid} ({switches_by_dpid.get(dpid, 'Unknown')}): conexiones -> {list(neighbors.keys())}")

    except Exception as e:
        logger.error(f"Error al cargar topología: {e}")
    finally:
        if conn:
            conn.close()


@dijkstra_bp.route('/calculate_path', methods=['POST'])
def calculate_path_endpoint():
    data = request.get_json()
    src_mac = data.get('src_mac')
    dst_mac = data.get('dst_mac')

    src_info = host_to_switch_map.get(src_mac)
    dst_info = host_to_switch_map.get(dst_mac)

    if not src_info or not dst_info:
        return jsonify({"error": "MAC de origen o destino no encontrados"}), 400

    src_dpid = src_info['dpid']
    dst_dpid = dst_info['dpid']
    dst_port = dst_info['port']

    if src_dpid == dst_dpid:
        return jsonify({
            "path": [{
                "dpid": src_dpid,
                "out_port": dst_port,
                "in_port": None
            }]
        }), 200

    path = calculate_dijkstra_path(src_dpid, dst_dpid)

    if not path:
        return jsonify({"error": "Ruta no encontrada"}), 404

    formatted_path = []

    for i in range(len(path)):
        dpid, _, _ = path[i]
        entry = {"dpid": dpid}

        if i == 0:
            if len(path) > 1:
                next_hop_dpid = path[i+1][0]
                link = network_graph[dpid].get(next_hop_dpid)
                entry["out_port"] = link["port_out"] if link else -1
            else:
                entry["out_port"] = dst_port
            entry["in_port"] = None
        else:
            prev_dpid = path[i-1][0]
            link = network_graph[prev_dpid].get(dpid)
            entry["in_port"] = link["port_in_neighbor"] if link else -1

            if i < len(path) - 1:
                next_hop_dpid = path[i+1][0]
                link = network_graph[dpid].get(next_hop_dpid)
                entry["out_port"] = link["port_out"] if link else -1
            else:
                entry["out_port"] = dst_port

        formatted_path.append(entry)

    return jsonify({"path": formatted_path}), 200


def calculate_dijkstra_path(start_dpid, end_dpid):
    distances = {node: float('inf') for node in network_graph}
    distances[start_dpid] = 0
    queue = [(0, start_dpid, [(start_dpid, None, None)])]
    visited = set()

    while queue:
        cost, current, path = heapq.heappop(queue)
        if current in visited:
            continue
        visited.add(current)

        if current == end_dpid:
            return path

        for neighbor, link in network_graph[current].items():
            if neighbor not in visited:
                new_cost = cost + link['cost']
                port_out = link.get('port_out')
                port_in_neighbor = link.get('port_in_neighbor')

                if port_out is None or port_in_neighbor is None:
                    logger.warning(f"Puertos inválidos para el enlace entre {current} y {neighbor}. Omitiendo este enlace.")
                    continue

                heapq.heappush(queue, (new_cost, neighbor, path + [(neighbor, port_out, port_in_neighbor)]))

    return None


@dijkstra_bp.route('/calculate_multicast_tree', methods=['POST'])
def calculate_multicast_tree():
    """
    Endpoint que recibe JSON con:
      {
        "source_dpid": <dpid_entero>,
        "member_dpids": [<dpid1>, <dpid2>, ...]
      }
    y devuelve el 'árbol multicast' en formato:
      {
        "tree": {
          "<dpid_str>": [<puerto1>, <puerto2>, ...],
          ...
        }
      }

    Modificado para extraer correctamente el puerto de salida de cada salto
    a partir del grafo network_graph, evitando que el switch fuente reciba None.
    Además inyecta cada leaf (cliente) con su puerto de host.
    """
    data = request.get_json()
    source_dpid = data.get('source_dpid')
    member_dpids = data.get('member_dpids')

    if source_dpid is None or not member_dpids:
        return jsonify({"error": "source_dpid o member_dpids faltantes"}), 400

    tree = {}

    # 1) Construir árbol basado en Dijkstra para cada miembro (sin leafs)
    for dst_dpid in member_dpids:
        path = calculate_dijkstra_path(source_dpid, dst_dpid)
        if not path:
            # Saltar si no hay ruta hacia este miembro
            continue

        # Para cada par de saltos (current -> next_hop) en la ruta:
        for i in range(len(path) - 1):
            current_dpid = path[i][0]
            next_hop_dpid = path[i + 1][0]

            enlace = network_graph.get(current_dpid, {}).get(next_hop_dpid)
            if not enlace:
                logger.warning(f"Enlace no encontrado en grafo: {current_dpid} → {next_hop_dpid}")
                continue

            port_out = enlace.get('port_out')
            if port_out is None:
                logger.warning(f"Puerto de salida nulo en enlace: {current_dpid} → {next_hop_dpid}")
                continue

            # Agregar port_out al set de puertos de current_dpid
            if current_dpid not in tree:
                tree[current_dpid] = set()
            tree[current_dpid].add(port_out)

    # 2) Convertir sets a listas y claves a strings para JSON
    serialized_tree = {str(dpid): list(ports) for dpid, ports in tree.items()}

    # 3) Inyectar cada leaf (cliente) con su puerto de salida hacia el host
    for leaf_dpid in member_dpids:
        leaf_str = str(leaf_dpid)
        if leaf_str in serialized_tree:
            continue

        # Buscar en host_to_switch_map algún host conectado a leaf_dpid
        port_cliente = None
        for mac, info in host_to_switch_map.items():
            if info.get('dpid') == leaf_dpid:
                port_cliente = info.get('port')
                break

        if port_cliente is None or not isinstance(port_cliente, int) or port_cliente <= 0:
            # Si no encontramos puerto, dejamos lista vacía para que el controlador haga fallback
            serialized_tree.setdefault(leaf_str, [])
        else:
            serialized_tree[leaf_str] = [port_cliente]

    return jsonify({"tree": serialized_tree}), 200

# Cargar topología al iniciar
load_topology()

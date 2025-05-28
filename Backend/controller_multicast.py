# Imports para PostgreSQL y Ryu
import psycopg2
import sys
import collections
import heapq
import threading
import time
import os

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, DEAD_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet
from ryu.lib.packet import ether_types
from ryu.lib.packet import arp
from ryu.lib.packet import ipv4
from ryu.lib.packet import icmp
from ryu.lib.packet import igmp
from ryu.lib.packet import tcp
from ryu.lib.packet import udp
from ryu.ofproto import inet
from ryu.controller import dpset # Importar dpset para eventos de datapath

import psycopg2.extras
from datetime import datetime

class DijkstraController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]
    _CONTEXTS = {}

    DB_CONFIG = {
        "dbname": os.getenv("DB_NAME", "geant_network"),
        "user": os.getenv("DB_USER", "geant_user"),
        "password": os.getenv("DB_PASSWORD", "geant"),
        "host": os.getenv("DB_HOST", "192.168.18.151"),
        "port": os.getenv("DB_PORT", "5432")
    }

    def __init__(self, *args, **kwargs):
        """
        Constructor del controlador.
        Inicializa las estructuras de datos y carga la topología de la base de datos.
        """
        super(DijkstraController, self).__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.net_graph = collections.defaultdict(dict)

        self.switches_by_dpid = {}
        self.id_switch_to_info = {}
        self.dpid_to_name = {}
        self.name_to_dpid = {}

        self.host_info = {}
        self.host_to_switch_map = {}
        self.host_mac_to_ip = {}
        self.host_ip_to_mac = {}
        self.host_ports = {}
        self.datapaths = {}

        self.VIP = '10.0.0.100'
        self.VIP_MAC = "00:00:00:00:00:AA"
        self.VIP_SERVICE_PORT = 8080
        self.active_web_servers = {}
        self.configured_lb_algorithm = 'round_robin'
        self.server_rr_index = 0
        self.client_to_server_map = {}
        self.lb_lock = threading.RLock()

        self.routing_config = {}

        self.load_topology_from_db()
        self._load_lb_config_and_servers()
        self._refresh_routing_config_from_db()
        self.db_lock = threading.Lock()
        self.topology_lock = threading.RLock()

        self.running = True
        self.logger.info("Aplicación de Controlador de Ruta Dijkstra/Balanceo de Carga de Ryu Inicializada")

        self.update_server_thread = threading.Thread(target=self._update_server_info_periodically)
        self.update_server_thread.daemon = True
        self.update_server_thread.start()

        self.config_monitor_thread = threading.Thread(target=self._monitor_config_changes)
        self.config_monitor_thread.daemon = True
        self.config_monitor_thread.start()
        self.logger.info("Hilos de monitoreo iniciados.")

    def _get_db_connection(self):
        """Establece y devuelve una conexión a la base de datos PostgreSQL."""
        try:
            conn = psycopg2.connect(**self.DB_CONFIG)
            return conn
        except psycopg2.Error as e:
            self.logger.error(f"Error al conectar a la base de datos: {e}")
            sys.exit(1)

    def fetch_all(self, query, params=None):
        """Ejecuta una consulta SELECT y devuelve todos los resultados como diccionarios."""
        conn = None
        try:
            conn = self._get_db_connection()
            cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cur.execute(query, params)
            results = [dict(row) for row in cur.fetchall()]
            cur.close()
            return results
        except psycopg2.Error as e:
            self.logger.error(f"Error al ejecutar consulta DB: {query} - {e}")
            return []
        finally:
            if conn:
                conn.close()

    def fetch_one(self, query, params=None):
        """Ejecuta una consulta SELECT y devuelve el primer resultado como diccionario."""
        conn = None
        try:
            conn = self._get_db_connection()
            cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cur.execute(query, params)
            result = cur.fetchone()
            cur.close()
            return dict(result) if result else None
        except psycopg2.Error as e:
            self.logger.error(f"Error al ejecutar consulta DB (fetch_one): {query} - {e}")
            return None
        finally:
            if conn:
                conn.close()

    def execute_query(self, query, params=None):
        """Ejecuta una consulta de INSERT/UPDATE/DELETE en la base de datos."""
        conn = None
        try:
            conn = self._get_db_connection()
            cur = conn.cursor()
            cur.execute(query, params)
            conn.commit()
            cur.close()
            return True
        except psycopg2.Error as e:
            self.logger.error(f"Error al ejecutar la consulta de actualización DB: {query} - {e}")
            return False
        finally:
            if conn:
                conn.close()

    def update_switch_status_in_db(self, dpid, status):
        """
        Actualiza el estado de un switch en la base de datos.
        """
        query = "UPDATE switches SET status = %s WHERE id_switch = %s;"
        with self.db_lock: # Usar el lock para acceso seguro a la DB
            if self.execute_query(query, (status, dpid)):
                self.logger.info(f"Estado del switch {dpid} actualizado a '{status}' en la base de datos.")
            else:
                self.logger.error(f"Fallo al actualizar el estado del switch {dpid} a '{status}' en la base de datos.")



    def registrar_servidor_asignado(self, nombre_cliente, nombre_servidor):
        """
        Registra en la base de datos el nombre del servidor asignado y la hora actual al cliente especificado.

        :param nombre_cliente: Nombre del host cliente (ej. 'h1_1')
        :param nombre_servidor: Nombre del host del servidor asignado (ej. 'h3_1')
        """
        update_query = """
            UPDATE clientes_activos
            SET servidor_asignado = %s,
                hora_asignacion = (NOW() AT TIME ZONE 'America/Bogota')
            WHERE host_cliente = %s;
        """
        try:
            with self.db_lock:
                self.execute_query(update_query, (nombre_servidor, nombre_cliente))
                self.logger.info(f"[DB] Asignado servidor '{nombre_servidor}' a cliente '{nombre_cliente}'.")
        except Exception as e:
            self.logger.error(f"[DB] Error al registrar servidor asignado: {e}")



    def load_topology_from_db(self):
        """
        Carga la topología de la red (switches, enlaces, hosts) desde la base de datos,
        poblando tanto las estructuras nuevas como las del controlador para compatibilidad.
        """
        self.logger.info("Cargando topología desde la base de datos...")
        self.net_graph = collections.defaultdict(dict)
        self.switches_by_dpid = {}
        self.id_switch_to_info = {}
        self.dpid_to_name = {}
        self.name_to_dpid = {}

        self.host_info = {}
        self.host_to_switch_map = {}
        self.host_mac_to_ip = {}
        self.host_ip_to_mac = {}
        self.host_ports = {}

        query_switches = "SELECT id_switch, nombre, switch_label, latitud, longitud FROM switches;"
        switches_data = self.fetch_all(query_switches)
        for s in switches_data:
            dpid = int(s['id_switch'])
            name = s['nombre']
            switch_label = s.get('switch_label', name)
            latitude = s.get('latitud')
            longitude = s.get('longitud')

            self.dpid_to_name[dpid] = name
            self.name_to_dpid[name] = dpid
            self.net_graph[dpid] = {}

            switch_info = {
                'dpid': dpid,
                'name': name,
                'label': switch_label,
                'latitude': latitude,
                'longitude': longitude
            }
            self.switches_by_dpid[dpid] = switch_info
            self.id_switch_to_info[dpid] = switch_info
            self.logger.info(f"Switch cargado: {name} (dpid={dpid}, lat={latitude}, lon={longitude})")

        query_enlaces = """
            SELECT p.nodo_origen, p.nodo_destino, p.puerto_origen, p.puerto_destino, e.ancho_banda
            FROM puertos p
            JOIN enlaces e ON (
                (p.nodo_origen = (SELECT nombre FROM switches WHERE id_switch = e.id_origen) AND p.nodo_destino = (SELECT nombre FROM switches WHERE id_switch = e.id_destino))
                OR
                (p.nodo_origen = (SELECT nombre FROM switches WHERE id_switch = e.id_destino) AND p.nodo_destino = (SELECT nombre FROM switches WHERE id_switch = e.id_origen))
            );
        """
        enlaces_data = self.fetch_all(query_enlaces)
        for link in enlaces_data:
            dpid_origen = self.name_to_dpid.get(link['nodo_origen'])
            dpid_destino = self.name_to_dpid.get(link['nodo_destino'])

            if dpid_origen is None or dpid_destino is None:
                self.logger.warning(f"Enlace con nodos desconocidos (switch/host): {link['nodo_origen']} <-> {link['nodo_destino']}. Saltando.")
                continue

            if dpid_origen in self.switches_by_dpid and dpid_destino in self.switches_by_dpid:
                port_origen = int(link['puerto_origen'])
                port_destino = int(link['puerto_destino'])
                ancho_banda = link['ancho_banda']

                hop_weight = 1
                if ancho_banda is not None and ancho_banda > 0:
                    bandwidth_weight = 1.0 / ancho_banda
                else:
                    bandwidth_weight = float('inf')

                self.net_graph[dpid_origen][dpid_destino] = {
                    'port': port_origen,
                    'bandwidth_weight': bandwidth_weight,
                    'hop_weight': hop_weight
                }
                self.net_graph[dpid_destino][dpid_origen] = {
                    'port': port_destino,
                    'bandwidth_weight': bandwidth_weight,
                    'hop_weight': hop_weight
                }
                self.logger.info(f"Enlace cargado: {link['nodo_origen']} (port {port_origen}) <-> {link['nodo_destino']} (port {port_destino}) con BW {ancho_banda} (peso BW: {bandwidth_weight:.4f}, peso saltos: {hop_weight})")
            else:
                self.logger.debug(f"Enlace {link['nodo_origen']}-{link['nodo_destino']} no es un enlace switch-switch, se maneja como host-switch.")

        query_hosts = """
            SELECT
                h.nombre AS host_name,
                h.ipv4,
                h.mac,
                s.id_switch AS dpid,
                CASE
                    WHEN p.nodo_origen = h.nombre THEN p.puerto_destino
                    WHEN p.nodo_destino = h.nombre THEN p.puerto_origen
                END AS port_no_on_switch
            FROM
                hosts h
            JOIN
                switches s ON h.switch_asociado = s.id_switch
            JOIN
                puertos p ON (
                    (p.nodo_origen = h.nombre AND p.nodo_destino = s.nombre) OR
                    (p.nodo_destino = h.nombre AND p.nodo_origen = s.nombre)
                );
        """
        hosts_data = self.fetch_all(query_hosts)
        for host in hosts_data:
            host_name = host['host_name']
            dpid = int(host['dpid'])
            port_on_switch = int(host['port_no_on_switch'])
            ip_address = host['ipv4']
            mac_address = host['mac']

            self.host_info[host_name] = {
                'dpid': dpid,
                'port': port_on_switch,
                'ip': ip_address,
                'mac': mac_address,
                'host_name': host_name
            }
            self.host_to_switch_map[host_name] = {'dpid': dpid, 'port': port_on_switch}
            self.host_mac_to_ip[mac_address] = ip_address
            self.host_ip_to_mac[ip_address] = mac_address
            self.host_ports[(dpid, host_name)] = port_on_switch
            self.logger.info(f"Host cargado: {host_name} (IP={ip_address}, MAC={mac_address}) en switch {dpid} puerto {port_on_switch}")
        self.logger.info("Carga de topología completada.")
        self.logger.debug(f"Contenido de self.host_info después de la carga: {self.host_info}")
        self.logger.debug(f"Contenido de self.host_mac_to_ip después de la carga: {self.host_mac_to_ip}")

    def _load_lb_config_and_servers(self):
        """
        Carga la configuración del algoritmo de balanceo y los servidores web activos desde la base de datos.
        """
        self.logger.debug("Cargando configuración de balanceo de carga y servidores activos...")

        query_lb_algo = "SELECT algoritmo_balanceo FROM configuracion ORDER BY fecha_activacion DESC LIMIT 1;"
        config_data = self.fetch_one(query_lb_algo)
        if config_data and config_data['algoritmo_balanceo']:
            self.configured_lb_algorithm = config_data['algoritmo_balanceo']
            self.logger.info(f"Algoritmo de balanceo de carga configurado: {self.configured_lb_algorithm}")
        else:
            self.logger.warning("No se encontró configuración de algoritmo de balanceo, usando 'round_robin' por defecto.")

        query_servers = """
            SELECT
                sv.host_name,
                h.ipv4,
                h.mac,
                sw.id_switch AS dpid,
                CASE
                    WHEN p.nodo_origen = h.nombre THEN p.puerto_destino
                    WHEN p.nodo_destino = h.nombre THEN p.puerto_origen
                END AS port_no,
                sv.server_weight
            FROM
                servidores_vlc_activos sv
            JOIN
                hosts h ON sv.host_name = h.nombre
            JOIN
                switches sw ON h.switch_asociado = sw.id_switch
            JOIN
                puertos p ON (
                    (p.nodo_origen = h.nombre AND p.nodo_destino = sw.nombre) OR
                    (p.nodo_destino = h.nombre AND p.nodo_origen = sw.nombre)
                )
            WHERE
                sv.status = 'activo';
        """
        servers_data = self.fetch_all(query_servers)
        self.active_web_servers = {}
        for server in servers_data:
            host_name = server['host_name']
            self.active_web_servers[host_name] = {
                'ip': server['ipv4'],
                'mac': server['mac'],
                'dpid': int(server['dpid']),
                'port': int(server['port_no']),
                'weight': server['server_weight'] if server['server_weight'] is not None else 1
            }
            self.logger.info(f"Servidor web activo cargado: {host_name} (IP={server['ipv4']}, MAC={server['mac']}) en switch {server['dpid']} puerto {server['port_no']}, peso={self.active_web_servers[host_name]['weight']}")

        if not self.active_web_servers:
            self.logger.warning("No se encontraron servidores web activos en la base de datos.")
        self.logger.debug("Carga de configuración de balanceo de carga y servidores activos completada.")

    def _refresh_routing_config_from_db(self):
        """
        Carga la configuración de enrutamiento desde la base de datos.
        Aquí podrías cargar parámetros como el tipo de enrutamiento (ej. "shortest_path", "dijkstra_bandwidth").
        """
        self.logger.debug("Cargando configuración de enrutamiento desde la base de datos...")
        query_routing_config = "SELECT algoritmo_enrutamiento FROM configuracion ORDER BY fecha_activacion DESC LIMIT 1;"
        config_data = self.fetch_one(query_routing_config)
        if config_data and config_data['algoritmo_enrutamiento']:
            self.routing_config['type'] = config_data['algoritmo_enrutamiento']
            self.logger.info(f"Tipo de enrutamiento configurado: {self.routing_config['type']}")
        else:
            self.logger.warning("No se encontró configuración de enrutamiento, usando 'shortest_path' por defecto.")
            self.routing_config['type'] = 'shortest_path'
        self.logger.debug("Carga de configuración de enrutamiento completada.")

    def _monitor_config_changes(self):
        """
        Hilo que monitorea periódicamente los cambios en la configuración de enrutamiento y balanceo de carga en la base de datos.
        """
        while self.running:
            self.logger.debug("Monitoreando cambios en la configuración...")
            self._refresh_routing_config_from_db()
            self._load_lb_config_and_servers()
            time.sleep(10)

    def _update_server_info_periodically(self):
        """
        Hilo que consulta periódicamente la base de datos para obtener
        la información de los servidores VLC activos y sus IPs multicast.
        (Adaptado para llamar a las funciones de carga de LB)
        """
        while True:
            with self.db_lock:
                self._load_lb_config_and_servers()
            time.sleep(10)

    def add_flow(self, datapath, priority, match, actions, idle_timeout=0, hard_timeout=0):
        """
        Añade una regla de flujo (flow entry) a un switch.
        """
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS,
                                             actions)]
        mod = parser.OFPFlowMod(datapath=datapath, priority=priority,
                                idle_timeout=idle_timeout,
                                hard_timeout=hard_timeout,
                                match=match, instructions=inst)
        datapath.send_msg(mod)
        self.logger.debug(f"Regla de flujo añadida al switch {datapath.id}: priority={priority}, match={match}, actions={actions}")

    def remove_flow_by_match(self, datapath, match):
        """
        Elimina flujos que coincidan con un match específico de un datapath.
        """
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        mod = parser.OFPFlowMod(datapath=datapath, command=ofproto.OFPFC_DELETE,
                                out_port=ofproto.OFPP_ANY, out_group=ofproto.OFPG_ANY,
                                match=match)
        datapath.send_msg(mod)
        self.logger.info(f"Flujo eliminado del switch {datapath.id} con match: {match}")

    def get_path_between_switches(self, src_dpid, dst_dpid):
        """
        Calcula la ruta más corta (usando Dijkstra) entre dos switches,
        basándose en el algoritmo de enrutamiento configurado.
        Devuelve una lista de tuplas (dpid_del_salto, puerto_de_salida_en_ese_dpid)
        empezando por el puerto de salida del src_dpid.
        """
        if src_dpid not in self.net_graph or dst_dpid not in self.net_graph:
            self.logger.error(f"DPID de origen ({src_dpid}) o destino ({dst_dpid}) no encontrado en el grafo de la red.")
            return None
        distances = {dpid: float('inf') for dpid in self.net_graph}
        distances[src_dpid] = 0
        previous_nodes = {dpid: None for dpid in self.net_graph}

        pq = [(0, src_dpid)]
        weight_key = 'hop_weight'
        if self.routing_config.get('type') == 'dijkstra':
            weight_key = 'bandwidth_weight'
            self.logger.debug(f"Calculando ruta usando algoritmo de Dijkstra (basado en ancho de banda).")
        else:
            self.logger.debug(f"Calculando ruta usando algoritmo de Shortest Path (menor número de saltos).")

        while pq:
            current_distance, current_dpid = heapq.heappop(pq)
            if current_distance > distances[current_dpid]:
                continue
            for neighbor_dpid, link_info in self.net_graph[current_dpid].items():
                weight = link_info[weight_key]
                distance = current_distance + weight
                if distance < distances[neighbor_dpid]:
                    distances[neighbor_dpid] = distance
                    previous_nodes[neighbor_dpid] = (current_dpid, link_info['port'])
                    heapq.heappush(pq, (distance, neighbor_dpid))
        path_segments = []
        current_trace = dst_dpid
        if distances[dst_dpid] == float('inf'):
            self.logger.warning(f"No se pudo encontrar una ruta de {src_dpid} a {dst_dpid}.")
            return None
        while current_trace != src_dpid:
            if previous_nodes[current_trace] is None:
                self.logger.error(f"Error al reconstruir la ruta: nodo {current_trace} no tiene predecesor, pero no es el origen.")
                return None
            prev_dpid, out_port = previous_nodes[current_trace]
            path_segments.insert(0, (prev_dpid, out_port))
            current_trace = prev_dpid

        return path_segments

    def select_server(self, client_ip, client_port=None, proto=None):
        """
        Selecciona un servidor backend basado en el algoritmo configurado.
        """
        self.logger.debug(f"[DEBUG] Entrando a select_server con client_ip={client_ip}, client_port={client_port}, proto={proto}")
        active_servers_list = list(self.active_web_servers.values())
        self.logger.debug(f"[DEBUG] Lista de servidores activos: {active_servers_list}")
        if not active_servers_list:
            self.logger.info("No hay servidores web activos disponibles para balanceo de carga.")
            return None
        self.logger.debug("[DEBUG] Esperando adquirir self.lb_lock...")
        with self.lb_lock:
            self.logger.debug("[DEBUG] Lock adquirido correctamente.")
            self.logger.debug(f"[DEBUG] Algoritmo de balanceo configurado: {self.configured_lb_algorithm}")
            if self.configured_lb_algorithm == 'round_robin':
                self.logger.debug(f"[DEBUG] RR: Usando Round Robin para seleccionar servidor.")
                server_info = active_servers_list[self.server_rr_index % len(active_servers_list)]
                self.logger.debug(f"[DEBUG] RR: Servidor seleccionado: {server_info}")
                self.server_rr_index += 1
                self.logger.debug(f"[DEBUG] RR: Servidor seleccionado: {server_info['ip']}")
                return server_info
            elif self.configured_lb_algorithm == 'weighted_round_robin':
                expanded_servers = []
                for s_name, s_info in self.active_web_servers.items():
                    expanded_servers.extend([s_info] * s_info['weight'])

                if not expanded_servers:
                    self.logger.warning("WRR: No hay servidores con pesos válidos, fallback a Round Robin.")
                    server_info = active_servers_list[self.server_rr_index % len(active_servers_list)]
                    self.server_rr_index += 1
                    return server_info
                server_info = expanded_servers[self.server_rr_index % len(expanded_servers)]
                self.server_rr_index += 1
                self.logger.info(f"[DEBUG] WRR: Servidor seleccionado: {server_info['ip']}")
                return server_info
            else:
                self.logger.info(f"[WARNING] Algoritmo '{self.configured_lb_algorithm}' no reconocido, usando Round Robin.")
                server_info = active_servers_list[self.server_rr_index % len(active_servers_list)]
                self.server_rr_index += 1
                return server_info

    def _send_packet_out(self, datapath, buffer_id, in_port, out_port, data):
        """Función auxiliar para enviar un mensaje PacketOut."""
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        actions = [parser.OFPActionOutput(out_port)]
        out = parser.OFPPacketOut(datapath=datapath, buffer_id=buffer_id,
                                   in_port=in_port, actions=actions, data=data)
        datapath.send_msg(out)

    @set_ev_cls(ofp_event.EventOFPStateChange,
                [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state_change_handler(self, ev):
        """
        Maneja los eventos de cambio de estado de los datapaths (switches).
        Actualiza el estado de conexión en la base de datos.
        """
        datapath = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            if datapath.id not in self.datapaths:
                self.logger.info("Switch conectado: %016x", datapath.id)
                self.datapaths[datapath.id] = datapath
                # Actualizar el estado del switch a 'conectado' en la base de datos
                self.update_switch_status_in_db(datapath.id, 'conectado')

                # Instala la regla de "table-miss" para enviar paquetes al controlador
                # cuando no hay otra regla que coincida.
                ofproto = datapath.ofproto
                parser = datapath.ofproto_parser
                match = parser.OFPMatch()
                actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                                  ofproto.OFPCML_NO_BUFFER)]
                self.add_flow(datapath, 0, match, actions) # Prioridad 0 (la más baja)
                self.logger.info(f"Switch {datapath.id} conectado y configurado con table-miss flow.")

        elif ev.state == DEAD_DISPATCHER:
            if datapath.id in self.datapaths:
                self.logger.info("Switch desconectado: %016x", datapath.id)
                del self.datapaths[datapath.id] # Corrected: datpath.id to datapath.id
                # Actualizar el estado del switch a 'desconectado' en la base de datos
                self.update_switch_status_in_db(datapath.id, 'desconectado')
            else:
                self.logger.warning(f"Evento de desconexión para DPID {datapath.id} no encontrado en datapaths.")


    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        dpid = datapath.id
        in_port = msg.match['in_port']
        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]
        dst_mac = eth.dst
        src_mac = eth.src
        eth_type = eth.ethertype
        self.logger.debug(f"PacketIn: dpid={dpid}, in_port={in_port}, src_mac={src_mac}, dst_mac={dst_mac}, eth_type={hex(eth_type)}")

        if dpid not in self.mac_to_port:
            self.mac_to_port[dpid] = {}
        if src_mac not in self.mac_to_port[dpid]:
            self.mac_to_port[dpid][src_mac] = in_port
            self.logger.debug(f"MAC aprendida: {src_mac} en switch {dpid} puerto {in_port}")

        if eth_type == ether_types.ETH_TYPE_IP:
            self.logger.debug(f"[DEBUG] eth_type IP: {hex(eth_type)}")
            ip_pkt = pkt.get_protocol(ipv4.ipv4)
            if ip_pkt:
                src_ip = ip_pkt.src
                dst_ip = ip_pkt.dst
                proto = ip_pkt.proto
                src_port = None
                dst_port = None

                if proto == inet.IPPROTO_TCP:
                    tcp_pkt = pkt.get_protocol(tcp.tcp)
                    if tcp_pkt:
                        src_port = tcp_pkt.src_port
                        dst_port = tcp_pkt.dst_port
                elif proto == inet.IPPROTO_UDP:
                    udp_pkt = pkt.get_protocol(udp.udp)
                    if udp_pkt:
                        src_port = udp_pkt.src_port
                        dst_port = udp_pkt.dst_port
                        self.logger.debug(f"[DEBUG] Paquete UDP: src={src_ip}:{src_port} -> dst={dst_ip}:{dst_port}")
                elif proto == inet.IPPROTO_ICMP:
                    icmp_pkt = pkt.get_protocol(icmp.icmp)
                    pass

                if dst_ip == self.VIP and (dst_port is None or dst_port == self.VIP_SERVICE_PORT):
                    self.logger.info(f"Solicitud a VIP {self.VIP}:{self.VIP_SERVICE_PORT} detectada de {src_ip}:{src_port} (Proto: {proto}) en dpid={dpid}")
                    selected_server_info = None
                    flow_key = (src_ip, self.VIP, proto, src_port, dst_port)
                    self.logger.debug(f"[DEBUG] Intentando asignar servidor a cliente {src_ip}:{src_port} -> {self.VIP}:{dst_port}")
                    self.logger.debug(f"[DEBUG] Flow_key = {flow_key}")
                    self.logger.debug(f"[DEBUG] Map actual: {self.client_to_server_map}")

                    with self.lb_lock:
                        if flow_key in self.client_to_server_map:
                            self.logger.debug(f"[DEBUG] verificando asignación previa para {flow_key}")
                            server_name_assigned = self.client_to_server_map[flow_key]
                            selected_server_info = self.active_web_servers.get(server_name_assigned)
                            if selected_server_info:
                                self.logger.info(f"Cliente {src_ip} ya asignado a {server_name_assigned} (persistencia).")
                            else:
                                self.logger.warning(f"Servidor {server_name_assigned} no activo, reasignando cliente {src_ip}.")
                                del self.client_to_server_map[flow_key]
                                selected_server_info = self.select_server(src_ip, src_port, proto)

                                if selected_server_info:
                                    for name, info in self.active_web_servers.items():
                                        if info == selected_server_info:
                                            self.client_to_server_map[flow_key] = name
                                            nombre_cliente = next((hn for hn, info in self.host_info.items() if info['ip'] == src_ip), None)
                                            if nombre_cliente:
                                                self.registrar_servidor_asignado(nombre_cliente, name)
                                            else:
                                                self.logger.warning(f"No se pudo determinar el nombre del cliente para IP {src_ip}")

                                            break
                        else:
                            self.logger.debug(f"[DEBUG] No hay asignación previa para {flow_key}, seleccionando nuevo servidor.")
                            selected_server_info = self.select_server(src_ip, src_port, proto)

                            if selected_server_info:
                                for name, info in self.active_web_servers.items():
                                    if info == selected_server_info:
                                        self.client_to_server_map[flow_key] = name
                                        nombre_cliente = next((hn for hn, info in self.host_info.items() if info['ip'] == src_ip), None)
                                        if nombre_cliente:
                                            self.registrar_servidor_asignado(nombre_cliente, name)
                                        else:
                                                self.logger.warning(f"No se pudo determinar el nombre del cliente para IP {src_ip}")
                                        break
                                self.logger.info(f"Asignando cliente {src_ip} a servidor {selected_server_info['ip']} (DPID={selected_server_info['dpid']}, Port={selected_server_info['port']}).")
                            else:
                                self.logger.error(f"No se pudo seleccionar un servidor backend para {src_ip} a {self.VIP}.")
                                self._send_packet_out(datapath, msg.buffer_id, in_port, ofproto.OFPP_CONTROLLER, msg.data)
                                return

                    if selected_server_info:
                        real_server_ip = selected_server_info['ip']
                        real_server_mac = selected_server_info['mac']
                        server_dpid = selected_server_info['dpid']
                        server_port = selected_server_info['port']
                        route_client_to_server_segments = self.get_path_between_switches(dpid, server_dpid)
                        if not route_client_to_server_segments:
                            self.logger.error(f"No se encontró ruta de switch {dpid} a switch del servidor {server_dpid} para el balanceador.")
                            self._send_packet_out(datapath, msg.buffer_id, in_port, ofproto.OFPP_CONTROLLER, msg.data)
                            return
                        self.logger.info(f"Ruta Cliente->Servidor (balanceador) calculada: {route_client_to_server_segments}")

                        match_client_to_vip = parser.OFPMatch(
                            eth_type=ether_types.ETH_TYPE_IP,
                            ipv4_src=src_ip,
                            ipv4_dst=self.VIP,
                            ip_proto=proto,
                            **({'tcp_src': src_port, 'tcp_dst': dst_port} if proto == inet.IPPROTO_TCP else {}),
                            **({'udp_src': src_port, 'udp_dst': dst_port} if proto == inet.IPPROTO_UDP else {})
                        )

                        initial_out_port_from_dpid = route_client_to_server_segments[0][1]
                        actions_client_to_server = [
                            parser.OFPActionSetField(ipv4_dst=real_server_ip),
                            parser.OFPActionSetField(eth_dst=real_server_mac),
                            parser.OFPActionOutput(initial_out_port_from_dpid)
                        ]

                        self.add_flow(datapath, 100, match_client_to_vip, actions_client_to_server, idle_timeout=300)
                        self.logger.debug(f"Regla instalada en {dpid}: Cliente {src_ip} -> VIP {self.VIP} redirigido a {real_server_ip}:{real_server_mac} via port {initial_out_port_from_dpid}")

                        for i in range(1, len(route_client_to_server_segments)):
                            current_hop_dpid = route_client_to_server_segments[i][0]
                            out_port = route_client_to_server_segments[i][1]

                            hop_datapath = self.datapaths.get(current_hop_dpid)
                            if not hop_datapath:
                                self.logger.error(f"Datapath para switch intermedio {current_hop_dpid} no encontrado.")
                                continue
                            match_intermediate = parser.OFPMatch(
                                eth_type=ether_types.ETH_TYPE_IP,
                                ipv4_dst=real_server_ip,
                                ip_proto=proto,
                                **({'tcp_dst': dst_port} if proto == inet.IPPROTO_TCP else {}),
                                **({'udp_dst': dst_port} if proto == inet.IPPROTO_UDP else {})
                            )
                            actions_intermediate = [parser.OFPActionOutput(out_port)]
                            self.add_flow(hop_datapath, 90, match_intermediate, actions_intermediate, idle_timeout=300)
                            self.logger.debug(f"Regla instalada en {current_hop_dpid} (intermedio): Tráfico a {real_server_ip} reenviado por port {out_port}")

                        server_datapath = self.datapaths.get(server_dpid)
                        if not server_datapath:
                            self.logger.error(f"Datapath para el switch del servidor {server_dpid} no encontrado.")
                            self._send_packet_out(datapath, msg.buffer_id, in_port, ofproto.OFPP_CONTROLLER, msg.data)
                            return

                        route_server_to_client_segments = self.get_path_between_switches(server_dpid, dpid)
                        if not route_server_to_client_segments:
                            self.logger.error(f"No se encontró ruta de switch del servidor {server_dpid} a switch del cliente {dpid} para el balanceador.")
                            self._send_packet_out(datapath, msg.buffer_id, in_port, ofproto.OFPP_CONTROLLER, msg.data)
                            return

                        self.logger.info(f"Ruta Servidor->Cliente (balanceador) calculada: {route_server_to_client_segments}")
                        out_port_from_server_dpid = route_server_to_client_segments[0][1]
                        match_server_to_client = parser.OFPMatch(
                            eth_type=ether_types.ETH_TYPE_IP,
                            ipv4_src=real_server_ip,
                            ipv4_dst=src_ip,
                            ip_proto=proto,
                            **({'tcp_src': dst_port, 'tcp_dst': src_port} if proto == inet.IPPROTO_TCP else {}),
                            **({'udp_src': dst_port, 'udp_dst': src_port} if proto == inet.IPPROTO_UDP else {})
                        )

                        actions_server_to_client = [
                            parser.OFPActionSetField(ipv4_src=self.VIP),
                            parser.OFPActionSetField(eth_src=self.VIP_MAC),
                            parser.OFPActionOutput(out_port_from_server_dpid)
                        ]

                        self.add_flow(server_datapath, 100, match_server_to_client, actions_server_to_client, idle_timeout=300)
                        self.logger.debug(f"Regla instalada en {server_dpid}: Servidor {real_server_ip} -> Cliente {src_ip} redirigido como {self.VIP} via port {out_port_from_server_dpid}")

                        for i in range(1, len(route_server_to_client_segments)):
                            current_hop_dpid = route_server_to_client_segments[i][0]
                            out_port = route_server_to_client_segments[i][1]

                            hop_datapath = self.datapaths.get(current_hop_dpid)
                            if not hop_datapath:
                                self.logger.error(f"Datapath para switch intermedio {current_hop_dpid} no encontrado.")
                                continue
                            match_intermediate = parser.OFPMatch(
                                eth_type=ether_types.ETH_TYPE_IP,
                                ipv4_src=self.VIP,
                                ipv4_dst=src_ip,
                                ip_proto=proto,
                                **({'tcp_dst': src_port} if proto == inet.IPPROTO_TCP else {}),
                                **({'udp_dst': src_port} if proto == inet.IPPROTO_UDP else {})
                            )
                            actions_intermediate = [parser.OFPActionOutput(out_port)]
                            self.add_flow(hop_datapath, 90, match_intermediate, actions_intermediate, idle_timeout=300)
                            self.logger.debug(f"Regla instalada en {current_hop_dpid} (intermedio): Tráfico de {self.VIP} a {src_ip} reenviado por port {out_port}")

                        modified_pkt = packet.Packet()
                        modified_pkt.add_protocol(ethernet.ethernet(
                            dst=real_server_mac,
                            src=eth.src,
                            ethertype=eth.ethertype
                        ))

                        new_ip_pkt = ipv4.ipv4(
                            version=ip_pkt.version,
                            tos=ip_pkt.tos,
                            total_length=ip_pkt.total_length,
                            identification=ip_pkt.identification,
                            flags=ip_pkt.flags,
                            offset=ip_pkt.offset,
                            ttl=ip_pkt.ttl,
                            proto=ip_pkt.proto,
                            csum=0,
                            src=ip_pkt.src,
                            dst=real_server_ip
                        )
                        modified_pkt.add_protocol(new_ip_pkt)
                        if proto == inet.IPPROTO_TCP:
                            tcp_pkt = pkt.get_protocol(tcp.tcp)
                            if tcp_pkt:
                                new_tcp_pkt = tcp.tcp(
                                    src_port=tcp_pkt.src_port,
                                    dst_port=tcp_pkt.dst_port,
                                    seq=tcp_pkt.seq,
                                    ack=tcp_pkt.ack,
                                    offset=tcp_pkt.offset,
                                    bits=tcp_pkt.bits,
                                    window_size=tcp_pkt.window_size,
                                    csum=0,
                                    urgent=tcp_pkt.urgent,
                                    option=tcp_pkt.option
                                )
                                modified_pkt.add_protocol(new_tcp_pkt)
                        elif proto == inet.IPPROTO_UDP:
                            udp_pkt = pkt.get_protocol(udp.udp)
                            if udp_pkt:
                                new_udp_pkt = udp.udp(
                                    src_port=udp_pkt.src_port,
                                    dst_port=udp_pkt.dst_port,
                                    total_length=udp_pkt.total_length,
                                    csum=0
                                )
                                modified_pkt.add_protocol(new_udp_pkt)
                        elif proto == inet.IPPROTO_ICMP:
                            icmp_pkt = pkt.get_protocol(icmp.icmp)
                            if icmp_pkt:
                                new_icmp_pkt = icmp.icmp(
                                    type_=icmp_pkt.type,
                                    code=icmp_pkt.code,
                                    csum=0,
                                    data=icmp_pkt.data
                                )
                                modified_pkt.add_protocol(new_icmp_pkt)
                        data = modified_pkt.serialize()
                        self._send_packet_out(datapath, ofproto.OFP_NO_BUFFER, in_port, initial_out_port_from_dpid, data)
                        self.logger.debug(f"Paquete inicial modificado y reenviado para {src_ip} a {real_server_ip} desde {dpid}.")
                        return

        if eth_type == ether_types.ETH_TYPE_ARP:
            arp_pkt = pkt.get_protocol(arp.arp)
            if arp_pkt:
                if arp_pkt.opcode == arp.ARP_REQUEST and arp_pkt.dst_ip == self.VIP:
                    self.logger.info(f"ARP Request para VIP {self.VIP} de {arp_pkt.src_ip} en dpid={dpid}, in_port={in_port}.")
                    self.reply_arp(datapath, eth, arp_pkt, self.VIP, self.VIP_MAC, in_port)
                    return
                elif arp_pkt.opcode == arp.ARP_REQUEST:
                    dst_host_info = next((info for name, info in self.host_info.items() if info['ip'] == arp_pkt.dst_ip), None)
                    if dst_host_info:
                        dst_dpid = dst_host_info['dpid']
                        src_host_dpid = dpid
                        if src_host_dpid == dst_dpid:
                            self.logger.info(f"ARP Request para {arp_pkt.dst_ip} (Host: {dst_host_info['host_name']}) en el mismo switch {src_host_dpid}. Respondiendo.")
                            self.reply_arp(datapath, eth, arp_pkt, dst_host_info['ip'], dst_host_info['mac'], in_port)
                            return
                        else:
                            self.logger.info(f"ARP Request para {arp_pkt.dst_ip} (Host: {dst_host_info['host_name']}) en otro switch. Instalando reglas bidireccionales ARP.")
                            path_request_segments = self.get_path_between_switches(src_host_dpid, dst_dpid)
                            if not path_request_segments:
                                self.logger.warning(f"No hay ruta para reenviar ARP request a {arp_pkt.dst_ip}.")
                                self._send_packet_out(datapath, msg.buffer_id, in_port, ofproto.OFPP_CONTROLLER, msg.data)
                                return

                            self.logger.info(f"Ruta ARP Request calculada: {path_request_segments}")
                            path_reply_segments = self.get_path_between_switches(dst_dpid, src_host_dpid)
                            if not path_reply_segments:
                                self.logger.warning(f"No hay ruta de retorno para ARP reply de {arp_pkt.dst_ip}.")
                                pass
                            else:
                                self.logger.info(f"Ruta ARP Reply calculada: {path_reply_segments}")
                            initial_out_port_req = path_request_segments[0][1]
                            match_req_orig = parser.OFPMatch(
                                eth_type=ether_types.ETH_TYPE_ARP,
                                arp_tpa=arp_pkt.dst_ip,
                                arp_op=arp.ARP_REQUEST
                            )
                            actions_req_orig = [parser.OFPActionOutput(initial_out_port_req)]
                            self.add_flow(datapath, 60, match_req_orig, actions_req_orig, idle_timeout=60)
                            self.logger.debug(f"Regla ARP Request instalada en {src_host_dpid}: para {arp_pkt.dst_ip} por port {initial_out_port_req}.")

                            for i in range(1, len(path_request_segments)):
                                current_hop_dpid = path_request_segments[i][0]
                                out_port = path_request_segments[i][1]
                                hop_datapath = self.datapaths.get(current_hop_dpid)
                                if not hop_datapath:
                                    self.logger.error(f"Datapath para switch intermedio ARP Request {current_hop_dpid} no encontrado.")
                                    continue
                                match_req_inter = parser.OFPMatch(
                                    eth_type=ether_types.ETH_TYPE_ARP,
                                    arp_tpa=arp_pkt.dst_ip,
                                    arp_op=arp.ARP_REQUEST
                                )
                                actions_req_inter = [parser.OFPActionOutput(out_port)]
                                self.add_flow(hop_datapath, 60, match_req_inter, actions_req_inter, idle_timeout=60)
                                self.logger.debug(f"Regla ARP Request instalada en {current_hop_dpid} (intermedio): para {arp_pkt.dst_ip} por port {out_port}.")

                            final_datapath_req = self.datapaths.get(dst_dpid)
                            if final_datapath_req:
                                match_req_final = parser.OFPMatch(
                                    eth_type=ether_types.ETH_TYPE_ARP,
                                    arp_tpa=arp_pkt.dst_ip,
                                    arp_op=arp.ARP_REQUEST
                                )
                                actions_req_final = [parser.OFPActionOutput(dst_host_info['port'])]
                                self.add_flow(final_datapath_req, 60, match_req_final, actions_req_final, idle_timeout=60)
                                self.logger.debug(f"Regla ARP Request instalada en {dst_dpid} (final): para {arp_pkt.dst_ip} a host por port {dst_host_info['port']}.")

                            if path_reply_segments:
                                initial_out_port_rep = path_reply_segments[0][1]
                                match_rep_orig = parser.OFPMatch(
                                    eth_type=ether_types.ETH_TYPE_ARP,
                                    arp_tpa=arp_pkt.src_ip,
                                    arp_op=arp.ARP_REPLY
                                )
                                self.add_flow(final_datapath_req, 60, match_rep_orig, [parser.OFPActionOutput(initial_out_port_rep)], idle_timeout=60)
                                self.logger.debug(f"Regla ARP Reply instalada en {dst_dpid}: para {arp_pkt.src_ip} por port {initial_out_port_rep}.")

                                for i in range(1, len(path_reply_segments)):
                                    current_hop_dpid_rep = path_reply_segments[i][0]
                                    out_port_rep = path_reply_segments[i][1]
                                    hop_datapath_rep = self.datapaths.get(current_hop_dpid_rep)
                                    if not hop_datapath_rep:
                                        self.logger.error(f"Datapath para switch intermedio ARP Reply {current_hop_dpid_rep} no encontrado.")
                                        continue
                                    match_rep_inter = parser.OFPMatch(
                                        eth_type=ether_types.ETH_TYPE_ARP,
                                        arp_tpa=arp_pkt.src_ip,
                                        arp_op=arp.ARP_REPLY
                                    )
                                    actions_rep_inter = [parser.OFPActionOutput(out_port_rep)]
                                    self.add_flow(hop_datapath_rep, 60, match_rep_inter, actions_rep_inter, idle_timeout=60)
                                    self.logger.debug(f"Regla ARP Reply instalada en {current_hop_dpid_rep} (intermedio): para {arp_pkt.src_ip} por port {out_port_rep}.")

                                final_datapath_rep_to_client = self.datapaths.get(src_host_dpid)
                                if final_datapath_rep_to_client:
                                    match_rep_final = parser.OFPMatch(
                                        eth_type=ether_types.ETH_TYPE_ARP,
                                        arp_tpa=arp_pkt.src_ip,
                                        arp_op=arp.ARP_REPLY
                                    )
                                    self.add_flow(final_datapath_rep_to_client, 60, match_rep_final, [parser.OFPActionOutput(in_port)], idle_timeout=60)
                                    self.logger.debug(f"Regla ARP Reply instalada en {src_host_dpid} (final, a cliente): para {arp_pkt.src_ip} a host por port {in_port}.")
                                else:
                                    self.logger.error(f"Datapath final para ARP Reply {src_host_dpid} no encontrado.")

                            self._send_packet_out(datapath, msg.buffer_id, in_port, initial_out_port_req, msg.data)
                            return
                    else:
                        self.logger.warning(f"ARP Request para IP desconocida {arp_pkt.dst_ip}. Flooding.")
                        self._send_packet_out(datapath, msg.buffer_id, in_port, ofproto.OFPP_FLOOD, msg.data)
                        return
                elif arp_pkt.opcode == arp.ARP_REPLY:
                    self.logger.info(f"ARP Reply de {arp_pkt.src_ip} ({arp_pkt.src_mac}) en dpid={dpid}, in_port={in_port}. Reenviando...")
                    if arp_pkt.dst_mac in self.mac_to_port[dpid]:
                        out_port = self.mac_to_port[dpid][arp_pkt.dst_mac]
                        self._send_packet_out(datapath, msg.buffer_id, in_port, out_port, msg.data)
                        self.logger.debug(f"ARP Reply reenviado directamente a {arp_pkt.dst_mac} en {dpid} puerto {out_port}.")
                    else:
                        self.logger.warning(f"ARP Reply para {arp_pkt.dst_mac} no tiene regla específica o MAC desconocida en {dpid}. Reenviando al controlador.")
                        self._send_packet_out(datapath, msg.buffer_id, in_port, ofproto.OFPP_CONTROLLER, msg.data)
                    return

        if eth_type == ether_types.ETH_TYPE_IP:
            ip_pkt = pkt.get_protocol(ipv4.ipv4)
            if ip_pkt:
                src_ip = ip_pkt.src
                dst_ip = ip_pkt.dst
                proto = ip_pkt.proto
                src_port = None
                dst_port = None

                if proto == inet.IPPROTO_TCP:
                    tcp_pkt = pkt.get_protocol(tcp.tcp)
                    if tcp_pkt:
                        src_port = tcp_pkt.src_port
                        dst_port = tcp_pkt.dst_port
                elif proto == inet.IPPROTO_UDP:
                    udp_pkt = pkt.get_protocol(udp.udp)
                    if udp_pkt:
                        src_port = udp_pkt.src_port
                        dst_port = udp_pkt.dst_port
                self.logger.debug(f"[DEBUG] UDP detectado: src_ip={src_ip}:{src_port} -> dst_ip={dst_ip}:{dst_port}")

                dst_host_info = next((info for name, info in self.host_info.items() if info['ip'] == dst_ip), None)
                if dst_host_info:
                    dst_switch_dpid = dst_host_info['dpid']
                    dst_host_port = dst_host_info['port']
                    self.logger.info(f"Destino unicast {dst_ip} (Host: {dst_host_info['host_name']}) encontrado en switch {dst_switch_dpid}.")
                    if dpid == dst_switch_dpid:
                        self.logger.info(f"Host {dst_host_info['host_name']} en el mismo switch {dpid}. Reenviando por puerto {dst_host_port}.")
                        actions = [parser.OFPActionOutput(dst_host_port)]
                        match = parser.OFPMatch(
                            eth_type=ether_types.ETH_TYPE_IP,
                            ipv4_dst=dst_ip,
                            ip_proto=proto,
                            **({'tcp_dst': dst_port} if proto == inet.IPPROTO_TCP else {}),
                            **({'udp_dst': dst_port} if proto == inet.IPPROTO_UDP else {})
                        )
                        self.add_flow(datapath, 10, match, actions, idle_timeout=300)
                        self._send_packet_out(datapath, msg.buffer_id, in_port, dst_host_port, msg.data)
                        return
                    route_segments = self.get_path_between_switches(dpid, dst_switch_dpid)
                    if route_segments:
                        self.logger.info(f"Ruta unicast IP {src_ip} -> {dst_ip} calculada: {route_segments}")
                        initial_out_port = route_segments[0][1]
                        actions_origin = [parser.OFPActionOutput(initial_out_port)]
                        match_origin = parser.OFPMatch(
                            eth_type=ether_types.ETH_TYPE_IP,
                            ipv4_src=src_ip,
                            ipv4_dst=dst_ip,
                            ip_proto=proto,
                            **({'tcp_src': src_port, 'tcp_dst': dst_port} if proto == inet.IPPROTO_TCP else {}),
                            **({'udp_src': src_port, 'udp_dst': dst_port} if proto == inet.IPPROTO_UDP else {})
                        )
                        self.add_flow(datapath, 10, match_origin, actions_origin, idle_timeout=300)
                        self.logger.debug(f"Regla unicast instalada en {dpid}: {src_ip} -> {dst_ip} por port {initial_out_port}")

                        for i in range(1, len(route_segments)):
                            current_hop_dpid = route_segments[i][0]
                            out_port = route_segments[i][1]

                            hop_datapath = self.datapaths.get(current_hop_dpid)
                            if not hop_datapath:
                                self.logger.error(f"Datapath para switch intermedio {current_hop_dpid} no encontrado.")
                                continue
                            match_intermediate = parser.OFPMatch(
                                eth_type=ether_types.ETH_TYPE_IP,
                                ipv4_dst=dst_ip,
                                ip_proto=proto,
                                **({'tcp_dst': dst_port} if proto == inet.IPPROTO_TCP else {}),
                                **({'udp_dst': dst_port} if proto == inet.IPPROTO_UDP else {})
                            )
                            actions_intermediate = [parser.OFPActionOutput(out_port)]
                            self.add_flow(hop_datapath, 10, match_intermediate, actions_intermediate, idle_timeout=300)
                            self.logger.debug(f"Regla unicast instalada en {current_hop_dpid} (intermedio): Tráfico a {dst_ip} reenviado por port {out_port}")

                        final_datapath = self.datapaths.get(dst_switch_dpid)
                        if final_datapath:
                            match_final = parser.OFPMatch(
                                eth_type=ether_types.ETH_TYPE_IP,
                                ipv4_dst=dst_ip,
                                ip_proto=proto,
                                **({'tcp_dst': dst_port} if proto == inet.IPPROTO_TCP else {}),
                                **({'udp_dst': dst_port} if proto == inet.IPPROTO_UDP else {})
                            )
                            actions_final = [parser.OFPActionOutput(dst_host_port)]
                            self.add_flow(final_datapath, 10, match_final, actions_final, idle_timeout=300)
                            self.logger.debug(f"Regla unicast instalada en {dst_switch_dpid} (destino): Tráfico a {dst_ip} reenviado a host por port {dst_host_port}")
                        else:
                            self.logger.error(f"Datapath para switch de destino {dst_switch_dpid} no encontrado para unicast.")

                        route_return_segments = self.get_path_between_switches(dst_switch_dpid, dpid)
                        if route_return_segments:
                            self.logger.info(f"Ruta de retorno unicast IP {dst_ip} -> {src_ip} calculada: {route_return_segments}")
                            initial_out_port_return = route_return_segments[0][1]
                            match_return_origin = parser.OFPMatch(
                                eth_type=ether_types.ETH_TYPE_IP,
                                ipv4_src=dst_ip,
                                ipv4_dst=src_ip,
                                ip_proto=proto,
                                **({'tcp_src': dst_port, 'tcp_dst': src_port} if proto == inet.IPPROTO_TCP else {}),
                                **({'udp_src': dst_port, 'udp_dst': src_port} if proto == inet.IPPROTO_UDP else {})
                            )
                            self.add_flow(final_datapath, 10, match_return_origin, [parser.OFPActionOutput(initial_out_port_return)], idle_timeout=300)
                            self.logger.debug(f"Regla unicast retorno instalada en {dst_switch_dpid}: {dst_ip} -> {src_ip} por port {initial_out_port_return}")

                            for i in range(1, len(route_return_segments)):
                                current_hop_dpid_return = route_return_segments[i][0]
                                out_port_return = route_return_segments[i][1]
                                hop_datapath_return = self.datapaths.get(current_hop_dpid_return)
                                if not hop_datapath_return:
                                    self.logger.error(f"Datapath para switch intermedio retorno {current_hop_dpid_return} no encontrado.")
                                    continue
                                match_return_intermediate = parser.OFPMatch(
                                    eth_type=ether_types.ETH_TYPE_IP,
                                    ipv4_src=dst_ip,
                                    ipv4_dst=src_ip,
                                    ip_proto=proto,
                                    **({'tcp_src': dst_port, 'tcp_dst': src_port} if proto == inet.IPPROTO_TCP else {}),
                                    **({'udp_src': dst_port, 'udp_dst': src_port} if proto == inet.IPPROTO_UDP else {})
                                )
                                actions_return_intermediate = [parser.OFPActionOutput(out_port_return)]
                                self.add_flow(hop_datapath_return, 10, match_return_intermediate, actions_return_intermediate, idle_timeout=300)
                                self.logger.debug(f"Regla unicast retorno instalada en {current_hop_dpid_return} (intermedio): Tráfico de {dst_ip} a {src_ip} reenviado por port {out_port_return}")

                            final_datapath_return_to_client = self.datapaths.get(dpid)
                            if final_datapath_return_to_client:
                                match_return_final = parser.OFPMatch(
                                    eth_type=ether_types.ETH_TYPE_IP,
                                    ipv4_src=dst_ip,
                                    ipv4_dst=src_ip,
                                    ip_proto=proto,
                                    **({'tcp_src': dst_port, 'tcp_dst': src_port} if proto == inet.IPPROTO_TCP else {}),
                                    **({'udp_src': dst_port, 'udp_dst': src_port} if proto == inet.IPPROTO_UDP else {})
                                )
                                actions_return_final = [parser.OFPActionOutput(in_port)]
                                self.add_flow(final_datapath_return_to_client, 10, match_return_final, actions_return_final, idle_timeout=300)
                                self.logger.debug(f"Regla unicast retorno instalada en {dpid} (final, a cliente): Tráfico de {dst_ip} a {src_ip} a host por port {in_port}.")
                            else:
                                self.logger.error(f"Datapath final para retorno unicast {dpid} no encontrado.")
                        else:
                            self.logger.warning(f"No hay ruta de retorno de {dst_switch_dpid} a {dpid} para unicast IP.")
                        self._send_packet_out(datapath, msg.buffer_id, in_port, initial_out_port, msg.data)
                        self.logger.debug(f"Paquete inicial unicast IP enviado desde el switch de origen {dpid} puerto {initial_out_port}.")
                        return
                    else:
                        self.logger.warning(f"No hay ruta desde {dpid} a {dst_switch_dpid} para {src_ip} -> {dst_ip}, descartando paquete.")
                        return

        self.logger.debug(f"Paquete no manejado: src={src_mac}, dst={dst_mac}, eth_type={eth.ethertype} en dpid={dpid}, in_port={in_port}. Enviando al controlador.")
        self._send_packet_out(datapath, msg.buffer_id, in_port, ofproto.OFPP_CONTROLLER, msg.data)

    def reply_arp(self, datapath, eth_pkt, arp_pkt, reply_ip, reply_mac, in_port):
        """
        Envía una respuesta ARP para una IP virtual o un host.
        """
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        ether_proto = eth_pkt.ethertype
        hwtype = arp_pkt.hwtype
        proto = arp_pkt.proto
        hlen = arp_pkt.hlen
        plen = arp_pkt.plen
        opcode = arp.ARP_REPLY

        arp_reply = packet.Packet()
        arp_reply.add_protocol(ethernet.ethernet(
            dst=eth_pkt.src,
            src=reply_mac,
            ethertype=ether_proto
        ))
        arp_reply.add_protocol(arp.arp(
            hwtype=hwtype,
            proto=proto,
            hlen=hlen,
            plen=plen,
            opcode=opcode,
            src_mac=reply_mac,
            src_ip=reply_ip,
            dst_mac=arp_pkt.src_mac,
            dst_ip=arp_pkt.src_ip
        ))
        arp_reply.serialize()
        actions = [parser.OFPActionOutput(in_port)]
        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=ofproto.OFP_NO_BUFFER,
            in_port=ofproto.OFPP_CONTROLLER,
            actions=actions,
            data=arp_reply.data
        )
        datapath.send_msg(out)
        self.logger.info(f"ARP Reply enviado para {reply_ip} ({reply_mac}) a {arp_pkt.src_ip} en dpid={datapath.id} puerto {in_port}.")

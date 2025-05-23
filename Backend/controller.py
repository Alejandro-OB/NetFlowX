# Imports para PostgreSQL y Ryu
import psycopg2
import sys
import collections
import heapq
import threading # Importar para hilos
import time      # Importar para pausas

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet
from ryu.lib.packet import ether_types
from ryu.lib.packet import arp
from ryu.lib.packet import ipv4
from ryu.lib.packet import icmp

class DijkstraController(app_manager.RyuApp):
    # Define las versiones de OpenFlow soportadas
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        """
        Constructor del controlador.
        Inicializa las estructuras de datos y carga la topología de la base de datos.
        """
        super(DijkstraController, self).__init__(*args, **kwargs)
        # Diccionario para mapear dpid a {dirección MAC -> puerto de salida}
        self.mac_to_port = {}

        # Estructuras para la topología cargada de la base de datos
        # Mapea dpid (entero) a nombre de switch de Mininet (ej. 's1')
        self.switches_by_dpid = {}
        # Mapea MAC de host (string) a {'dpid': dpid del switch, 'port': puerto del switch al host, 'ip': IP del host, 'name': nombre del host}
        self.host_to_switch_map = {}
        # Grafo de la red: dpid_origen -> {dpid_destino: {'cost': costo_ancho_banda, 'shortest_path_cost': 1, 'port_out': puerto_en_origen, 'port_in_neighbor': puerto_en_destino}}
        self.network_graph = collections.defaultdict(dict)
        # Almacena objetos datapath para enviar reglas de flujo a cualquier switch
        self.datapaths = {}

        # Variable para almacenar el algoritmo de enrutamiento seleccionado desde la DB
        # Por defecto, se usa Dijkstra (basado en ancho de banda)
        self.routing_algorithm = "dijkstra"

        # Bandera para controlar el hilo de monitoreo de configuración
        self.running = True
        # Hilo para monitorear cambios en la configuración de la base de datos
        self.config_monitor_thread = threading.Thread(target=self._monitor_config_changes)
        self.config_monitor_thread.daemon = True # Permite que el hilo se cierre cuando el programa principal lo haga

        self.logger.info("Aplicación de Controlador de Ruta Dijkstra/Camino más Corto de Ryu Inicializada")
        # Carga la topología y la configuración de enrutamiento desde la base de datos
        self._load_topology_from_db()

        # Inicia el hilo de monitoreo de configuración después de la carga inicial
        self.config_monitor_thread.start()
        self.logger.info("Hilo de monitoreo de configuración iniciado.")

    def _load_topology_from_db(self):
        """
        Carga la topología de la red (switches, hosts, enlaces, puertos, ancho de banda)
        desde la base de datos PostgreSQL y construye la representación interna del grafo.
        También carga la configuración del algoritmo de enrutamiento.
        """
        conn = None
        cur = None
        try:
            # --- Configuración de la base de datos ---
            conn = psycopg2.connect(
                dbname="geant_network",
                user="geant_user",
                password="geant",
                host="192.168.18.151",
                port="5432"
            )
            cur = conn.cursor()
            self.logger.info("Conexión a la base de datos establecida.")

            # 1. Obtener switches
            cur.execute("SELECT id_switch, nombre FROM switches;")
            switch_list = cur.fetchall()
            for id_switch, ciudad in switch_list:
                dpid = int(id_switch)
                self.switches_by_dpid[dpid] = f's{id_switch}'
                # Inicializa la entrada del grafo para este switch
                self.network_graph[dpid] = {}
                self.logger.debug(f"Switch cargado: s{id_switch} ({ciudad}) DPID: {dpid}")

            # 2. Obtener hosts y mapearlos a switches/puertos
            cur.execute("SELECT nombre, switch_asociado, ipv4, mac FROM hosts;")
            hosts_list = cur.fetchall()

            # Obtener información de puertos para conexiones host-switch y switch-switch
            # La clave es (nodo_origen, nodo_destino) y el valor es (puerto_origen, puerto_destino)
            puertos_dict = {}
            cur.execute("SELECT nodo_origen, nodo_destino, puerto_origen, puerto_destino FROM puertos;")
            for nodo_origen, nodo_destino, puerto_origen_val, puerto_destino_val in cur.fetchall():
                # Asegura que los puertos sean enteros o None
                puerto_origen_int = int(puerto_origen_val) if puerto_origen_val is not None else None
                puerto_destino_int = int(puerto_destino_val) if puerto_destino_val is not None else None
                puertos_dict[(nodo_origen, nodo_destino)] = (puerto_origen_int, puerto_destino_int)

            # Cargar hosts con el puerto correcto según los nombres reales
            for nombre_host, id_switch_asociado, ip, mac in hosts_list:
                # Busca el nombre de la ciudad del switch asociado
                ciudad_switch = None
                for s_id, s_nombre in switch_list:
                    if s_id == id_switch_asociado:
                        ciudad_switch = s_nombre
                        break

                self.logger.info(f"Buscando puerto para el host {nombre_host} conectado al switch {ciudad_switch}")

                if ciudad_switch and (ciudad_switch, nombre_host) in puertos_dict:
                    # El puerto de origen en el switch es el que va hacia el host
                    puerto_en_switch_a_host = puertos_dict[(ciudad_switch, nombre_host)][0]
                    self.host_to_switch_map[mac] = {
                        'dpid': int(id_switch_asociado),
                        'port': puerto_en_switch_a_host,
                        'ip': ip,
                        'name': nombre_host
                    }
                    self.logger.info(f"Puerto encontrado para el host {nombre_host}: puerto {puerto_en_switch_a_host} en el switch {ciudad_switch}")
                else:
                    self.logger.warning(f"No se encontró puerto para el host {nombre_host} conectado al switch {ciudad_switch}")

            # 3. Obtener enlaces switch-switch y construir el grafo
            cur.execute("SELECT id_origen, id_destino, ancho_banda FROM enlaces;")
            enlaces_list = cur.fetchall()

            for id_origen, id_destino, bw in enlaces_list:
                dpid_origen = int(id_origen)
                dpid_destino = int(id_destino)

                ciudad_origen = None
                ciudad_destino = None
                for s_id, s_nombre in switch_list:
                    if s_id == id_origen:
                        ciudad_origen = s_nombre
                    if s_id == id_destino:
                        ciudad_destino = s_nombre
                    if ciudad_origen and ciudad_destino:
                        break

                self.logger.info(f"Buscando puertos para el enlace {ciudad_origen} <-> {ciudad_destino}")

                port_origen_to_destino = None
                port_destino_to_origen = None

                # Busca los puertos en ambas direcciones (origen->destino y destino->origen)
                if (ciudad_origen, ciudad_destino) in puertos_dict:
                    port_origen_to_destino = puertos_dict[(ciudad_origen, ciudad_destino)][0]
                    port_destino_to_origen = puertos_dict[(ciudad_origen, ciudad_destino)][1]
                elif (ciudad_destino, ciudad_origen) in puertos_dict:
                    # Si el enlace está definido en la dirección opuesta en puertos_dict
                    port_origen_to_destino = puertos_dict[(ciudad_destino, ciudad_origen)][1]
                    port_destino_to_origen = puertos_dict[(ciudad_destino, ciudad_origen)][0]

                if port_origen_to_destino is None or port_destino_to_origen is None:
                    self.logger.warning(f"No se encontró puerto para el enlace {ciudad_origen} <-> {ciudad_destino}, se omite para el cálculo de Dijkstra")
                    continue

                # Calcula el costo basado en el ancho de banda (para Dijkstra)
                cost = 1.0 / float(bw) if bw and float(bw) > 0 else float('inf')
                # Para el Camino más Corto (Shortest Path), el costo es 1 por salto
                shortest_path_cost = 1

                # Agrega el enlace al grafo en ambas direcciones con ambos costos
                self.network_graph[dpid_origen][dpid_destino] = {
                    'cost': cost,
                    'shortest_path_cost': shortest_path_cost,
                    'port_out': port_origen_to_destino,
                    'port_in_neighbor': port_destino_to_origen
                }
                self.network_graph[dpid_destino][dpid_origen] = {
                    'cost': cost,
                    'shortest_path_cost': shortest_path_cost,
                    'port_out': port_destino_to_origen,
                    'port_in_neighbor': port_origen_to_destino
                }
                self.logger.info(f"Enlace cargado: {ciudad_origen} puerto {port_origen_to_destino} <--> {ciudad_destino} puerto {port_destino_to_origen}")

            # 4. Obtener la configuración del algoritmo de enrutamiento de la tabla 'configuracion'
            # Esta parte se ha movido a _refresh_routing_config_from_db para ser llamada periódicamente
            self._refresh_routing_config_from_db()

        except psycopg2.Error as e:
            self.logger.error(f"Error de base de datos durante la carga inicial de topología: {e}")
            sys.exit(1)
        except Exception as e:
            self.logger.error(f"Error inesperado al cargar la topología: {e}")
            sys.exit(1)
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()
            self.logger.info("Conexión a la base de datos cerrada (carga inicial).")
            self.logger.info(f"Cargados {len(self.switches_by_dpid)} switches y {len(self.host_to_switch_map)} hosts.")
            self.logger.debug(f"Grafo de la red: {self.network_graph}")

    def _refresh_routing_config_from_db(self):
        """
        Refresca la configuración del algoritmo de enrutamiento desde la base de datos.
        Esta función está diseñada para ser llamada periódicamente.
        """
        conn = None
        cur = None
        try:
            conn = psycopg2.connect(
                dbname="geant_network",
                user="geant_user",
                password="geant",
                host="192.168.18.151",
                port="5432"
            )
            cur = conn.cursor()
            cur.execute("SELECT algoritmo_enrutamiento FROM configuracion ORDER BY fecha_activacion DESC LIMIT 1;")
            config_result = cur.fetchone()
            if config_result:
                new_algorithm = config_result[0]
                if self.routing_algorithm != new_algorithm:
                    self.routing_algorithm = new_algorithm
                    self.logger.info(f"Algoritmo de enrutamiento actualizado a: {self.routing_algorithm}")
            else:
                self.logger.warning("No se encontró configuración de enrutamiento en la base de datos. Manteniendo el algoritmo actual.")

        except psycopg2.Error as e:
            self.logger.error(f"Error de base de datos al refrescar la configuración: {e}")
        except Exception as e:
            self.logger.error(f"Error inesperado al refrescar la configuración: {e}")
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    def _monitor_config_changes(self):
        """
        Hilo que monitorea periódicamente los cambios en la configuración de enrutamiento en la base de datos.
        """
        while self.running:
            self.logger.debug("Monitoreando cambios en la configuración de enrutamiento...")
            self._refresh_routing_config_from_db()
            time.sleep(10) # Espera 10 segundos antes de la siguiente consulta

    def _dijkstra_path(self, start_dpid, end_dpid, use_shortest_path_cost=False):
        """
        Calcula la ruta más corta utilizando el algoritmo de Dijkstra.
        Puede usar 'cost' (basado en ancho de banda) o 'shortest_path_cost' (basado en número de saltos).

        Args:
            start_dpid (int): DPID del switch de origen.
            end_dpid (int): DPID del switch de destino.
            use_shortest_path_cost (bool): Si es True, usa el costo de salto (1 por enlace);
                                           si es False, usa el costo basado en ancho de banda.

        Returns:
            list: Una lista de tuplas que representan la ruta:
                  [(dpid_actual, puerto_salida_desde_anterior, puerto_entrada_al_actual), ...]
                  Retorna None si no se encuentra una ruta.
        """
        distances = {node: float('inf') for node in self.network_graph}
        distances[start_dpid] = 0
        # path_info almacena (dpid, puerto_salida_desde_nodo_previo, puerto_entrada_a_nodo_actual)
        priority_queue = [(0, start_dpid, [(start_dpid, None, None)])]
        visited = set()

        while priority_queue:
            current_cost, current_dpid, path_info = heapq.heappop(priority_queue)

            if current_dpid in visited:
                continue
            visited.add(current_dpid)

            if current_dpid == end_dpid:
                return path_info

            for neighbor_dpid, link_info in self.network_graph[current_dpid].items():
                if neighbor_dpid not in visited:
                    if use_shortest_path_cost:
                        cost = link_info['shortest_path_cost']
                    else:
                        cost = link_info['cost'] # Este es el costo basado en ancho de banda

                    port_out = link_info['port_out'] # Puerto de salida en current_dpid hacia neighbor_dpid
                    port_in_neighbor = link_info['port_in_neighbor'] # Puerto de entrada en neighbor_dpid desde current_dpid

                    new_cost = current_cost + cost
                    if new_cost < distances[neighbor_dpid]:
                        distances[neighbor_dpid] = new_cost
                        heapq.heappush(priority_queue, (new_cost, neighbor_dpid, path_info + [(neighbor_dpid, port_out, port_in_neighbor)]))
        return None

    def _get_path(self, start_dpid, end_dpid):
        """
        Función que decide qué algoritmo de enrutamiento usar (Dijkstra o Shortest Path)
        basándose en la configuración cargada de la base de datos y llama a la función
        _dijkstra_path con el parámetro de costo adecuado.

        Args:
            start_dpid (int): DPID del switch de origen.
            end_dpid (int): DPID del switch de destino.

        Returns:
            list: La ruta calculada, o None si no se encuentra.
        """
        path = None
        if self.routing_algorithm == "dijkstra":
            self.logger.info("Calculando ruta usando Dijkstra (basado en ancho de banda).")
            path = self._dijkstra_path(start_dpid, end_dpid, use_shortest_path_cost=False)
        elif self.routing_algorithm == "shortest_path":
            self.logger.info("Calculando ruta usando Shortest Path (basado en número de saltos).")
            path = self._dijkstra_path(start_dpid, end_dpid, use_shortest_path_cost=True)
        else:
            self.logger.warning(f"Algoritmo de enrutamiento desconocido: {self.routing_algorithm}. Usando Dijkstra por defecto.")
            path = self._dijkstra_path(start_dpid, end_dpid, use_shortest_path_cost=False)
        return path


    def add_flow(self, datapath, priority, match, actions, buffer_id=None, idle_timeout=0, hard_timeout=0):
        """
        Función auxiliar para añadir una entrada de flujo a un switch.

        Args:
            datapath (ryu.controller.controller.Datapath): Objeto datapath del switch.
            priority (int): Prioridad de la regla de flujo.
            match (ryu.ofproto.ofproto_v1_3_parser.OFPMatch): Objeto de coincidencia para la regla.
            actions (list): Lista de acciones para la regla.
            buffer_id (int, optional): ID del búfer del paquete. Por defecto es None.
            idle_timeout (int, optional): Tiempo de inactividad antes de que la regla expire. Por defecto es 0 (nunca expira por inactividad).
            hard_timeout (int, optional): Tiempo máximo de vida de la regla. Por defecto es 0 (nunca expira).
        """
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(datapath=datapath, buffer_id=buffer_id if buffer_id is not None else ofproto.OFP_NO_BUFFER,
                                 priority=priority, match=match,
                                 instructions=inst,
                                 idle_timeout=idle_timeout,
                                 hard_timeout=hard_timeout)
        datapath.send_msg(mod)
        self.logger.debug(f"Regla de flujo añadida al switch {datapath.id}: priority={priority}, match={match}, actions={actions}")

    def _send_arp_reply(self, datapath, target_mac, target_ip, src_mac, src_ip, out_port):
        """
        Envía una respuesta ARP proxy.

        Args:
            datapath (ryu.controller.controller.Datapath): Objeto datapath del switch.
            target_mac (str): MAC del host que envió la solicitud ARP.
            target_ip (str): IP del host que envió la solicitud ARP.
            src_mac (str): MAC del host cuya IP se está solicitando (la MAC que estamos respondiendo).
            src_ip (str): IP del host cuya MAC se está solicitando.
            out_port (int): Puerto por donde enviar la respuesta ARP.
        """
        parser = datapath.ofproto_parser
        # Construye el encabezado Ethernet
        eth = ethernet.ethernet(dst=target_mac, src=src_mac, ethertype=ether_types.ETH_TYPE_ARP)
        # Construye el paquete ARP de respuesta
        arp_reply = arp.arp(opcode=arp.ARP_REPLY,
                            src_mac=src_mac, src_ip=src_ip,
                            dst_mac=target_mac, dst_ip=target_ip)
        # Crea el paquete completo
        pkt = packet.Packet()
        pkt.add_protocol(eth)
        pkt.add_protocol(arp_reply)
        pkt.serialize() # Serializa el paquete para enviarlo

        actions = [parser.OFPActionOutput(out_port)]
        out = parser.OFPPacketOut(datapath=datapath,
                                 buffer_id=0xffffffff, # No usar un buffer_id existente, enviar el paquete completo
                                 in_port=datapath.ofproto.OFPP_CONTROLLER, # El paquete se origina en el controlador
                                 actions=actions,
                                 data=pkt.data)
        datapath.send_msg(out)
        self.logger.info(f"Respuesta ARP proxy enviada: {src_ip} está en {src_mac} a {target_mac}")

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        """
        Maneja el evento de características del switch.
        Instala una regla de flujo predeterminada para enviar todos los paquetes no coincidentes al controlador.
        También almacena el objeto datapath para uso futuro (ej. instalar flujos en otros switches).
        """
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        # Almacena el objeto datapath en el diccionario para acceder a él más tarde
        self.datapaths[datapath.id] = datapath

        # Instala una entrada de flujo de tabla-miss (prioridad 0)
        # Una coincidencia vacía (match=parser.OFPMatch()) coincide con todos los paquetes
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)] # Envía al controlador sin almacenar en búfer
        match = parser.OFPMatch()
        self.add_flow(datapath, 0, match, actions)
        self.logger.info(f"Regla de flujo predeterminada instalada para el switch {datapath.id}")

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        """
        Maneja el evento Packet-In, que ocurre cuando un switch envía un paquete al controlador.
        Realiza el aprendizaje de MAC, maneja ARP y calcula/instala rutas.
        """
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match['in_port'] # Puerto de entrada del paquete en el switch

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if not eth:
            # Si no hay encabezado Ethernet, ignora el paquete
            return

        # Ignorar paquetes LLDP e IPv6
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return
        if eth.ethertype == ether_types.ETH_TYPE_IPV6:
            self.logger.debug(f"Ignorando paquete IPv6 en el switch {datapath.id}")
            return

        dst_mac = eth.dst # MAC de destino del paquete
        src_mac = eth.src # MAC de origen del paquete
        dpid = datapath.id # DPID del switch que envió el Packet-In
        self.mac_to_port.setdefault(dpid, {}) # Asegura que el dpid exista en mac_to_port

        self.logger.info(f"Paquete entrante: switch={dpid} src={src_mac} dst={dst_mac} in_port={in_port} ethertype={eth.ethertype:04x}")

        # Aprendizaje de MAC: Asocia la MAC de origen con el puerto de entrada en este switch
        first_octet_src_int = int(src_mac.split(':')[0], 16)
        is_src_multicast = (first_octet_src_int & 1) == 1
        if not is_src_multicast: # Solo aprende MACs unicast
            if src_mac not in self.mac_to_port[dpid]:
                self.mac_to_port[dpid][src_mac] = in_port
                self.logger.info(f"MAC aprendida: switch={dpid} mac={src_mac} port={in_port}")

        first_octet_dst_int = int(dst_mac.split(':')[0], 16)
        is_dst_multicast = (first_octet_dst_int & 1) == 1

        # Manejo de ARP proxy
        if eth.ethertype == ether_types.ETH_TYPE_ARP:
            arp_pkt = pkt.get_protocol(arp.arp)
            if arp_pkt:
                if arp_pkt.opcode == arp.ARP_REQUEST:
                    target_ip = arp_pkt.dst_ip
                    # Busca la MAC del target_ip en los hosts conocidos
                    for mac, info in self.host_to_switch_map.items():
                        if info['ip'] == target_ip:
                            # Si se encuentra, envía una respuesta ARP proxy
                            self._send_arp_reply(datapath, src_mac, arp_pkt.src_ip, mac, target_ip, in_port)
                            return # Termina el procesamiento del paquete ARP
                # Para ARP reply, se deja fluir normalmente (se maneja como unicast si la MAC es conocida)

        # Si el destino es multicast/broadcast (incluyendo solicitudes ARP no respondidas), inunda el paquete
        if is_dst_multicast:
            out_port = ofproto.OFPP_FLOOD
            self.logger.info(f"Inundando paquete multicast/broadcast en switch={dpid} dst={dst_mac}")
            # Envía el paquete inundado
            data = None
            if msg.buffer_id == ofproto.OFP_NO_BUFFER:
                data = msg.data
            out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                                       in_port=in_port, actions=[parser.OFPActionOutput(out_port)],
                                       data=data)
            datapath.send_msg(out)
            self.logger.debug(f"Paquete enviado desde switch {dpid} puerto {out_port}")
            return # Termina el procesamiento

        else: # Caso unicast
            # Primero, verifica si el destino está directamente conectado a este switch (MAC aprendida localmente)
            if dst_mac in self.mac_to_port[dpid]:
                out_port = self.mac_to_port[dpid][dst_mac]
                self.logger.info(f"Destino conocido en switch={dpid} dst={dst_mac} port={out_port}. Instalando flujo directo.")
                match = parser.OFPMatch(eth_src=src_mac, eth_dst=dst_mac)
                actions = [parser.OFPActionOutput(out_port)]
                # Añade la regla de flujo
                self.add_flow(datapath, 100, match, actions, msg.buffer_id, idle_timeout=60, hard_timeout=300)
                
                # Envía el paquete después de instalar el flujo
                data = None
                if msg.buffer_id == ofproto.OFP_NO_BUFFER:
                    data = msg.data
                out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                                           in_port=in_port, actions=actions, data=data)
                datapath.send_msg(out)
                self.logger.debug(f"Paquete enviado desde switch {dpid} puerto {out_port} (ruta directa).")
                return # Importante: salir después de manejar la ruta directa

            # Si no está directamente conectado, intenta encontrar la ruta a través del mapa de host a switch
            elif dst_mac in self.host_to_switch_map:
                dst_host_info = self.host_to_switch_map[dst_mac]
                dst_switch_dpid = dst_host_info['dpid'] # DPID del switch al que está conectado el host de destino
                dst_switch_port_to_host = dst_host_info['port'] # Puerto en el switch de destino que va al host

                self.logger.info(f"Host de destino {dst_mac} en switch {dst_switch_dpid} puerto {dst_switch_port_to_host}")

                # --- Llama a la función que decide el algoritmo de enrutamiento ---
                path = self._get_path(dpid, dst_switch_dpid)
                # --- FIN de la llamada a la función de enrutamiento ---

                self.logger.info("Detalles de la ruta calculada:")
                if path:
                    for idx, (switch_id, out_port_path, in_port_path) in enumerate(path):
                        self.logger.info(f"  Salto {idx}: Switch={switch_id}, out_port={out_port_path}, in_port={in_port_path}")
                else:
                    self.logger.info("  No se encontró ruta.")

                if path:
                    self.logger.info(f"Ruta encontrada: {path}")
                    
                    # Instalar flujos en todos los switches a lo largo de la ruta
                    for i, (cur_dpid_in_path, out_port_to_next_in_path, in_port_from_prev_in_path) in enumerate(path):
                        # Asegurar que el dpid sea un entero para la búsqueda
                        cur_dpid_int = int(cur_dpid_in_path) if isinstance(cur_dpid_in_path, str) else cur_dpid_in_path

                        cur_dp = self.datapaths.get(cur_dpid_int)
                        if not cur_dp:
                            self.logger.error(f"Datapath faltante para el switch {cur_dpid_int}, omitiendo la instalación de flujo")
                            continue

                        actual_out_port = None
                        if i == len(path) - 1: # Si es el último switch en la ruta
                            actual_out_port = dst_switch_port_to_host # El puerto de salida es al host final
                        else: # Si es un switch intermedio
                            # El puerto de salida es el puerto hacia el siguiente salto en la ruta
                            actual_out_port = path[i+1][1]

                        if not isinstance(actual_out_port, int) or actual_out_port <= 0:
                            self.logger.error(f"Puerto de salida inválido ({actual_out_port}) para el switch {cur_dpid_int} en la ruta. Omitiendo la instalación de flujo.")
                            continue

                        # Construye la regla de flujo para este switch
                        match = parser.OFPMatch(eth_src=src_mac, eth_dst=dst_mac)
                        actions = [parser.OFPActionOutput(actual_out_port)]

                        # Solo usa buffer_id para la primera instalación de flujo en el switch de origen
                        # Esto evita que el paquete se reenvíe dos veces desde el primer switch
                        buffer_id_use = msg.buffer_id if cur_dpid_int == dpid and msg.buffer_id != ofproto.OFP_NO_BUFFER else ofproto.OFP_NO_BUFFER

                        self.add_flow(cur_dp, 100, match, actions, buffer_id_use, idle_timeout=60, hard_timeout=300)
                        self.logger.info(f"Flujo instalado en switch {cur_dpid_int} para {src_mac}->{dst_mac} a través del puerto {actual_out_port}")

                    # --- IMPORTANTE: Envía el paquete inicial desde el datapath *original* ---
                    # El puerto de salida para el paquete inicial será el puerto de salida del primer salto.
                    # Si el path tiene un solo elemento, significa que el origen y el destino están en el mismo switch,
                    # por lo que el puerto de salida es al host final.
                    initial_out_port = None
                    if len(path) > 1:
                        initial_out_port = path[1][1] # Puerto del primer switch al segundo switch en la ruta
                    else:
                        initial_out_port = dst_switch_port_to_host # Puerto del switch al host final

                    if initial_out_port is not None and isinstance(initial_out_port, int) and initial_out_port > 0:
                        data = None
                        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
                            data = msg.data

                        out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                                                   in_port=in_port, actions=[parser.OFPActionOutput(initial_out_port)],
                                                   data=data)
                        datapath.send_msg(out)
                        self.logger.debug(f"Paquete inicial enviado desde el switch de origen {dpid} puerto {initial_out_port}.")
                    else:
                        self.logger.error(f"Fallo al enviar el paquete inicial: initial_out_port inválido ({initial_out_port}) desde el cálculo de la ruta.")
                    return # Salir después de manejar la ruta y enviar el paquete

                else:
                    self.logger.warning(f"No hay ruta desde {dpid} a {dst_switch_dpid} para {src_mac} -> {dst_mac}, descartando paquete")
                    return
            else:
                self.logger.info(f"Destino unicast desconocido {dst_mac} en switch {dpid}, descartando paquete")
                return

        # Esta sección es un fallback y principalmente para paquetes multicast/broadcast (como solicitudes ARP)
        # que no fueron manejados por el proxy ARP o si out_port es OFPP_FLOOD.
        data = None
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data

        if out_port is not None:
            out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                                       in_port=in_port, actions=[parser.OFPActionOutput(out_port)],
                                       data=data)
            datapath.send_msg(out)
            self.logger.debug(f"Paquete enviado desde switch {dpid} puerto {out_port}")
        else:
            self.logger.error(f"No se encontró out_port para el paquete {src_mac}->{dst_mac} en switch {dpid}")

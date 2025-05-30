# Imports para PostgreSQL y Ryu
import psycopg2
import sys
import collections
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
from ryu.lib.packet import igmp # Importar IGMP
from ryu.ofproto import inet 
from ryu.controller.handler import DEAD_DISPATCHER
import psycopg2.extras # Para obtener resultados de la DB como diccionarios
import requests

class Controller(app_manager.RyuApp):
    # Define las versiones de OpenFlow soportadas
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        """
        Constructor del controlador.
        Inicializa las estructuras de datos y carga la topología de la base de datos.
        """
        super(Controller, self).__init__(*args, **kwargs)
        # Diccionario para mapear dpid a {dirección MAC -> puerto de salida}
        self.mac_to_port = {}

        # Estructuras para la topología cargada de la base de datos
        # Mapea dpid (entero) a información del switch (ej. {'nombre': 's1', 'latitud': X, 'longitud': Y, 'dpid_str': '00...'})
        self.switches_by_dpid = {}
        # Mapea MAC de host (string) a {'dpid': dpid del switch, 'port': puerto del switch al host, 'ip': IP del host, 'name': nombre del host}
        self.host_to_switch_map = {}
        # Mapea IP de host (string) a MAC de host (string) - para ARP
        self.host_ip_to_mac = {}
        # Mapea MAC de host (string) a IP de host (string) - para ARP
        self.host_mac_to_ip = {}


        # Almacena objetos datapath para enviar reglas de flujo a cualquier switch
        self.datapaths = {}

        # Tabla ARP para el controlador (IP -> MAC)
        self.arp_table = {}

        

        # NUEVO: Estructuras de datos específicas para Multicast
        # {multicast_ip: {dpid_switch: [puertos_interesados]}}
        self.multicast_group_members = collections.defaultdict(lambda: collections.defaultdict(list))
        # {multicast_ip: dpid_switch_fuente}
        self.multicast_sources = {}
        # {multicast_ip: {dpid1, dpid2, ...}} - Para rastrear dónde se han instalado flujos multicast
        self.multicast_flow_installed_at = collections.defaultdict(set)

        self.db_lock = threading.Lock() # Para la sincronización de acceso a la DB
        # CORRECCIÓN: Cambiar a RLock para permitir el bloqueo re-entrante
        self.topology_lock = threading.RLock() # Para actualizaciones del grafo de topología

        self.logger.info("Aplicación de Controlador Ryu Inicializada")
        # Carga la topología y la configuración de enrutamiento desde la base de datos
        self._load_topology_from_db()

        # Iniciar hilos DESPUÉS de que los métodos estén definidos y la topología cargada
        self.update_server_thread = threading.Thread(target=self._update_server_info_periodically)
        self.update_server_thread.daemon = True # El hilo se cerrará cuando el programa principal termine
        self.update_server_thread.start()

        self.logger.info("Hilos de monitoreo iniciados.")


    def _get_db_connection(self):
        """
        Establece y retorna una conexión a la base de datos PostgreSQL.
        """
        # Asegúrate de que estos detalles coincidan con tu configuración de DB
        return psycopg2.connect(
            dbname="geant_network",
            user="geant_user",
            password="geant",
            host="192.168.18.151",
            port="5432"
        )

    def _load_topology_from_db(self):
        """
        Carga la topología de la red (switches, hosts, enlaces, puertos, ancho de banda)
        desde la base de datos PostgreSQL y construye la representación interna del grafo.
        También carga la configuración del algoritmo de enrutamiento.
        """
        conn = None
        cur = None
        try:
            conn = self._get_db_connection()
            cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor) # Usar DictCursor para obtener resultados como diccionarios
            self.logger.info("Conexión a la base de datos establecida.")

            # 1. Obtener switches
            # Seleccionar id_switch, nombre, latitud, longitud. El DPID se generará a partir de id_switch.
            cur.execute("SELECT id_switch, nombre, latitud, longitud FROM switches;")
            switch_list_raw = cur.fetchall()

            # Diccionario para mapear id_switch a nombre de ciudad y dpid_int
            id_switch_to_info = {}
            for s in switch_list_raw:
                # Generar el DPID string a partir del id_switch y convertirlo a entero
                dpid_str = "{:016x}".format(s['id_switch'])
                dpid_int = int(dpid_str, 16)
                self.switches_by_dpid[dpid_int] = {
                    'id_switch': s['id_switch'],
                    'nombre': s['nombre'],
                    'dpid_str': dpid_str, # Almacenar el string DPID generado
                    'latitud': s['latitud'],
                    'longitud': s['longitud']
                }
                id_switch_to_info[s['id_switch']] = {
                    'nombre': s['nombre'],
                    'dpid_int': dpid_int
                }
                self.logger.debug(f"Switch cargado: {s['nombre']} (ID: {s['id_switch']}, DPID: {dpid_int})")

            # 2. Obtener información de puertos para conexiones host-switch y switch-switch
            # La clave es (nodo_origen, nodo_destino) y el valor es (puerto_origen, puerto_destino)
            puertos_dict = {}
            cur.execute("SELECT nodo_origen, nodo_destino, puerto_origen, puerto_destino FROM puertos;")
            for p in cur.fetchall():
                nodo_origen = p['nodo_origen']
                nodo_destino = p['nodo_destino']
                puerto_origen_int = int(p['puerto_origen']) if p['puerto_origen'] is not None else None
                puerto_destino_int = int(p['puerto_destino']) if p['puerto_destino'] is not None else None
                puertos_dict[(nodo_origen, nodo_destino)] = (puerto_origen_int, puerto_destino_int)
            self.logger.info(f"Cargados {len(puertos_dict)} entradas de puertos.")


            # 3. Obtener hosts y mapearlos a switches/puertos
            # Usar 'ipv4' y 'switch_asociado' que son los nombres de columna correctos.
            cur.execute("SELECT nombre, switch_asociado, ipv4 AS ip, mac FROM hosts;")
            hosts_list = cur.fetchall()

            for host_entry in hosts_list:
                nombre_host = host_entry['nombre']
                id_switch_asociado = host_entry['switch_asociado']
                ip = host_entry['ip']
                mac = host_entry['mac']

                switch_info = id_switch_to_info.get(id_switch_asociado)
                if not switch_info:
                    self.logger.warning(f"Advertencia: Host {nombre_host} conectado a switch ID {id_switch_asociado} que no se encuentra en la topología de switches. Host omitido.")
                    continue

                ciudad_switch = switch_info['nombre']
                dpid_switch_asociado = switch_info['dpid_int']

                self.logger.info(f"Buscando puerto para el host {nombre_host} conectado al switch {ciudad_switch}")

                puerto_en_switch_a_host = None
                # La clave en puertos_dict es (nombre_switch, nombre_host)
                if (ciudad_switch, nombre_host) in puertos_dict:
                    puerto_en_switch_a_host = puertos_dict[(ciudad_switch, nombre_host)][0] # Puerto de salida del switch al host
                elif (nombre_host, ciudad_switch) in puertos_dict: # Si está en la dirección opuesta
                    puerto_en_switch_a_host = puertos_dict[(nombre_host, ciudad_switch)][1] # Puerto de entrada al switch desde el host

                if puerto_en_switch_a_host is None:
                    self.logger.warning(f"No se encontró puerto para el host {nombre_host} conectado al switch {ciudad_switch}. Usando puerto por defecto 1.")
                    puerto_en_switch_a_host = 1 # Valor por defecto si no se encuentra puerto

                self.host_to_switch_map[mac] = {
                    'dpid': dpid_switch_asociado,
                    'port': puerto_en_switch_a_host,
                    'ip': ip,
                    'name': nombre_host
                }
                self.host_mac_to_ip[mac] = ip
                self.host_ip_to_mac[ip] = mac
                self.mac_to_port.setdefault(dpid_switch_asociado, {})
                self.mac_to_port[dpid_switch_asociado][mac] = puerto_en_switch_a_host # También para el aprendizaje de MACs
                self.logger.info(f"Host cargado: {nombre_host} (MAC: {mac}, IP: {ip}) conectado a {ciudad_switch} (p{puerto_en_switch_a_host})")

            
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

    def update_switch_status_in_db(self, dpid, status):
        """
        Actualiza el estado de un switch en la base de datos.
        """
        query = "UPDATE switches SET status = %s WHERE id_switch = %s;"
        try:
            with self.db_lock:
                conn = self._get_db_connection()
                cur = conn.cursor()
                cur.execute(query, (status, dpid))
                conn.commit()
                cur.close()
                conn.close()
                self.logger.info(f"Estado del switch {dpid} actualizado a '{status}' en la base de datos.")
        except Exception as e:
            self.logger.error(f"Fallo al actualizar el estado del switch {dpid} a '{status}': {e}")

    



    def _update_server_info_periodically(self):
        """
        Hilo que consulta periódicamente la base de datos para obtener
        la información de los servidores VLC activos y sus IPs multicast.
        """
        while True:
            with self.db_lock:
                conn = None
                cur = None
                try:
                    conn = self._get_db_connection()
                    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
                    cur.execute("SELECT host_name, ip_destino, puerto FROM servidores_vlc_activos WHERE status = 'activo';")
                    active_servers = cur.fetchall()

                    new_multicast_sources = {}
                    for server in active_servers:
                        host_name = server['host_name']
                        multicast_ip = server['ip_destino']

                        server_dpid = None
                        # Buscar el DPID del switch al que está conectado el host_name
                        # Asumimos que `host_name` en `servidores_vlc_activos` es el mismo `nombre` de la tabla `hosts`

                        # Buscar el id_switch_conectado para el host_name
                        cur.execute("SELECT mac, switch_asociado FROM hosts WHERE nombre = %s;", (host_name,))
                        cur_host_info = cur.fetchone()

                        if cur_host_info:
                            switch_id_conectado = cur_host_info['switch_asociado']
                            # Asegurarse de que el switch_id_conectado existe en switches_by_dpid
                            for dpid_int, switch_data in self.switches_by_dpid.items():
                                if switch_data['id_switch'] == switch_id_conectado:
                                    server_dpid = dpid_int
                                    break
                            if not server_dpid:
                                self.logger.warning(f"Switch ID {switch_id_conectado} not found in topology for host {host_name}.")
                        else:
                            self.logger.warning(f"Host information for {host_name} not found in 'hosts' table.")


                        if server_dpid:
                            new_multicast_sources[multicast_ip] = server_dpid
                            self.logger.info(f"Server {host_name} ({multicast_ip}) associated with switch dpid {server_dpid}")
                        else:
                            self.logger.error(f"DPID of switch for server {host_name} not found. Cannot set as multicast source.")

                    # Actualizar las fuentes multicast del controlador
                    self.multicast_sources = new_multicast_sources
                    self.logger.debug(f"Fuentes multicast actualizadas: {self.multicast_sources}")

                except psycopg2.Error as e:
                    self.logger.error(f"DB error in _update_server_info_periodically: {e}")
                except Exception as e:
                    self.logger.error(f"Unexpected error in _update_server_info_periodically: {e}")
                finally:
                    if cur: cur.close()
                    if conn: conn.close()
            time.sleep(10) # Consultar cada 10 segundos


  

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
        # CORRECCIÓN: Cambiar 'datatap' a 'datapath'
        self.logger.info(f"Flujo eliminado del switch {datapath.id} con match: {match}")

    def _send_packet_out(self, datapath, buffer_id, in_port, actions, data):
        """
        Envía un paquete fuera del switch.
        """
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        out = parser.OFPPacketOut(datapath=datapath, buffer_id=buffer_id,
                                   in_port=in_port, actions=actions, data=data)
        datapath.send_msg(out)

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

    def _handle_igmp_packet(self, datapath, msg, dpid, in_port, igmp_pkt):
        """
        Maneja los paquetes IGMP, especialmente los informes de membresía (Join) y Leave.
        """
        self.logger.debug(f"DEBUG: Entrando a _handle_igmp_packet para switch {dpid} puerto {in_port}.")
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        # IGMPv3 Membership Report: Type 0x22 (34 decimal)
        if igmp_pkt.msgtype == 34:  # IGMPv3 Report
            self.logger.info(f"IGMPv3 Report recibido en switch {dpid}, puerto {in_port}")
            with self.topology_lock:
                for record in igmp_pkt.records:
                    multicast_group_addr = record.address
                    self.logger.info(f"[IGMPv3] tipo={record.type_} dirección={multicast_group_addr} fuentes={record.sources}")

                    # Manejar Join real solo si la lista de fuentes no está vacía (evita falsos Join con include vacío)
                    if record.type_ in [1, 3]:  # MODE_IS_INCLUDE o CHANGE_TO_EXCLUDE_MODE
                        if not record.sources:
                            self.logger.info(f"Ignorando Join ambiguo (Include vacío) para {multicast_group_addr}")
                            continue

                        self.logger.info(f"IGMPv3 Join válido para {multicast_group_addr} en switch {dpid}, puerto {in_port}")
                        if multicast_group_addr not in self.multicast_group_members:
                            self.multicast_group_members[multicast_group_addr] = {}
                        if dpid not in self.multicast_group_members[multicast_group_addr]:
                            self.multicast_group_members[multicast_group_addr][dpid] = []
                        if in_port not in self.multicast_group_members[multicast_group_addr][dpid]:
                            self.multicast_group_members[multicast_group_addr][dpid].append(in_port)
                            self.logger.info(f"Puerto {in_port} agregado al grupo {multicast_group_addr} en switch {dpid}")
                            self._install_multicast_flows(multicast_group_addr)

                    elif record.type_ in [2, 4]:  # CHANGE_TO_INCLUDE_MODE o BLOCK_OLD_SOURCES
                        self.logger.info(f"IGMPv3 Leave para {multicast_group_addr} en switch {dpid}, puerto {in_port}")
                        if multicast_group_addr in self.multicast_group_members and \
                        dpid in self.multicast_group_members[multicast_group_addr] and \
                        in_port in self.multicast_group_members[multicast_group_addr][dpid]:
                            self.multicast_group_members[multicast_group_addr][dpid].remove(in_port)
                            if not self.multicast_group_members[multicast_group_addr][dpid]:
                                del self.multicast_group_members[multicast_group_addr][dpid]
                            if not self.multicast_group_members[multicast_group_addr]:
                                del self.multicast_group_members[multicast_group_addr]
                            self.logger.info(f"Puerto {in_port} eliminado del grupo {multicast_group_addr} en switch {dpid}")
                            self._remove_multicast_flows(multicast_group_addr)

        # IGMPv2 Membership Report: Type 0x16 (22 decimal)
        elif igmp_pkt.msgtype == 22: # igmp.IGMP_V2_MEMBERSHIP_REPORT
            multicast_group_addr = igmp_pkt.address
            self.logger.info(f"IGMPv2 Join recibido para {multicast_group_addr} en switch {dpid}, puerto {in_port}")

            with self.topology_lock: # topology_lock ya está adquirido
                # Añadir/actualizar miembro para este grupo multicast
                if in_port not in self.multicast_group_members[multicast_group_addr][dpid]:
                    self.multicast_group_members[multicast_group_addr][dpid].append(in_port)
                    self.logger.info(f"Puerto {in_port} agregado al grupo multicast {multicast_group_addr} en el switch {dpid}")
                    self.logger.debug(f"Miembros actuales: {self.multicast_group_members}")

                    # Disparar el cálculo del árbol multicast y la instalación de flujos
                    self.logger.debug(f"DEBUG: Llamando a _install_multicast_flows desde IGMP Join (v2) para {multicast_group_addr}.")
                    # No es necesario adquirir el lock aquí de nuevo, ya que _handle_igmp_packet ya lo tiene.
                    self._install_multicast_flows(multicast_group_addr)
                    self.logger.debug(f"DEBUG: _install_multicast_flows finalizado para IGMP Join (v2).")

        # IGMPv2 Leave Group: Type 0x17 (23 decimal)
        elif igmp_pkt.msgtype == 23: # igmp.IGMP_V2_LEAVE_GROUP
            multicast_group_addr = igmp_pkt.address
            self.logger.info(f"IGMPv2 Leave Group para {multicast_group_addr} en {dpid} puerto {in_port}")
            with self.topology_lock: # topology_lock ya está adquirido
                if dpid in self.multicast_group_members[multicast_group_addr] and in_port in self.multicast_group_members[multicast_group_addr][dpid]:
                    self.multicast_group_members[multicast_group_addr][dpid].remove(in_port)
                    # Si no quedan puertos interesados en este switch para este grupo, eliminar la entrada del switch
                    if not self.multicast_group_members[multicast_group_addr][dpid]:
                        del self.multicast_group_members[multicast_group_addr][dpid]
                    # Si no quedan switches interesados en este grupo, eliminar la entrada del grupo
                    if not self.multicast_group_members[multicast_group_addr]:
                        del self.multicast_group_members[multicast_group_addr]

                    self.logger.info(f"Puerto {in_port} eliminado del grupo multicast {multicast_group_addr} en el switch {dpid}")
                    self.logger.debug(f"Miembros actuales después de Leave: {self.multicast_group_members}")

                    # Re-evaluar y potencialmente eliminar flujos multicast
                    self.logger.debug(f"DEBUG: Llamando a _remove_multicast_flows desde IGMP Leave (v2) para {multicast_group_addr}.")
                    # No es necesario adquirir el lock aquí de nuevo, ya que _handle_igmp_packet ya lo tiene.
                    self._remove_multicast_flows(multicast_group_addr)
                    self.logger.debug(f"DEBUG: _remove_multicast_flows finalizado para IGMP Leave (v2).")
        else:
            self.logger.warning(f"Tipo de mensaje IGMP no soportado o desconocido: {igmp_pkt.msgtype}")
        self.logger.debug(f"DEBUG: Saliendo de _handle_igmp_packet para switch {dpid} puerto {in_port}.")
    
    def _handle_multicast_ip_traffic(self, datapath, msg, dpid, in_port, multicast_ip):
            """
            Maneja el tráfico IP multicast que llega al controlador (Packet_In).
            Esto suele ocurrir si no hay un flujo instalado o si ha expirado.
            Ahora, solo se procesa si hay clientes suscritos al grupo.
            """
            self.logger.debug(f"DEBUG: Entrando a _handle_multicast_ip_traffic para {multicast_ip} en switch {dpid} puerto {in_port}.")
            # Verificar si hay algún miembro para este grupo multicast en cualquier switch
            if not self.multicast_group_members.get(multicast_ip):
                self.logger.debug(f"Tráfico IP Multicast {multicast_ip} de {dpid} en {in_port} llegó al controlador, pero no hay clientes suscritos. Descartando paquete.")
                self.logger.debug(f"DEBUG: Saliendo de _handle_multicast_ip_traffic (sin suscriptores).")
                return # Descartar el paquete si no hay suscriptores

            self.logger.warning(f"Tráfico IP Multicast {multicast_ip} de {dpid} en {in_port} llegó al controlador. Re-evaluando e instalando flujos.")
            self.logger.debug(f"DEBUG: Llamando a _install_multicast_flows desde _handle_multicast_ip_traffic para {multicast_ip}.")
            # No es necesario adquirir el lock aquí de nuevo, ya que _handle_multicast_ip_traffic no tiene el lock
            # y _install_multicast_flows lo adquirirá internamente.
            self._install_multicast_flows(multicast_ip) # Re-disparar la instalación de flujos
            self.logger.debug(f"DEBUG: _install_multicast_flows finalizado desde _handle_multicast_ip_traffic.")

            # Reenviar el paquete actual usando las reglas recién instaladas o un fallback
            # Si los flujos se acaban de instalar, el siguiente paquete debería ser manejado por el switch.
            # Para este paquete específico, podemos intentar reenviarlo si ya conocemos los puertos de salida.
            data = None
            if msg.buffer_id == datapath.ofproto.OFP_NO_BUFFER:
                data = msg.data

            # Intentar reenviar el paquete si hay miembros conocidos en este switch
            if dpid in self.multicast_group_members[multicast_ip]:
                out_ports = self.multicast_group_members[multicast_ip][dpid]
                if out_ports:
                    actions = [datapath.ofproto_parser.OFPActionOutput(p) for p in out_ports]
                    self._send_packet_out(datapath, msg.buffer_id, in_port, actions, data)
                    self.logger.debug(f"Fallback: Paquete multicast reenviado desde {dpid} a {out_ports}")
                    self.logger.debug(f"DEBUG: Saliendo de _handle_multicast_ip_traffic (reenviado fallback).")
                    return
            self.logger.warning(f"Paquete multicast {multicast_ip} en {dpid} (in_port {in_port}) no pudo ser reenviado por el controlador fallback (no hay miembros en este switch o puertos de salida).")
            self.logger.debug(f"DEBUG: Saliendo de _handle_multicast_ip_traffic (no reenviado fallback).")


    def _install_multicast_flows(self, multicast_group_addr):
        """
        Calcula e instala las reglas de flujo para un árbol multicast.
        """
        self.logger.debug(f"DEBUG: Entrando a _install_multicast_flows para grupo {multicast_group_addr}.")
        source_dpid = self.multicast_sources.get(multicast_group_addr)
        if not source_dpid:
            self.logger.warning(f"No se encontró la fuente para el grupo multicast {multicast_group_addr}. No se pueden instalar flujos.")
            self.logger.debug(f"DEBUG: Saliendo de _install_multicast_flows (sin fuente).")
            return

        member_switches = self.multicast_group_members.get(multicast_group_addr, {})
        if not member_switches:
            self.logger.warning(f"No hay miembros para el grupo multicast {multicast_group_addr}. No hay flujos para instalar.")
            self.logger.debug(f"DEBUG: Saliendo de _install_multicast_flows (sin miembros).")
            return

        self.logger.info(f"Instalando flujos multicast para {multicast_group_addr} desde la fuente {source_dpid}")

        self.logger.debug(f"DEBUG: Limpiando flujos existentes para {multicast_group_addr}.")
        dpids_to_clear = list(self.multicast_flow_installed_at[multicast_group_addr])
        for dpid_to_clear in dpids_to_clear:
            if dpid_to_clear in self.datapaths:
                datapath = self.datapaths[dpid_to_clear]
                local_parser = datapath.ofproto_parser
                match = local_parser.OFPMatch(eth_type=ether_types.ETH_TYPE_IP,
                                            ipv4_dst=multicast_group_addr,
                                            ip_proto=inet.IPPROTO_UDP)
                self.remove_flow_by_match(datapath, match)
                self.logger.info(f"Flujo multicast existente en dpid {dpid_to_clear} limpiado para {multicast_group_addr}")
        self.multicast_flow_installed_at[multicast_group_addr].clear()

        switch_output_ports = collections.defaultdict(set)

        if source_dpid in member_switches:
            for port in member_switches[source_dpid]:
                switch_output_ports[source_dpid].add(port)

        self.logger.debug(f"DEBUG: Solicitando árbol multicast remoto para {multicast_group_addr} desde fuente {source_dpid} a miembros {list(member_switches.keys())}.")
        try:
            url = "http://192.168.18.151:5000/dijkstra/calculate_multicast_tree"
            payload = {
                "source_dpid": source_dpid,
                "member_dpids": list(member_switches.keys())
            }
            response = requests.post(url, json=payload, timeout=3)

            if response.status_code == 200:
                tree = response.json().get("tree", {})
            else:
                self.logger.error(f"Error al obtener árbol multicast: {response.status_code} {response.text}")
                return
        except requests.RequestException as e:
            self.logger.error(f"Fallo en la solicitud al servidor de rutas multicast: {e}")
            return

        self.logger.debug(f"DEBUG: Árbol recibido: {tree}")
        for dpid_str, out_ports in tree.items():
            dpid = int(dpid_str)
            if dpid in self.datapaths:
                datapath = self.datapaths[dpid]
                local_parser = datapath.ofproto_parser
                valid_ports = [int(p) for p in out_ports if p is not None and isinstance(p, int) and p > 0]

                if not valid_ports:
                    self.logger.warning(f"Saltando instalación de flujo en switch {dpid} por puertos inválidos: {out_ports}")
                    continue

                actions = [local_parser.OFPActionOutput(p) for p in valid_ports]
                match = local_parser.OFPMatch(
                    eth_type=ether_types.ETH_TYPE_IP,
                    ipv4_dst=multicast_group_addr,
                    ip_proto=inet.IPPROTO_UDP
                )
                self.add_flow(datapath, 200, match, actions, idle_timeout=300, hard_timeout=600)
                self.multicast_flow_installed_at[multicast_group_addr].add(dpid)
                self.logger.info(f"[MULTICAST] Flujo instalado en {dpid} para {multicast_group_addr} → puertos válidos: {valid_ports}, originales: {out_ports}")
            else:
                self.logger.warning(f"Switch {dpid} no encontrado en datapaths. No se puede instalar flujo multicast.")


    
        


    def _remove_multicast_flows(self, multicast_group_addr):
        """
        Re-evalúa y elimina flujos multicast si no quedan miembros para un grupo.
        """
        self.logger.debug(f"DEBUG: Entrando a _remove_multicast_flows para grupo {multicast_group_addr}.")
        self.logger.debug(f"DEBUG: Intentando adquirir topology_lock en _remove_multicast_flows.")
        try:
            with self.topology_lock:
                self.logger.debug(f"DEBUG: topology_lock adquirido en _remove_multicast_flows.")
                # Si no quedan miembros para este grupo multicast, eliminar todos los flujos relacionados
                if not self.multicast_group_members.get(multicast_group_addr):
                    self.logger.info(f"No quedan miembros para el grupo multicast {multicast_group_addr}. Eliminando todos los flujos.")
                    self.logger.debug(f"DEBUG: No quedan miembros para {multicast_group_addr}. Procediendo a eliminar flujos.")
                    dpids_to_remove_from = list(self.multicast_flow_installed_at.get(multicast_group_addr, set())) # Usar .get con set() para seguridad
                    self.logger.debug(f"DEBUG: DPIDs con flujos multicast para eliminar: {dpids_to_remove_from}")
                    
                    if not dpids_to_remove_from:
                        self.logger.info(f"No hay switches registrados con flujos para eliminar para {multicast_group_addr}.")

                    for dpid in dpids_to_remove_from:
                        self.logger.debug(f"DEBUG: Procesando eliminación de flujo en DPID: {dpid}")
                        if dpid in self.datapaths:
                            datapath = self.datapaths[dpid]
                            local_parser = datapath.ofproto_parser # Usar el parser del datapath específico
                            # MODIFICACIÓN: Añadir ip_proto=inet.IPPROTO_UDP para un match más específico
                            match = local_parser.OFPMatch(eth_type=ether_types.ETH_TYPE_IP,
                                                                     ipv4_dst=multicast_group_addr,
                                                                     ip_proto=inet.IPPROTO_UDP) # Asegura que solo el tráfico UDP coincida
                            self.logger.debug(f"DEBUG: Llamando a remove_flow_by_match para {dpid} con match {match}")
                            self.remove_flow_by_match(datapath, match)
                            self.logger.info(f"Flujo multicast eliminado para {multicast_group_addr} en switch {dpid}.")
                        else:
                            self.logger.warning(f"ADVERTENCIA: Datapath {dpid} no encontrado en self.datapaths al intentar eliminar flujo para {multicast_group_addr}.")
                    self.multicast_flow_installed_at[multicast_group_addr].clear() # Limpiar el registro
                    # Si no quedan entradas para este grupo, eliminarlo completamente del diccionario principal
                    if not self.multicast_flow_installed_at[multicast_group_addr]:
                        del self.multicast_flow_installed_at[multicast_group_addr]
                        self.logger.debug(f"DEBUG: Grupo {multicast_group_addr} completamente eliminado de multicast_flow_installed_at.")
                else:
                    # Si todavía hay miembros, recalcular y reinstalar los flujos
                    self.logger.info(f"El grupo multicast {multicast_group_addr} todavía tiene miembros. Re-evaluando y reinstalando flujos.")
                    self.logger.debug(f"DEBUG: Todavía hay miembros para {multicast_group_addr}. Reinstalando flujos.")
                    self._install_multicast_flows(multicast_group_addr)
            self.logger.debug(f"DEBUG: topology_lock liberado en _remove_multicast_flows.")
        except Exception as e:
            self.logger.error(f"ERROR: Excepción en _remove_multicast_flows para {multicast_group_addr}: {e}", exc_info=True)
            # Asegurarse de liberar el lock si se adquirió antes de la excepción (aunque 'with' debería manejarlo)
            # No hay necesidad de liberar explícitamente el lock en un 'finally' porque el 'with' statement lo hace.
        self.logger.debug(f"DEBUG: Saliendo de _remove_multicast_flows para grupo {multicast_group_addr}.")

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
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
                self.update_switch_status_in_db(datapath.id, 'conectado')

                # Instala regla table-miss
                ofproto = datapath.ofproto
                parser = datapath.ofproto_parser
                match = parser.OFPMatch()
                actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                                ofproto.OFPCML_NO_BUFFER)]
                self.add_flow(datapath, 0, match, actions)

        elif ev.state == DEAD_DISPATCHER:
            if datapath.id in self.datapaths:
                self.logger.info("Switch desconectado: %016x", datapath.id)
                del self.datapaths[datapath.id]
                self.update_switch_status_in_db(datapath.id, 'desconectado')
        else:
            self.logger.warning(f"Evento de desconexión para DPID {datapath.id} no encontrado en datapaths.")

    
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
        dpid = datapath.id
        in_port = msg.match['in_port'] # Puerto de entrada del paquete en el switch

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        if not eth:
            # Si no hay encabezado Ethernet, ignora el paquete
            return

        # LOG DE DEPURACIÓN: Añadido para ver todos los PacketIn que llegan al controlador
        self.logger.debug(f"DEBUG: PacketIn recibido en switch={dpid} in_port={in_port} eth_type={eth.ethertype:04x}")

        # LOG DE DEPURACIÓN: Imprimir todos los protocolos en el paquete
        protocol_names = [p.protocol_name for p in pkt.protocols if hasattr(p, 'protocol_name')]
        self.logger.debug(f"Packet protocols: {protocol_names}")

        # Ignorar paquetes LLDP e IPv6
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return
        if eth.ethertype == ether_types.ETH_TYPE_IPV6:
            self.logger.debug(f"Ignorando paquete IPv6 en el switch {dpid}")
            return

        dst_mac = eth.dst # MAC de destino del paquete
        src_mac = eth.src # MAC de origen del paquete
        self.mac_to_port.setdefault(dpid, {}) # Asegura que el dpid exista en mac_to_port

        self.logger.debug(f"Paquete entrante: switch={dpid} src={src_mac} dst={dst_mac} in_port={in_port} ethertype={eth.ethertype:04x}")

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
                self.logger.info(f"DEBUG: Paquete ARP en switch {dpid}: opcode={arp_pkt.opcode} src_ip={arp_pkt.src_ip} dst_ip={arp_pkt.dst_ip}")
                if arp_pkt.opcode == arp.ARP_REQUEST:
                    target_ip = arp_pkt.dst_ip
                    # Busca la MAC del target_ip en los hosts conocidos
                    for mac, info in self.host_to_switch_map.items():
                        if info['ip'] == target_ip:
                            # Si se encuentra, envía una respuesta ARP proxy
                            self._send_arp_reply(datapath, src_mac, arp_pkt.src_ip, mac, target_ip, in_port)
                            return # Termina el procesamiento del paquete ARP
                # Para ARP reply, se deja fluir normalmente (se maneja como unicast si la MAC es conocida)

        # Manejo de IGMP (Multicast Group Management Protocol)
        for protocol in pkt.protocols:
            if isinstance(protocol, igmp.igmp):
                self.logger.info(f"Paquete IGMP recibido en switch {dpid}, puerto {in_port}: {protocol}")
                self._handle_igmp_packet(datapath, msg, dpid, in_port, protocol)
                return # IGMP manejado, no procesar más

        # Si el destino es multicast/broadcast (incluyendo solicitudes ARP no respondidas), inunda el paquete
        # O si es tráfico IP Multicast (224.0.0.0/4 o 239.0.0.0/8)
        if is_dst_multicast:
            _ipv4 = pkt.get_protocol(ipv4.ipv4)
            if _ipv4 and (_ipv4.dst.startswith('224.') or _ipv4.dst.startswith('239.')):
                self.logger.debug(f"DEBUG: Tráfico IP Multicast detectado: {_ipv4.dst} de {src_mac} a {dst_mac} en switch {dpid} puerto {in_port}. Protocolo IP: {_ipv4.proto}")
                self._handle_multicast_ip_traffic(datapath, msg, dpid, in_port, _ipv4.dst)
                return # Multicast IP manejado, no procesar como unicast
            else: # Es un broadcast o multicast no IP
                out_port = ofproto.OFPP_FLOOD
                self.logger.info(f"Inundando paquete broadcast/multicast no IP en switch={dpid} dst={dst_mac}")
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
            # LOG DE DEPURACIÓN: Para tráfico IP unicast
            _ipv4 = pkt.get_protocol(ipv4.ipv4)
            if _ipv4:
                self.logger.info(f"DEBUG: Paquete IP Unicast de {_ipv4.src} a {_ipv4.dst} en switch {dpid}. Protocolo IP: {_ipv4.proto}")
            else:
                self.logger.info(f"DEBUG: Paquete Unicast no IP (o IP sin cabecera) src={src_mac} dst={dst_mac} en switch {dpid}")


            # Primero, verifica si el destino está directamente conectado a este switch (MAC aprendida localmente)
            if dst_mac in self.mac_to_port[dpid]:
                out_port = self.mac_to_port[dpid][dst_mac]
                self.logger.info(f"Destino conocido en switch={dpid} dst={dst_mac} port={out_port}. Instalando flujo directo.")
                match = parser.OFPMatch(
                    eth_type=ether_types.ETH_TYPE_IP,
                    eth_src=src_mac,
                    eth_dst=dst_mac
                )

                actions = [parser.OFPActionOutput(out_port)]
                # Añade la regla de flujo
                # MODIFICACIÓN: idle_timeout y hard_timeout a 0 para flujos permanentes
                self.add_flow(datapath, 100, match, actions, msg.buffer_id, idle_timeout=0, hard_timeout=0)

                # Envía el paquete después de instalar el flujo
                data = None
                if msg.buffer_id == ofproto.OFP_NO_BUFFER:
                    data = msg.data
                out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                                           in_port=in_port, actions=actions, data=data)
                datapath.send_msg(out)
                self.logger.debug(f"Paquete enviado desde switch {dpid} puerto {out_port} (ruta directa).")
                return # Importante: salir después de manejar la ruta directa

            elif dst_mac in self.host_to_switch_map:
                dst_host_info = self.host_to_switch_map[dst_mac]
                dst_switch_dpid = dst_host_info['dpid']
                dst_switch_port_to_host = dst_host_info['port']

                self.logger.info(f"Host de destino {dst_mac} en switch {dst_switch_dpid} puerto {dst_switch_port_to_host}")

                try:
                    url = 'http://192.168.18.151:5000/dijkstra/calculate_path'
                    payload = {"src_mac": src_mac, "dst_mac": dst_mac}
                    response = requests.post(url, json=payload, timeout=3)
                    if response.status_code == 200:
                        data = response.json()
                        path = data.get("path", [])
                    else:
                        self.logger.error(f"Fallo al obtener ruta: {response.status_code} {response.text}")
                        return
                except requests.RequestException as e:
                    self.logger.error(f"Error en la solicitud HTTP al servidor de rutas: {e}")
                    return

                self.logger.info("Detalles de la ruta calculada:")
                for idx, salto in enumerate(path):
                    self.logger.info(f"  Salto {idx}: Switch={salto.get('dpid')}, out_port={salto.get('out_port')}, in_port={salto.get('in_port')}")

                if not path:
                    self.logger.warning(f"No hay ruta desde {dpid} a {dst_switch_dpid} para {src_mac} -> {dst_mac}, descartando paquete")
                    return

                # Instalar flujos ida: src → dst
                self.logger.debug(f"Ruta encontrada: {path}")
                for i, salto in enumerate(path):
                    cur_dpid = salto.get("dpid")
                    out_port = salto.get("out_port")  # ✅ Usar directamente el valor del salto

                    cur_dp = self.datapaths.get(cur_dpid)
                    if not cur_dp:
                        self.logger.error(f"Datapath faltante para el switch {cur_dpid}, omitiendo instalación de flujo")
                        continue

                    if not isinstance(out_port, int) or out_port <= 0:
                        self.logger.error(f"Puerto de salida inválido ({out_port}) en la ruta directa para {cur_dpid}")
                        continue

                    match = parser.OFPMatch(
                        eth_type=ether_types.ETH_TYPE_IP,
                        eth_src=src_mac,
                        eth_dst=dst_mac
                    )
                    actions = [parser.OFPActionOutput(out_port)]

                    buffer_id_use = msg.buffer_id if cur_dpid == dpid and msg.buffer_id != ofproto.OFP_NO_BUFFER else ofproto.OFP_NO_BUFFER

                    self.add_flow(cur_dp, 100, match, actions, buffer_id_use, idle_timeout=0, hard_timeout=0)
                    self.logger.info(f"Flujo instalado en switch {cur_dpid} para {src_mac}->{dst_mac} a través del puerto {out_port}")

                # === Solicitar ruta inversa: dst → src ===
                try:
                    reverse_payload = {"src_mac": dst_mac, "dst_mac": src_mac}
                    reverse_response = requests.post(url, json=reverse_payload, timeout=3)
                    if reverse_response.status_code == 200:
                        reverse_data = reverse_response.json()
                        reverse_path = reverse_data.get("path", [])
                    else:
                        self.logger.error(f"Fallo al obtener ruta inversa: {reverse_response.status_code} {reverse_response.text}")
                        return
                except requests.RequestException as e:
                    self.logger.error(f"Error en la solicitud HTTP al servidor de rutas (inverso): {e}")
                    return

                self.logger.debug(f"Ruta inversa encontrada: {reverse_path}")
                self.logger.info("Detalles de la ruta inversa calculada:")
                for idx, salto in enumerate(reverse_path):
                    self.logger.info(f"  Salto {idx}: Switch={salto.get('dpid')}, out_port={salto.get('out_port')}, in_port={salto.get('in_port')}")
                # En la ruta inversa
                for i, salto in enumerate(reverse_path):
                    cur_dpid = salto.get("dpid")
                    out_port = salto.get("out_port")

                    cur_dp = self.datapaths.get(cur_dpid)
                    if not cur_dp:
                        self.logger.error(f"Datapath faltante para el switch {cur_dpid} en la ruta inversa, omitiendo")
                        continue

                    if not isinstance(out_port, int) or out_port <= 0:
                        self.logger.error(f"Puerto de salida inválido ({out_port}) en ruta inversa para {cur_dpid}")
                        continue

                    reverse_match = parser.OFPMatch(
                        eth_type=ether_types.ETH_TYPE_IP,
                        eth_src=dst_mac,
                        eth_dst=src_mac
                    )
                    reverse_actions = [parser.OFPActionOutput(out_port)]

                    self.add_flow(cur_dp, 100, reverse_match, reverse_actions, idle_timeout=0, hard_timeout=0)
                    self.logger.info(f"[RETORNO] Flujo instalado en switch {cur_dpid} para {dst_mac}->{src_mac} por puerto {out_port}")


                # Reenviar el primer paquete
                initial_out_port = path[0].get("out_port") if len(path) > 1 else dst_switch_port_to_host
                if isinstance(initial_out_port, int) and initial_out_port > 0:
                    data = None
                    if msg.buffer_id == ofproto.OFP_NO_BUFFER:
                        data = msg.data

                    out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                                            in_port=in_port, actions=[parser.OFPActionOutput(initial_out_port)],
                                            data=data)
                    datapath.send_msg(out)
                    self.logger.debug(f"Paquete inicial enviado desde switch {dpid} puerto {initial_out_port}")
                else:
                    self.logger.error(f"Fallo al enviar paquete inicial: puerto inválido ({initial_out_port})")
                return


        # Si el paquete llega aquí, significa que no fue manejado por las lógicas anteriores (ARP, Unicast, Multicast).
        # En este punto, simplemente se descarta o se permite que Ryu lo maneje por defecto (que a menudo es descartar).
        self.logger.debug(f"Paquete no manejado: src={src_mac}, dst={dst_mac}, eth_type={eth.ethertype} en dpid={dpid}, in_port={in_port}. Descartando.")
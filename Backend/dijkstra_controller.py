from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, CONFIG_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet, ipv4
from ryu.lib import hub
import networkx as nx
import psycopg2
import json
from datetime import datetime
import time

class SDNDijkstraRouter(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.datapaths = {}
        self.db_rules = {}
        self.installed_flows = {}
        self.running = True
        self.monitor_interval = kwargs.get('monitor_interval', 10)
        self.monitor_thread = hub.spawn(self.monitorizar_reglas)

    def obtener_conexion_bd(self):
        return psycopg2.connect(
            dbname="geant_network",
            user="geant_user",
            password="geant",
            host="192.168.18.151",
            port="5432"
        )

    def construir_grafo(self):
        G = nx.Graph()
        conn = self.obtener_conexion_bd()
        cur = conn.cursor()
        cur.execute("""
            SELECT s1.nombre, s2.nombre, e.ancho_banda
            FROM enlaces e
            JOIN switches s1 ON e.id_origen = s1.id_switch
            JOIN switches s2 ON e.id_destino = s2.id_switch
        """)
        for row in cur.fetchall():
            G.add_edge(row[0], row[1], weight=1 / row[2])
        cur.close()
        conn.close()
        return G

    def obtener_puerto(self, origen, destino):
        conn = self.obtener_conexion_bd()
        cur = conn.cursor()
        cur.execute("""
            SELECT puerto_salida FROM puertos
            WHERE nodo_origen = %s AND nodo_destino = %s
        """, (origen, destino))
        res = cur.fetchone()
        cur.close()
        conn.close()
        return res[0] if res else None

    def obtener_dpid(self, nombre):
        conn = self.obtener_conexion_bd()
        cur = conn.cursor()
        cur.execute("SELECT id_switch FROM switches WHERE nombre = %s", (nombre,))
        dpid = cur.fetchone()
        cur.close()
        conn.close()
        return dpid[0] if dpid else None

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        self.logger.info(f"Switch conectado: DPID = {ev.msg.datapath.id}")
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        # Regla por defecto: enviar paquetes desconocidos al controlador
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(datapath=datapath, priority=0, match=match, instructions=inst)
        datapath.send_msg(mod)

        dpid = datapath.id
        self.datapaths[dpid] = datapath

        # Cargar reglas desde la base de datos
        reglas_db = self.obtener_reglas_desde_db().get(dpid, {})
        self.db_rules.setdefault(dpid, {}).update(reglas_db)
        if not reglas_db:
            self.logger.warning(f"No rules found for switch {dpid}.")
        else:
            self.logger.info(f"Rules for {dpid} loaded ({len(reglas_db)} rules).")
        self._install_db_rules(datapath, reglas_db)

        match_arp = parser.OFPMatch(eth_type=0x0806)
        actions_arp = [parser.OFPActionOutput(ofproto.OFPP_FLOOD)]
        inst_arp = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions_arp)]
        mod_arp = parser.OFPFlowMod(
            datapath=datapath,
            priority=1000,
            match=match_arp,
            instructions=inst_arp
        )
        datapath.send_msg(mod_arp)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        dpid = datapath.id
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        in_port = msg.match['in_port']

        #self.logger.info(f"[PACKET_IN] Paquete recibido por el switch DPID {dpid} en el puerto {in_port}")


        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocol(ethernet.ethernet)
        ip = pkt.get_protocol(ipv4.ipv4)
        if not ip:
            return

        dst_ip = ip.dst
        src_ip = ip.src

        conn = self.obtener_conexion_bd()
        cur = conn.cursor()
        cur.execute("SELECT nombre FROM switches WHERE id_switch = %s", (dpid,))
        sw_nombre = cur.fetchone()[0]

        cur.execute("""
            SELECT s.nombre FROM hosts h
            JOIN switches s ON h.switch_asociado = s.id_switch
            WHERE h.ipv4 = %s
        """, (dst_ip,))
        destino_sw = cur.fetchone()

        cur.execute("""
            SELECT s.nombre FROM hosts h
            JOIN switches s ON h.switch_asociado = s.id_switch
            WHERE h.ipv4 = %s
        """, (src_ip,))
        origen_sw = cur.fetchone()
        cur.close()
        conn.close()

        if not destino_sw or not origen_sw:
            self.logger.warning(f"[ERROR] No se pudo resolver el switch de origen ({src_ip}) o destino ({dst_ip})")
            return

        self.logger.info(f"[DEBUG] Nombres usados para Dijkstra: origen = {sw_nombre}, destino = {destino_sw[0]}")
        destino_sw = destino_sw[0]
        origen_sw = origen_sw[0]

        if origen_sw == destino_sw:

            # Ambos hosts están en el mismo switch
            self.logger.info(f"{origen_sw} y {destino_sw} están en el mismo switch {sw_nombre}. Instalando reenvío local.")

            # Obtener el puerto hacia el host destino desde la tabla 'puertos'
            puerto_salida = self.obtener_puerto_dinamico(sw_nombre, dst_ip)


            if puerto_salida is None:
                self.logger.warning(f"No se encontró puerto de salida local para {dst_ip} en {sw_nombre}")
                return

            eth_type = eth.ethertype
            if eth_type == 0x0800:  # IPv4
                match = parser.OFPMatch(eth_type=eth_type, ipv4_dst=dst_ip)
            elif eth_type == 0x0806:  # ARP
                match = parser.OFPMatch(eth_type=eth_type)
            else:
                self.logger.warning(f"[DROP] Paquete con eth_type desconocido: {eth_type}")
                return

            actions = [parser.OFPActionOutput(int(puerto_salida))]
            inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
            mod = parser.OFPFlowMod(
                datapath=datapath,
                priority=100,
                match=match,
                instructions=inst
            )
            datapath.send_msg(mod)
            #self.guardar_regla_en_postgresql(dpid_actual, 100, match, actions)

            # reenviar el primer paquete
            out = parser.OFPPacketOut(
                datapath=datapath,
                buffer_id=msg.buffer_id,
                in_port=in_port,
                actions=actions,
                data=msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
            )
            datapath.send_msg(out)
            #self.guardar_regla_en_postgresql(dpid_actual, 100, match, actions)
            self.logger.info(f"[REPLY] Paquete reenviado localmente desde {src_ip} hacia {dst_ip} por el puerto {puerto_salida}")
            return
    
        grafo = self.construir_grafo()

        try:
            self.logger.info(f"{src_ip} ({origen_sw}) quiere comunicarse con {dst_ip} ({destino_sw}). Calculando ruta con Dijkstra...")
            ruta_ida = nx.dijkstra_path(grafo, sw_nombre, destino_sw, weight='weight')
            if len(ruta_ida) < 2:
                self.logger.info(f"[ENTREGA DIRECTA] El switch {sw_nombre} es el destino final para {dst_ip}. Instalando regla hacia el host.")
                
                puerto_salida = self.obtener_puerto_dinamico(sw_nombre, dst_ip)
                if puerto_salida is None:
                    self.logger.warning(f"No se encontró puerto de salida para {dst_ip} en {sw_nombre}")
                    return

                if eth.ethertype == 0x0800:
                    match = parser.OFPMatch(eth_type=0x0800, ipv4_dst=dst_ip)
                elif eth.ethertype == 0x0806:
                    match = parser.OFPMatch(eth_type=0x0806)
                else:
                    self.logger.warning(f"[DROP] Paquete con eth_type desconocido: {eth.ethertype}")
                    return

                actions = [parser.OFPActionOutput(int(puerto_salida))]
                inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
                mod = parser.OFPFlowMod(
                    datapath=datapath,
                    priority=100,
                    match=match,
                    instructions=inst
                )
                datapath.send_msg(mod)

                out = parser.OFPPacketOut(
                    datapath=datapath,
                    buffer_id=msg.buffer_id,
                    in_port=in_port,
                    actions=actions,
                    data=msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
                )
                datapath.send_msg(out)
                self.logger.info(f"[REPLY] Paquete entregado directamente en {sw_nombre} hacia {dst_ip} por el puerto {puerto_salida}")
                return
            ruta_retorno = list(reversed(ruta_ida))
            self.logger.info(f"Ruta calculada (IDA): {' → '.join(ruta_ida)}")
            self.logger.info(f"Ruta calculada (RETORNO): {' → '.join(ruta_retorno)}")
        except Exception as e:
            self.logger.error(f"Error calculando ruta Dijkstra entre {sw_nombre} y {destino_sw}: {e}")
            return


        for ruta, ip_objetivo, direccion in [(ruta_ida, dst_ip, "IDA"), (ruta_retorno, src_ip, "RETORNO")]:
            for i in range(len(ruta) - 1):
                actual = ruta[i]
                siguiente = ruta[i + 1]
                dpid_actual = self.obtener_dpid(actual)
                datapath_actual = self.datapaths.get(dpid_actual)

                puerto_salida = self.obtener_puerto_dinamico(actual, siguiente)
                if not datapath_actual or puerto_salida is None:
                    continue

                if eth.ethertype == 0x0800:
                    match = parser.OFPMatch(eth_type=0x0800, ipv4_dst=ip_objetivo)
                elif eth.ethertype == 0x0806:
                    match = parser.OFPMatch(eth_type=0x0806)
                else:
                    self.logger.warning(f"[DROP] Paquete desconocido con eth_type {eth.ethertype}")
                    continue

                actions = [parser.OFPActionOutput(int(puerto_salida))]
                inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
                mod = parser.OFPFlowMod(
                    datapath=datapath_actual,
                    priority=100,
                    match=match,
                    instructions=inst
                )
                datapath_actual.send_msg(mod)
                #self.guardar_regla_en_postgresql(dpid_actual, 100, match, actions)

        puerto_salida = self.obtener_puerto(sw_nombre, ruta_ida[1])
        if puerto_salida is None:
            return
        actions = [parser.OFPActionOutput(int(puerto_salida))]
        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=msg.buffer_id,
            in_port=in_port,
            actions=actions,
            data=msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
        )
        datapath.send_msg(out)
        self.logger.info(f"[REPLY] Primer paquete enviado desde {src_ip} hacia {dst_ip} a través de {sw_nombre} por el puerto {puerto_salida}")

    
    def obtener_reglas_desde_db(self):
        try:
            conn = self.obtener_conexion_bd()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT rule_id, dpid, priority, eth_type, ip_proto, ipv4_src, ipv4_dst,
                       tcp_src, tcp_dst, in_port, actions FROM reglas
            """)
            reglas = cursor.fetchall()
            conn.close()
            reglas_dict = {}
            for regla in reglas:
                (rule_id, dpid, priority, eth_type, ip_proto, ipv4_src,
                 ipv4_dst, tcp_src, tcp_dst, in_port, actions) = regla

                match_dict = {
                    "eth_type": eth_type,
                    "ip_proto": ip_proto,
                    "ipv4_src": ipv4_src,
                    "ipv4_dst": ipv4_dst,
                    "tcp_src": tcp_src,
                    "tcp_dst": tcp_dst,
                    "in_port": in_port
                }
                match_dict = {k: v for k, v in match_dict.items() if v is not None}

                actions_list = json.loads(actions) if isinstance(actions, str) else actions

                reglas_dict.setdefault(dpid, {})[rule_id] = {
                    "rule_id": rule_id,
                    "dpid": dpid,
                    "priority": priority,
                    "eth_type": eth_type,
                    "ip_proto": ip_proto,
                    "ipv4_src": ipv4_src,
                    "ipv4_dst": ipv4_dst,
                    "tcp_src": tcp_src,
                    "tcp_dst": tcp_dst,
                    "in_port": in_port,
                    "match_data": match_dict,
                    "actions": actions_list
                }
            return reglas_dict
        except Exception as e:
            self.logger.error(f"Error al cargar reglas desde la BD: {e}")
            return {}

    def comparar_reglas(self, reglas_antiguas, reglas_nuevas):
        """
        Compara las reglas antiguas con las nuevas para detectar cambios.
        """
        cambios = []
        # Itera sobre cada switch (dpid)
        dpids = set(list(reglas_antiguas.keys()) + list(reglas_nuevas.keys()))
        for dpid in dpids:
            old_rules = reglas_antiguas.get(dpid, {})
            new_rules = reglas_nuevas.get(dpid, {})
            old_ids = set(old_rules.keys())
            new_ids = set(new_rules.keys())

            # Reglas creadas
            for rule_id in new_ids - old_ids:
                cambios.append({
                    "dpid": dpid,
                    "rule_id": rule_id,
                    "campo": "Creada",
                    "valor_antiguo": None,
                    "valor_nuevo": new_rules[rule_id]
                })

            # Reglas eliminadas
            for rule_id in old_ids - new_ids:
                cambios.append({
                    "dpid": dpid,
                    "rule_id": rule_id,
                    "campo": "Eliminada",
                    "valor_antiguo": old_rules[rule_id],
                    "valor_nuevo": None
                })

            # Reglas existentes: compara los campos
            for rule_id in new_ids & old_ids:
                new_rule = new_rules[rule_id]
                old_rule = old_rules[rule_id]
                if new_rule.get("match_data", {}) != old_rule.get("match_data", {}):
                    cambios.append({
                        "dpid": dpid,
                        "rule_id": rule_id,
                        "campo": "match_data",
                        "valor_antiguo": old_rule.get("match_data"),
                        "valor_nuevo": new_rule.get("match_data")
                    })
                if new_rule.get("actions", []) != old_rule.get("actions", []):
                    cambios.append({
                        "dpid": dpid,
                        "rule_id": rule_id,
                        "campo": "actions",
                        "valor_antiguo": old_rule.get("actions"),
                        "valor_nuevo": new_rule.get("actions")
                    })
                if new_rule.get("priority") != old_rule.get("priority"):
                    cambios.append({
                        "dpid": dpid,
                        "rule_id": rule_id,
                        "campo": "priority",
                        "valor_antiguo": old_rule.get("priority"),
                        "valor_nuevo": new_rule.get("priority")
                    })
        return cambios

    def aplicar_cambios(self, dpid, rule_id, campo_modificado, valor_antiguo, valor_nuevo):
        """
        Apply changes to the switch based on detected rule modifications.
        """
        if campo_modificado in ['priority', 'match_data', 'actions']:
            self.actualizar_regla_switch(rule_id, campo_modificado, valor_nuevo, dpid)
        elif campo_modificado == "Eliminada":
            # For deletion, use the old information
            self.eliminar_regla_switch(rule_id, dpid, valor_antiguo["match_data"], valor_antiguo["priority"])
            if rule_id in self.installed_flows.get(dpid, {}):
                del self.installed_flows[dpid][rule_id]
        elif campo_modificado == "Creada":
            self.instalar_nueva_regla(rule_id, valor_nuevo, dpid)

    def instalar_nueva_regla(self, rule_id, nuevo_valor, dpid):
        """
        Install a new rule on the switch with robust ARP validation.
        Focuses only on proper rule formatting without installation verification.
        """
        self.logger.info(f"Installing rule {rule_id} on switch {dpid}")
        
        # 1. Get datapath handle
        datapath = self.datapaths.get(dpid)
        if not datapath:
            self.logger.error(f"Switch {dpid} not available")
            return

        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        # 2. Extract rule components
        match_data = nuevo_valor.get("match_data")
        actions = nuevo_valor.get("actions")
        priority = nuevo_valor.get("priority")

        # 3. Basic parameter validation
        if None in (match_data, actions, priority):
            self.logger.error(f"Incomplete rule data for rule {rule_id}")
            return

        # 4. Parse and validate match data
        try:
            match_dict = match_data if isinstance(match_data, dict) else json.loads(match_data)
            
            # Special ARP handling
            if match_dict.get('eth_type') == 2054:
                # Remove any IP-related fields for ARP
                ip_fields = ['ip_proto', 'ipv4_src', 'ipv4_dst', 'tcp_src', 'tcp_dst']
                match_dict = {k: v for k, v in match_dict.items() 
                            if k not in ip_fields and v is not None}
                
                self.logger.debug(f"Processed ARP rule match: {match_dict}")

            # 5. Create OpenFlow match
            match = parser.OFPMatch(**match_dict)
            
            # 6. Parse actions (with NORMAL fallback)
            actions_openflow = self._parse_actions(actions, parser, ofproto) or [
                parser.OFPActionOutput(ofproto.OFPP_NORMAL)
            ]

            # 7. Install the flow
            self.add_flow(datapath, priority, match, actions_openflow, rule_id=int(rule_id))
            
            # 8. Update state and log
            self.installed_flows.setdefault(dpid, {})[rule_id] = (priority, match_dict, actions)
            self.logger.info(f"Rule {rule_id} processed for switch {dpid}")
            self.guardar_log_en_postgresql(nuevo_valor, action="INSTALADA")

        except Exception as e:
            self.logger.error(f"Rule installation failed: {str(e)}")

    def eliminar_regla_switch(self, rule_id, dpid, match_data, priority):
        """
        Delete a rule from the switch and log the action in PostgreSQL.
        """
        try:
            datapath = self.datapaths.get(dpid)
            if not datapath:
                return False
            ofproto = datapath.ofproto
            parser = datapath.ofproto_parser
            match_dict = match_data if isinstance(match_data, dict) else json.loads(match_data)
            match = parser.OFPMatch(**match_dict)
            mod_delete = parser.OFPFlowMod(
                datapath=datapath,
                command=ofproto.OFPFC_DELETE,
                match=match,
                priority=priority,
                out_port=ofproto.OFPP_ANY,
                out_group=ofproto.OFPG_ANY
            )
            datapath.send_msg(mod_delete)

            # Resend the message a few times to confirm deletion
            for _ in range(3):
                hub.sleep(2)
                datapath.send_msg(mod_delete)

            self.logger.info(f"Rule {rule_id} deleted on switch {dpid}.")
            # Save the action to PostgreSQL
            self.guardar_log_en_postgresql({"dpid": dpid, "rule_id": rule_id}, action="ELIMINADA")
            return True
        except Exception as e:
            self.logger.error(f"Error deleting rule {rule_id} on switch {dpid}: {e}")
            return False

    def _parse_actions(self, actions_data, parser, ofproto):
        """
        Parse actions from the rule data.
        """
        actions = []
        if isinstance(actions_data, str):
            try:
                actions_list = json.loads(actions_data)
            except json.JSONDecodeError:
                return []
        elif isinstance(actions_data, list):
            actions_list = actions_data
        else:
            return []

        for act in actions_list:
            action_type = act.get("type", "").upper()
            if action_type == "OUTPUT":
                actions.append(parser.OFPActionOutput(int(act["port"])))
            elif action_type == "DROP":
                # DROP means not adding actions.
                continue
            elif action_type == "NORMAL":
                actions.append(parser.OFPActionOutput(ofproto.OFPP_NORMAL))
        return actions

    def _parse_match_data(self, match_data):
        """
        Parse match data with proper handling for ARP and other protocol types
        """
        try:
            if isinstance(match_data, str):
                match_dict = json.loads(match_data)
            elif isinstance(match_data, dict):
                match_dict = match_data.copy()
            else:
                return {}

            eth_type = match_dict.get('eth_type')
            
            # Clean None values
            match_dict = {k: v for k, v in match_dict.items() if v is not None}
            
            # Protocol-specific field filtering
            if eth_type == 2054:  # ARP
                # Remove all IP-related fields for ARP
                ip_fields = ['ip_proto', 'ipv4_src', 'ipv4_dst', 'tcp_src', 'tcp_dst']
                match_dict = {k: v for k, v in match_dict.items() if k not in ip_fields}
            elif eth_type == 2048:  # IPv4
                # Ensure required IP fields are present
                if 'ip_proto' not in match_dict:
                    match_dict['ip_proto'] = 0  # Default to wildcard
            else:
                # For other Ethernet types, remove IP fields
                ip_fields = ['ip_proto', 'ipv4_src', 'ipv4_dst', 'tcp_src', 'tcp_dst']
                match_dict = {k: v for k, v in match_dict.items() if k not in ip_fields}
                
            return match_dict
            
        except Exception as e:
            self.logger.error(f"Error parsing match_data: {e}")
            return {}

    def actualizar_regla_switch(self, rule_id, campo, nuevo_valor, dpid):
        datapath = self.datapaths.get(dpid)
        if not datapath:
            self.logger.warning(f"Switch {dpid} no encontrado")
            return False

        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        nuevas_reglas = self.obtener_reglas_desde_db()
        regla_modificada = nuevas_reglas.get(dpid, {}).get(rule_id)
        if not regla_modificada:
            self.logger.warning(f"Regla {rule_id} no encontrada en DB para {dpid}")
            return False

        try:
            match_data = regla_modificada.get("match_data")
            match_dict = match_data if isinstance(match_data, dict) else json.loads(match_data)
            if match_dict.get('eth_type') == 2054:
                ip_fields = ['ip_proto', 'ipv4_src', 'ipv4_dst', 'tcp_src', 'tcp_dst']
                match_dict = {k: v for k, v in match_dict.items() if k not in ip_fields and v is not None}

            installed_rule = self.installed_flows.get(dpid, {}).get(rule_id)
            if installed_rule:
                old_priority, old_match, old_actions = installed_rule
                self.eliminar_regla_switch(rule_id, dpid, old_match, old_priority)
                hub.sleep(0.5)

            new_priority = regla_modificada["priority"]
            new_actions = regla_modificada["actions"]
            match = parser.OFPMatch(**match_dict)
            actions_openflow = self._parse_actions(new_actions, parser, ofproto) or [
                parser.OFPActionOutput(ofproto.OFPP_NORMAL)
            ]

            inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions_openflow)]
            mod = parser.OFPFlowMod(
                datapath=datapath,
                priority=new_priority,
                match=match,
                instructions=inst,
                cookie=int(rule_id)
            )
            datapath.send_msg(mod)
            self.installed_flows.setdefault(dpid, {})[rule_id] = (new_priority, match_dict, new_actions)
            self.guardar_log_en_postgresql(regla_modificada, action="MODIFICADA")
            return True

        except Exception as e:
            self.logger.error(f"Error al actualizar la regla {rule_id} en {dpid}: {e}")
            return False

    def monitorizar_reglas(self):
        """
        Monitor the database for rule changes and apply them dynamically.
        """
        while self.running:
            try:
                nuevas_db = self.obtener_reglas_desde_db()
                cambios_detectados = self.comparar_reglas(self.db_rules, nuevas_db)
                if cambios_detectados:
                    for cambio in cambios_detectados:
                        dpid = cambio["dpid"]
                        rule_id = cambio["rule_id"]
                        campo_modificado = cambio["campo"]
                        valor_antiguo = cambio.get("valor_antiguo")
                        valor_nuevo = cambio.get("valor_nuevo")
                        self.logger.info(f"Change detected on switch {dpid} for rule {rule_id}: {campo_modificado}.")
                        self.aplicar_cambios(dpid, rule_id, campo_modificado, valor_antiguo, valor_nuevo)
                    # Update the local copy of the database
                    self.db_rules = nuevas_db
            except Exception as e:
                self.logger.error(f"Monitoring error: {e}.")
            time.sleep(self.monitor_interval)

    def guardar_log_en_postgresql(self, regla, action="INSTALADA"):
        """
        Guarda una entrada de log en la tabla 'logs' para los cambios de regla en PostgreSQL.
        """
        try:
            conn = self.obtener_conexion_bd()
            cursor = conn.cursor()

            actions = regla.get("actions", [])
            actions_str = json.dumps(actions)

            dpid = regla.get("dpid")
            if dpid is None:
                raise ValueError("El campo 'dpid' no puede ser None")

            cursor.execute("""
                INSERT INTO logs (
                    dpid, 
                    rule_id, 
                    action, 
                    priority, 
                    eth_type, 
                    ip_proto, 
                    ipv4_src, 
                    ipv4_dst, 
                    tcp_src, 
                    tcp_dst, 
                    in_port, 
                    actions
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                dpid,  
                regla.get("rule_id"),
                action,  
                regla.get("priority", 1),
                regla.get("eth_type"),
                regla.get("ip_proto"),
                regla.get("ipv4_src"),
                regla.get("ipv4_dst"),
                regla.get("tcp_src"),
                regla.get("tcp_dst"),
                regla.get("in_port"),
                actions_str
            ))
            conn.commit()
            #self.logger.info(f"Log registrado para la regla {regla.get('rule_id')}.")

        except psycopg2.Error as e:
            conn.rollback()
            self.logger.error(f"Error al guardar el log en PostgreSQL: {e}")
        except ValueError as ve:
            self.logger.error(f"Error de validación: {ve}")
        finally:
            conn.close()
    
    def add_flow(self, datapath, priority, match, actions, rule_id=0):
        """
        Add a flow to the switch.
        """
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(
            datapath=datapath,
            cookie=rule_id,  # Use the cookie field to identify the rule
            priority=priority,
            match=match,
            instructions=inst
        )
        datapath.send_msg(mod)

    def _install_db_rules(self, datapath, reglas_nuevas):
        """
        Install rules from the database on the switch with enhanced validation
        """
        dpid = datapath.id
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        
        #self.logger.info(f"Installing rules on switch {dpid}.")
        
        if not reglas_nuevas:
            #self.logger.warning(f"No rules defined for {dpid}.")
            return
            
        for rule_id, rule in reglas_nuevas.items():
            try:
                priority = rule["priority"]
                match_dict = self._parse_match_data(rule["match_data"])
                
                # Enhanced validation for ARP rules
                if match_dict.get('eth_type') == 2054:
                    self.logger.debug(f"Processing ARP rule {rule_id} on {dpid}")
                    if any(field in match_dict for field in ['ip_proto', 'ipv4_src', 'ipv4_dst']):
                        self.logger.error(f"Invalid ARP rule {rule_id}: Contains IP fields")
                        continue
                        
                self.logger.debug(f"match_dict for rule {rule_id}: {match_dict}")
                
                if not match_dict:
                    self.logger.warning(f"Rule {rule_id} has no valid match in {dpid}.")
                    continue
                    
                # Convert match dict to OFPMatch
                flow_match = parser.OFPMatch(**match_dict)
                actions_openflow = self._parse_actions(rule["actions"], parser, ofproto)
                
                self.add_flow(datapath, priority, flow_match, actions_openflow, rule_id=int(rule_id))
                self.installed_flows.setdefault(dpid, {})[rule_id] = (priority, match_dict, rule["actions"])
                #self.logger.info(f"Rule {rule_id} installed on switch {dpid}.")
                self.guardar_log_en_postgresql(rule, action="INSTALADA")
                
            except Exception as e:
                self.logger.error(f"Failed to install rule {rule_id} on {dpid}: {str(e)}")
                continue

    def obtener_puerto_dinamico(self, origen, destino_ip_o_nombre):
        """
        Detecta si el destino es un host (por IP) o un switch (por nombre) y obtiene el puerto correspondiente.
        """
        conn = self.obtener_conexion_bd()
        cur = conn.cursor()

        # Primero, intenta tratar el destino como IP (host)
        cur.execute("""
            SELECT h.nombre FROM hosts h WHERE h.ipv4 = %s
        """, (destino_ip_o_nombre,))
        host_row = cur.fetchone()

        if host_row:
            destino_host = host_row[0]
            cur.execute("""
                SELECT puerto_salida FROM puertos
                WHERE nodo_origen = %s AND nodo_destino = %s
            """, (origen, destino_host))
        else:
            # Si no es una IP de host, trata el destino como nombre de switch
            cur.execute("""
                SELECT puerto_salida FROM puertos
                WHERE nodo_origen = %s AND nodo_destino = %s
            """, (origen, destino_ip_o_nombre))

        res = cur.fetchone()
        cur.close()
        conn.close()
        return res[0] if res else None

    def guardar_regla_en_postgresql(self, dpid, priority, match, actions):
        try:
            conn = self.obtener_conexion_bd()
            cur = conn.cursor()

            # Obtener el último rule_id existente
            cur.execute("SELECT MAX(rule_id) FROM reglas")
            ultimo = cur.fetchone()[0]
            nuevo_rule_id = 1 if ultimo is None else ultimo + 1

            # Extraer campos relevantes del match
            match_dict = match.to_jsondict()['OFPMatch']['oxm_fields']
            campos = {
                'eth_type': None,
                'ip_proto': None,
                'ipv4_src': None,
                'ipv4_dst': None,
                'tcp_src': None,
                'tcp_dst': None,
                'in_port': None
            }

            for campo in match_dict:
                campos[campo['field']] = campo['value']

            # Serializar acciones
            acciones_serializadas = []
            for act in actions:
                if hasattr(act, 'port'):
                    acciones_serializadas.append({'type': 'OUTPUT', 'port': act.port})
                else:
                    acciones_serializadas.append({'type': 'UNKNOWN'})

            acciones_json = json.dumps(acciones_serializadas)

            # Insertar la regla en la BD
            cur.execute("""
                INSERT INTO reglas (rule_id, dpid, priority, eth_type, ip_proto,
                    ipv4_src, ipv4_dst, tcp_src, tcp_dst, in_port, actions)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                nuevo_rule_id, dpid, priority,
                campos['eth_type'], campos['ip_proto'],
                campos['ipv4_src'], campos['ipv4_dst'],
                campos['tcp_src'], campos['tcp_dst'],
                campos['in_port'], acciones_json
            ))

            conn.commit()
            self.logger.info(f"[DB] Regla {nuevo_rule_id} guardada en la BD para el switch {dpid}")
        except Exception as e:
            self.logger.error(f"[DB ERROR] No se pudo guardar la regla en la BD: {e}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()


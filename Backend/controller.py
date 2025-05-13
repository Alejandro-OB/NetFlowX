from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib import hub
from ryu.lib.packet import packet, ethernet
import psycopg2
import json
import time


class DynamicFlowSwitch(app_manager.RyuApp):
    # Supported OpenFlow versions
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(DynamicFlowSwitch, self).__init__(*args, **kwargs)
        # Dictionary to store datapaths (switches)
        self.datapaths = {}
        # Dictionary to track installed flows
        self.installed_flows = {}
        # Dictionary to cache rules from the database
        self.db_rules = {}
        # Flag to control the monitoring thread
        self.running = True
        self.mac_to_port = {}
        
        self.logger.info("DynamicFlowSwitch initialized.")
        # Interval for monitoring database changes
        self.monitor_interval = kwargs.get('monitor_interval', 10)
        # Start the monitoring thread
        self.monitor_thread = hub.spawn(self.monitorizar_reglas)

    def obtener_conexion_bd(self):
        # Conexión a PostgreSQL usando los parámetros explícitos
        return psycopg2.connect(
            dbname="geant_network",        # Nombre de la base de datos
            user="geant_user",             # Usuario de la base de datos
            password="geant",              # Contraseña de la base de datos
            host="192.168.18.151",        # Dirección IP del servidor donde está PostgreSQL
            port="5432"                    # Puerto de PostgreSQL
        )
    
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

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        """
        Handle the switch connection event and install default and database rules.
        """
        datapath = ev.msg.datapath
       
        #self.setup_arp_rules(datapath)   # Configurar ARP
        #self.setup_icmp_rules(datapath)  # Configurar ICMP
        dpid = datapath.id
        self.datapaths[dpid] = datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        # Default rule: send unknown packets to the controller
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions, rule_id=0)

        #self.logger.info(f"Switch {dpid} connected. Installing rules from the database...")
        reglas_db = self.obtener_reglas_desde_db().get(dpid, {})
        self.db_rules.setdefault(dpid, {}).update(reglas_db)
        if not reglas_db:
            self.logger.warning(f"No rules found for switch {dpid}.")
        else:
            self.logger.info(f"Rules for {dpid} loaded ({len(reglas_db)} rules).")
        self._install_db_rules(datapath, reglas_db)

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

    def obtener_reglas_desde_db(self):
        """
        Carga las reglas desde la base de datos PostgreSQL y las organiza
        por dpid -> rule_id -> datos de la regla.
        """
        try:
            conn = self.obtener_conexion_bd()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT rule_id, dpid, priority, eth_type, ip_proto, ipv4_src, ipv4_dst, tcp_src, tcp_dst, in_port, actions
                FROM reglas
            """)
            reglas = cursor.fetchall()
            conn.close()

            reglas_dict = {}
            for regla in reglas:
                (rule_id, dpid, priority, eth_type, ip_proto, 
                ipv4_src, ipv4_dst, tcp_src, tcp_dst, in_port, actions) = regla

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

                # Parsear las acciones
                if isinstance(actions, str):
                    actions_list = json.loads(actions)
                else:
                    actions_list = actions

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
            self.logger.error(f"Error al cargar las reglas: {e}")
            return {}
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
    
    def actualizar_regla_switch(self, rule_id, campo, nuevo_valor, dpid):
        """
        Update a rule on the switch with robust ARP handling and log the update to PostgreSQL.
        """
        #self.logger.info(f"Updating rule {rule_id} on switch {dpid}")
        
        # 1. Get datapath handle
        datapath = self.datapaths.get(dpid)
        if not datapath:
            self.logger.warning(f"Switch {dpid} not found")
            return False

        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        # 2. Get the updated rule from database
        nuevas_reglas = self.obtener_reglas_desde_db()
        regla_modificada = nuevas_reglas.get(dpid, {}).get(rule_id)
        if not regla_modificada:
            self.logger.warning(f"Rule {rule_id} not found in DB for switch {dpid}")
            return False

        try:
            # 3. Parse and validate match data with ARP handling
            new_match_data = regla_modificada["match_data"]
            match_dict = new_match_data if isinstance(new_match_data, dict) else json.loads(new_match_data)
            
            # Special ARP validation
            if match_dict.get('eth_type') == 2054:
                self.logger.debug(f"Processing ARP rule update {rule_id}")
                
                # Remove incompatible IP fields for ARP
                ip_fields = ['ip_proto', 'ipv4_src', 'ipv4_dst', 'tcp_src', 'tcp_dst']
                match_dict = {k: v for k, v in match_dict.items() 
                            if k not in ip_fields and v is not None}
                
                self.logger.debug(f"ARP match dict after cleanup: {match_dict}")

            # 4. Delete old rule if exists
            installed_rule = self.installed_flows.get(dpid, {}).get(rule_id)
            if installed_rule:
                old_priority, old_match, old_actions = installed_rule
                self.logger.debug(f"Removing old version of rule {rule_id}")
                self.eliminar_regla_switch(rule_id, dpid, old_match, old_priority)
                hub.sleep(0.5)  # Brief pause for rule deletion

            # 5. Prepare new flow
            new_priority = regla_modificada["priority"]
            new_actions = regla_modificada["actions"]
            
            # Create OpenFlow match
            match = parser.OFPMatch(**match_dict)
            actions_openflow = self._parse_actions(new_actions, parser, ofproto) or [
                parser.OFPActionOutput(ofproto.OFPP_NORMAL)
            ]

            # 6. Install updated rule
            self.add_flow(datapath, new_priority, match, actions_openflow, rule_id=int(rule_id))
            
            # 7. Update internal state
            self.installed_flows.setdefault(dpid, {})[rule_id] = (new_priority, match_dict, new_actions)
            self.logger.info(f"Successfully updated rule {rule_id} on switch {dpid}")
            
            # 8. Log the update
            self.guardar_log_en_postgresql(regla_modificada, action="MODIFICADA")
            return True

        except Exception as e:
            self.logger.error(f"Failed to update rule {rule_id} on {dpid}: {str(e)}")
            return False

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
    
    def setup_arp_rules(self, datapath):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        
        # Regla ARP con flooding explícito
        arp_match = parser.OFPMatch(eth_type=2054)
        arp_actions = [parser.OFPActionOutput(ofproto.OFPP_FLOOD)]
        self.add_flow(datapath, priority=20000, match=arp_match, 
                    actions=arp_actions, rule_id=1)
            
    
    def setup_icmp_rules(self, datapath):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        
        # Regla ICMP con forwarding adecuado
        icmp_match = parser.OFPMatch(eth_type=0x0800, ip_proto=1)
        icmp_actions = [parser.OFPActionOutput(ofproto.OFPP_NORMAL)]
        self.add_flow(datapath, priority=10000, match=icmp_match,
                    actions=icmp_actions, rule_id=2)
from mininet.topo import Topo
from mininet.link import TCLink
from mininet.node import RemoteController, OVSKernelSwitch # Importar OVSKernelSwitch
import psycopg2
import sys

class GeantTopo(Topo):
    def build(self):
        # Diccionarios para almacenar referencias a los objetos de Mininet
        # Usaremos el id_switch de la DB como clave para los switches
        switches = {}
        # Usaremos el nombre del host de la DB como clave para los hosts
        hosts = {}

        # Diccionarios para mapear entre IDs y nombres de switches/ciudades
        id_to_nombre = {}
        nombre_to_id = {}
        nombre_to_switch_obj = {} # Para almacenar los objetos switch de Mininet por nombre de ciudad

        # Conexión a la base de datos
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
            print("Conexión a la base de datos establecida.")

            # 1. Obtener switches (id y nombre)
            cur.execute("SELECT id_switch, nombre FROM switches;")
            switch_list = cur.fetchall()
            
            for id_switch, ciudad in switch_list:
                # CORRECCIÓN: Formatear explícitamente el DPID como una cadena hexadecimal de 16 caracteres
                dpid_str = "{:016x}".format(id_switch)
                # --- MODIFICACIÓN AQUÍ: Habilitar STP en los switches de OVS ---
                sw = self.addSwitch(f's{id_switch}', dpid=dpid_str, cls=OVSKernelSwitch, stp=True)
                # ---------------------------------------------------------------
                switches[id_switch] = sw
                id_to_nombre[id_switch] = ciudad
                nombre_to_id[ciudad] = id_switch
                nombre_to_switch_obj[ciudad] = sw
                print(f"Switch creado: s{id_switch} ({ciudad}) con DPID {dpid_str}, STP habilitado")

            # 2. Obtener hosts con IP y switch asociado
            cur.execute("SELECT nombre, switch_asociado, ipv4, mac FROM hosts;")
            hosts_list = cur.fetchall()

            for nombre_host, id_switch_asociado, ip, mac in hosts_list:
                h = self.addHost(nombre_host, ip=ip, mac=mac)
                hosts[nombre_host] = h
                print(f"Host creado: {nombre_host} IP: {ip} MAC: {mac} conectado lógicamente a switch ID {id_switch_asociado}")


            # 3. Obtener puertos para conexiones (host-switch y switch-switch)
            cur.execute("SELECT nodo_origen, nodo_destino, puerto_origen, puerto_destino FROM puertos;")
            puertos_list = cur.fetchall()

            # Crear diccionario para rápido acceso: (origen_nombre, destino_nombre) -> (puerto_origen, puerto_destino)
            puertos_dict = {}
            for nodo_origen, nodo_destino, puerto_origen_val, puerto_destino_val in puertos_list: # Renombrado para evitar confusión
                # Convertir puertos a int si no son None
                puerto_origen_int = int(puerto_origen_val) if puerto_origen_val is not None else None
                puerto_destino_int = int(puerto_destino_val) if puerto_destino_val is not None else None
                puertos_dict[(nodo_origen, nodo_destino)] = (puerto_origen_int, puerto_destino_int)

            # 4. Conectar hosts a switches con puerto específico en switch
            for nombre_host, id_switch_asociado, ip, mac in hosts_list:
                ciudad_switch = id_to_nombre[id_switch_asociado]
                
                # Buscar puertos específicos para la conexión host-switch
                puertos = puertos_dict.get((ciudad_switch, nombre_host), (None, None))
                puerto_origen_en_switch = puertos[0] 
                puerto_destino_en_host = puertos[1] 

                link_kwargs = {}
                if puerto_destino_en_host is not None:
                    link_kwargs['port1'] = puerto_destino_en_host # Puerto en el host
                if puerto_origen_en_switch is not None:
                    link_kwargs['port2'] = puerto_origen_en_switch # Puerto en el switch

                print(f"Conectando {nombre_host} a {ciudad_switch} (s{id_switch_asociado}) con puertos: host={puerto_destino_en_host}, switch={puerto_origen_en_switch}")
                self.addLink(hosts[nombre_host], switches[id_switch_asociado], **link_kwargs)

            # 5. Obtener enlaces switch-switch con ancho de banda
            cur.execute("SELECT id_origen, id_destino, ancho_banda FROM enlaces;")
            enlaces_list = cur.fetchall()

            for id_origen, id_destino, bw in enlaces_list:
                if id_origen in switches and id_destino in switches:
                    ciudad_origen = id_to_nombre[id_origen]
                    ciudad_destino = id_to_nombre[id_destino]

                    # Buscar puertos específicos para la conexión switch-switch
                    puertos = puertos_dict.get((ciudad_origen, ciudad_destino), None)
                    if puertos is None:
                        # Intentar sentido inverso y luego invertir puertos
                        puertos_inv = puertos_dict.get((ciudad_destino, ciudad_origen), None)
                        if puertos_inv is not None:
                            puerto_origen_en_sw = puertos_inv[1]  # invertir
                            puerto_destino_en_sw = puertos_inv[0]
                        else:
                            puerto_origen_en_sw = None
                            puerto_destino_en_sw = None
                    else:
                        puerto_origen_en_sw, puerto_destino_en_sw = puertos

                    try:
                        bw_float = float(bw)
                    except (ValueError, TypeError):
                        bw_float = 1000.0  # valor por defecto si falla la conversión

                    kwargs = {'cls': TCLink, 'bw': bw_float}
                    if puerto_origen_en_sw is not None:
                        kwargs['port1'] = puerto_origen_en_sw  # Puerto en el switch de origen
                    if puerto_destino_en_sw is not None:
                        kwargs['port2'] = puerto_destino_en_sw  # Puerto en el switch de destino

                    print(f"Enlace: s{id_origen} ({ciudad_origen}, puerto {puerto_origen_en_sw}) <-> s{id_destino} ({ciudad_destino}, puerto {puerto_destino_en_sw}) con bw {bw_float} Mbps")
                    self.addLink(switches[id_origen], switches[id_destino], **kwargs)
                else:
                    print(f"Advertencia: Enlace entre switches no encontrados en la topología: {id_origen} <-> {id_destino}")


        except psycopg2.Error as e:
            print(f"Error de base de datos: {e}")
            sys.exit(1) # Salir si hay un error crítico de DB
        except Exception as e:
            print(f"Error inesperado al construir la topología: {e}")
            sys.exit(1)
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()
            print("Conexión a la base de datos cerrada.")

# Para ejecutar la topología desde la línea de comandos
# sudo mn --custom geant_topo.py --topo geant --controller remote
topos = {'geant': (lambda: GeantTopo())}
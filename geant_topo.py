from mininet.topo import Topo
from mininet.link import TCLink
import psycopg2

class GeantTopo(Topo):
    def build(self):
        switches = {}
        hosts = {}

        # Conexión a la base de datos
        conn = psycopg2.connect(
            dbname="geant_network",
            user="geant_user",
            password="geant",
            host="localhost",
            port="5432"
        )
        cur = conn.cursor()

        # 1. Obtener switches
        cur.execute("SELECT id_switch, nombre FROM switches;")
        switch_list = cur.fetchall()

        for i, (id_switch, ciudad) in enumerate(switch_list):
            sw = self.addSwitch(f's{id_switch}')
            switches[ciudad] = sw

            # 2 hosts por switch
            for j in range(2):
                host = self.addHost(f'h{id_switch}_{j+1}')
                self.addLink(host, sw)

        # 2. Obtener enlaces con ancho de banda
        cur.execute("""
            SELECT s1.nombre, s2.nombre, e.ancho_banda
            FROM enlaces e
            JOIN switches s1 ON e.id_origen = s1.id_switch
            JOIN switches s2 ON e.id_destino = s2.id_switch;
        """)
        enlaces = cur.fetchall()

        for ciudad1, ciudad2, bw in enlaces:
            if ciudad1 in switches and ciudad2 in switches:
                self.addLink(
                    switches[ciudad1],
                    switches[ciudad2],
                    cls=TCLink,
                    bw=bw
                )

        cur.close()
        conn.close()

topos = {'geant': (lambda: GeantTopo())}

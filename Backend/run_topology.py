from mininet.net import Mininet
from mininet.cli import CLI
from mininet.link import TCLink
from mininet.node import RemoteController
from topo_nueva import GeantTopo

def main():
    print("[INFO] Iniciando red con topología Geant y configuración multicast...")

    topo = GeantTopo()

    controller = RemoteController('c0', ip='192.168.18.7', port=6653)

    net = Mininet(topo=topo, controller=controller, link=TCLink)

    net.start()

    for host in net.hosts:
        interfaces = host.intfList()
        iface = None

        for intf in interfaces:
            if str(intf) != 'lo':
                iface = str(intf)
                break

        if not iface:
            print(f"[WARNING] {host.name} no tiene interfaces válidas (solo loopback).")
            continue

        route_cmd = f"ip route add 224.0.0.0/4 dev {iface}"
        print(f"[INFO] Añadiendo ruta multicast en {host.name}: {route_cmd}")
        host.cmd(route_cmd)

        igmp_cmd = f"sysctl -w net.ipv4.conf.{iface}.force_igmp_version=2"
        print(f"[INFO] Forzando IGMPv2 en {host.name}: {igmp_cmd}")
        host.cmd(igmp_cmd)

        host.cmd("sysctl -w net.ipv4.ip_forward=1")

        print(f"[INFO] {host.name} IP: {host.IP()} - Interfaces: {[str(i) for i in interfaces]}")

    print("[INFO] Red iniciada y configuración multicast aplicada.")
    CLI(net)
    net.stop()

if __name__ == '__main__':
    main()

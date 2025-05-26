from mininet.net import Mininet
from mininet.cli import CLI
from mininet.link import TCLink
from mininet.node import RemoteController
from geant_topo_stp import GeantTopo

def main():
    print("[INFO] Iniciando red con topología Geant y configuración multicast...")

    # Usa tu topología personalizada
    topo = GeantTopo()

    # Define el controlador remoto
    controller = RemoteController('c0', ip='192.168.18.161', port=6653)

    # Crea la red con tu topología y controlador remoto
    net = Mininet(topo=topo, controller=controller, link=TCLink)

    # Inicia la red
    net.start()

    # Añadir la ruta multicast a cada host
    for host in net.hosts:
        iface = host.name + "-eth0"
        cmd = f"ip route add 224.0.0.0/4 dev {iface}"
        print(f"[INFO] Añadiendo ruta multicast en {host.name}: {cmd}")
        host.cmd(cmd)

    print("[INFO] Red iniciada y rutas multicast configuradas.")
    CLI(net)
    net.stop()

if __name__ == '__main__':
    main()
import psycopg2
import json
from config import Config

# Conexión a la base de datos PostgreSQL
def get_db_connection():
    return psycopg2.connect(Config.get_db_uri())

# Función para generar reglas y guardarlas en la base de datos
def generar_e_insertar_reglas():
    # Conectar a la base de datos
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        reglas = []
        rule_id_counter = 1  # Iniciar el contador de rule_id desde 1

        # Generar reglas para ICMP (Protocolo 1)
        for i in range(1, 24):
            for j in range(i + 1, 24):
                # Asignar in_port en función de las conexiones de los hosts
                if i == 1:
                    in_port = 1  # Tráfico de h1_1 hacia s1-eth1
                else:
                    in_port = 2  # Tráfico de otro switch, ajustamos el puerto

                regla_icmp = {
                    "dpid": i,
                    "rule_id": rule_id_counter,  # Asignar el rule_id numérico
                    "priority": 100,
                    "eth_type": 2048,  # IPv4
                    "ip_proto": 1,  # ICMP
                    "ipv4_src": f"10.0.0.{i}",
                    "ipv4_dst": f"10.0.0.{j}",
                    "in_port": in_port,
                    "actions": [{"type": "OUTPUT", "port": j}]
                }
                reglas.append(regla_icmp)
                rule_id_counter += 1  # Incrementar el rule_id para la siguiente regla

        # Generar reglas para ARP (Protocolo 2054)
        for i in range(1, 24):
            for j in range(i + 1, 24):
                in_port = 1 if i == 1 else 2
                regla_arp = {
                    "dpid": i,
                    "rule_id": rule_id_counter,  # Asignar el rule_id numérico
                    "priority": 100,
                    "eth_type": 2054,  # ARP
                    "ip_proto": None,  # No protocolo, solo Ethernet
                    "ipv4_src": None,
                    "ipv4_dst": None,
                    "in_port": in_port,
                    "actions": [{"type": "OUTPUT", "port": j}]
                }
                reglas.append(regla_arp)
                rule_id_counter += 1  # Incrementar el rule_id para la siguiente regla

        # Insertar las reglas en la base de datos
        for regla in reglas:
            cursor.execute("""
                INSERT INTO reglas (dpid, rule_id, priority, eth_type, ip_proto, ipv4_src, ipv4_dst, tcp_src, tcp_dst, in_port, actions)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            """, (
                regla['dpid'], regla['rule_id'], regla['priority'], regla['eth_type'], regla['ip_proto'],
                regla['ipv4_src'], regla['ipv4_dst'], regla.get('tcp_src'), regla.get('tcp_dst'), regla['in_port'],
                json.dumps(regla['actions'])
            ))

        # Confirmar los cambios en la base de datos
        conn.commit()
        print("✅ Reglas generadas e insertadas correctamente.")

    except Exception as e:
        # Si ocurre un error, hacer rollback de los cambios
        conn.rollback()
        print(f"❌ Error al insertar reglas: {str(e)}")
    finally:
        # Cerrar la conexión a la base de datos
        cursor.close()
        conn.close()

# Ejecutar la función
if __name__ == "__main__":
    generar_e_insertar_reglas()

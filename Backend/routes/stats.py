from flask import Blueprint, jsonify
from services.db import fetch_all

bp = Blueprint('stats', __name__)

from services.db import fetch_one, execute_query
import logging

def registrar_evento(tipo, nombre_host):
    try:
        host = fetch_one("SELECT id_host FROM hosts WHERE nombre = %s", (nombre_host,))
        if host:
            execute_query(
                "INSERT INTO estadisticas (id_host, tipo, timestamp) VALUES (%s, %s, NOW())",
                (host['id_host'], tipo)
            )
        else:
            logging.warning(f"No se encontró el host '{nombre_host}' para registrar evento '{tipo}'")
    except Exception as e:
        logging.error(f"Error al registrar evento '{tipo}' para host '{nombre_host}': {str(e)}")


@bp.route('/dashboard', methods=['GET'])
def get_dashboard_stats():
    try:
        # Clientes por servidor
        clientes_por_servidor = fetch_all("""
            SELECT servidor_asignado AS servidor, COUNT(*) AS total_clientes
            FROM clientes_activos
            GROUP BY servidor_asignado;
        """)

        # Total de transmisiones 
        transmisiones_activas = fetch_all("""
            SELECT COUNT(DISTINCT ip_destino) AS total_transmisiones
            FROM servidores_vlc_activos
            WHERE status = 'activo';
        """)[0]['total_transmisiones']

        # Clientes activos totales
        total_clientes = fetch_all("""
            SELECT COUNT(*) AS total_clientes
            FROM clientes_activos;
        """)[0]['total_clientes']

        # Carga vs peso
        carga_vs_peso = fetch_all("""
            SELECT s.host_name AS servidor, s.server_weight AS peso_configurado,
                   COUNT(c.host_cliente) AS clientes_asignados
            FROM servidores_vlc_activos s
            LEFT JOIN clientes_activos c ON c.servidor_asignado = s.host_name
            WHERE s.status = 'activo'
            GROUP BY s.host_name, s.server_weight;
        """)

        # Últimos eventos 
        ultimos_eventos = fetch_all("""
            SELECT h.nombre AS host, e.tipo AS tipo_evento, e.timestamp
            FROM estadisticas e
            JOIN hosts h ON e.id_host = h.id_host
            ORDER BY e.timestamp DESC
            LIMIT 10;
        """)

        # Total de flujos multicast activos 
        flujos_multicast = fetch_all("""
            SELECT ip_destino AS grupo, COUNT(*) AS total_puertos
            FROM clientes_activos
            GROUP BY ip_destino;
        """)

        return jsonify({
            "clientes_por_servidor": clientes_por_servidor,
            "transmisiones_activas": transmisiones_activas,
            "total_clientes": total_clientes,
            "carga_vs_peso": carga_vs_peso,
            "ultimos_eventos": ultimos_eventos,
            "flujos_multicast": flujos_multicast
        }), 200

    except Exception as e:
        return jsonify({"error": f"Error al generar estadísticas: {str(e)}"}), 500

@bp.route('/combined_stats', methods=['GET'])
def get_combined_stats():
    try:
        # Fetch combined data from both rutas_ping and latencias
        combined_stats = fetch_all("""
            SELECT
                l.host_origen,
                l.host_destino,
                r.descripcion AS ruta,
                r.algoritmo_enrutamiento,
                l.rtt_ms AS rtt,
                l.jitter_ms AS jitter
            FROM rutas_ping r
            JOIN latencias l ON r.id_ruta = l.id_ruta;
        """)
        
        return jsonify(combined_stats), 200
    
    except Exception as e:
        return jsonify({"error": f"Error al generar estadísticas combinadas: {str(e)}"}), 500

@bp.route('/comparar_algoritmos', methods=['GET'])
def comparar_algoritmos():
    try:
        # Obtener las métricas de RTT y Jitter para cada algoritmo
        metrics = fetch_all("""
            SELECT r.algoritmo_enrutamiento, 
                   AVG(l.rtt_ms) AS avg_rtt, 
                   AVG(l.jitter_ms) AS avg_jitter
            FROM rutas_ping r
            JOIN latencias l ON r.id_ruta = l.id_ruta
            WHERE r.algoritmo_enrutamiento IN ('dijkstra', 'shortest_path')
            GROUP BY r.algoritmo_enrutamiento;
        """)

        # Preparar los datos para el gráfico
        data = {
            "dijkstra": {
                "avg_rtt": None,
                "avg_jitter": None
            },
            "shortest_path": {
                "avg_rtt": None,
                "avg_jitter": None
            }
        }

        for metric in metrics:
            if metric['algoritmo_enrutamiento'] == 'dijkstra':
                data['dijkstra']['avg_rtt'] = metric['avg_rtt']
                data['dijkstra']['avg_jitter'] = metric['avg_jitter']
            elif metric['algoritmo_enrutamiento'] == 'shortest_path':
                data['shortest_path']['avg_rtt'] = metric['avg_rtt']
                data['shortest_path']['avg_jitter'] = metric['avg_jitter']

        return jsonify(data), 200

    except Exception as e:
        return jsonify({"error": f"Error al generar la comparación: {str(e)}"}), 500

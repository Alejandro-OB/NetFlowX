from flask import Blueprint, jsonify, request
import subprocess
import re
import os
import atexit # Para limpiar procesos al cerrar la aplicación
import signal # Para manejar señales de terminación y limpiar
import psycopg2 # Para interactuar con la base de datos PostgreSQL
import time # Para pausas si es necesario
import requests # Para hacer solicitudes HTTP al agente de Mininet

# Importa las funciones de la base de datos desde services.db
# Asegúrate de que 'services/db.py' exista y contenga 'fetch_all' y 'execute_query'
from services.db import fetch_all, execute_query

servers_bp = Blueprint('servers', __name__)

# --- Configuración de la base de datos PostgreSQL ---
DB_CONFIG = {
    "dbname": os.getenv("DB_NAME", "geant_network"),
    "user": os.getenv("DB_USER", "geant_user"),
    "password": os.getenv("DB_PASSWORD", "geant"),
    "host": os.getenv("DB_HOST", "192.168.18.151"), # IP de tu servidor PostgreSQL
    "port": os.getenv("DB_PORT", "5432")
}


MININET_AGENT_URL = "http://192.168.18.206:5002" # Ejemplo: IP de la máquina de Mininet


video_processes = {} # { "h1_1": {"video_path": "/path/to/video.mp4", "ip_destino": "10.0.0.2", "puerto": 5004, "status": "activo"} }

# No necesitamos get_host_pid ni cleanup_processes directamente aquí,
# ya que el agente remoto se encarga de la ejecución local de mnexec y su propia limpieza.
# Sin embargo, mantenemos un mecanismo de limpieza para el *estado en memoria* de este Flask.
def cleanup_local_cache():
    print("Cerrando Blueprint de servidores: limpiando caché local de procesos de video.")
    video_processes.clear()

atexit.register(cleanup_local_cache)


@servers_bp.route('/api/hosts', methods=['GET'])
def get_available_hosts_for_ui():
    """
    Obtiene la lista de hosts disponibles desde la base de datos para la interfaz de usuario.
    Solo incluye hosts donde es_servidor es FALSE.
    """
    query = """
        SELECT nombre FROM hosts
        WHERE es_servidor = FALSE -- <--- FILTRO AGREGADO AQUÍ
        ORDER BY
            CASE WHEN nombre ~ '^h\d+_\d+$' THEN 1 ELSE 0 END, -- Prioriza hX_Y
            CAST(split_part(nombre, '_', 1) AS TEXT),
            CAST(split_part(nombre, '_', 2) AS INT);
    """
    data = fetch_all(query)
    hosts_list = [row['nombre'] for row in data]
    return jsonify(hosts_list)

@servers_bp.route('/api/start_vlc_server', methods=['POST'])
def start_vlc_server_route():
    """
    Inicia un servidor de video (ffmpeg) en un host de Mininet a través del agente remoto.
    """
    data = request.get_json()

    host = data.get('host')
    video_path = data.get('video_path', '/mininet/sample.mp4')
    ip_destino = data.get('ip_destino', '10.0.0.2')
    puerto = data.get('puerto', '5004')

    # 1. Validación de parámetros de entrada
    if not all([host, video_path, ip_destino, puerto]):
        return jsonify({"error": "Faltan parámetros requeridos (host, video_path, ip_destino, puerto)"}), 400

    if not host or not re.match(r'^[a-zA-Z0-9_-]+$', host):
        return jsonify({"error": "Parámetro 'host' inválido o ausente"}), 400
    if not video_path:
        return jsonify({"error": "La ruta del video es requerida"}), 400
    if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', ip_destino):
        return jsonify({"error": "Parámetro 'ip_destino' inválido"}), 400
    try:
        puerto = int(puerto)
        if not (1024 <= puerto <= 65535):
            raise ValueError
    except ValueError:
        return jsonify({"error": "Parámetro 'puerto' inválido"}), 400

    # 2. Contactar al agente de Mininet para iniciar ffmpeg
    agent_endpoint = f"{MININET_AGENT_URL}/mininet/start_ffmpeg"
    payload = {
        "host": host,
        "video_path": video_path,
        "ip_destino": ip_destino,
        "puerto": puerto
    }
    try:
        response = requests.post(agent_endpoint, json=payload, timeout=20)
        response.raise_for_status() # Lanza una excepción para códigos de estado HTTP 4xx/5xx
        agent_response = response.json()

        if not agent_response.get("success"):
            return jsonify({"error": agent_response.get("message", "Fallo al iniciar en el agente"), "details": agent_response.get("details")}), 500

        # 3. Registrar el estado en la base de datos (transacción para ambos updates)
        conn = None
        cur = None
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cur = conn.cursor()

            # A. Insertar/Actualizar en servidores_vlc_activos
            cur.execute("""
                INSERT INTO servidores_vlc_activos (host_name, video_path, status, process_pid, ip_destino, puerto)
                VALUES (%s, %s, 'activo', %s, %s, %s)
                ON CONFLICT (host_name) DO UPDATE SET
                    video_path = EXCLUDED.video_path,
                    status = 'activo',
                    process_pid = EXCLUDED.process_pid,
                    ip_destino = EXCLUDED.ip_destino,
                    puerto = EXCLUDED.puerto,
                    last_updated = NOW();
            """, (host, video_path, agent_response.get("ffmpeg_pid"), ip_destino, puerto))
            print(f"Servidor VLC en {host} registrado/actualizado en DB con PID {agent_response.get('ffmpeg_pid')}.")

            # B. ACTUALIZACIÓN CLAVE: Marcar el host como servidor y activo en la tabla 'hosts'
            cur.execute("""
                UPDATE hosts
                SET es_servidor = TRUE, activo = TRUE
                WHERE nombre = %s;
            """, (host,))
            print(f"Host '{host}' marcado como es_servidor=TRUE y activo=TRUE en la tabla 'hosts'.")
            
            conn.commit() # Confirmar ambas operaciones
            
            # Actualizar caché local
            video_processes[host] = {
                "video_path": video_path,
                "ip_destino": ip_destino,
                "puerto": puerto,
                "status": "activo",
                "ffmpeg_pid": agent_response.get("ffmpeg_pid")
            }

        except psycopg2.Error as db_err:
            print(f"Error DB al registrar/actualizar servidor VLC o hosts: {db_err}")
            # Si falla la DB, deberíamos intentar detener el proceso en el agente para consistencia
            try:
                requests.post(f"{MININET_AGENT_URL}/mininet/stop_ffmpeg", json={"host": host}, timeout=5)
            except Exception as e:
                print(f"Advertencia: Fallo al intentar detener ffmpeg en agente después de error DB: {e}")
            return jsonify({"error": "Servidor iniciado, pero fallo al registrar en DB", "details": str(db_err)}), 500
        finally:
            if cur: cur.close()
            if conn: conn.close()

        return jsonify({
            "success": True,
            "message": f"Transmisión iniciada desde {host} a udp://{ip_destino}:{puerto} (vía agente)",
            "ffmpeg_pid": agent_response.get("ffmpeg_pid")
        })

    except requests.exceptions.RequestException as e:
        print(f"Error al contactar al agente de Mininet en {MININET_AGENT_URL}: {e}")
        return jsonify({"error": "No se pudo contactar al agente de Mininet", "details": str(e)}), 502
    except Exception as e:
        print(f"Error inesperado en start_vlc_server_route: {e}")
        return jsonify({"error": "Fallo inesperado", "details": str(e)}), 500


@servers_bp.route('/api/stop_vlc_server', methods=['POST'])
def stop_vlc_server_route():
    """
    Detiene un servidor de video (ffmpeg) en un host de Mininet a través del agente remoto.
    """
    data = request.get_json()
    host = data.get('host')

    if not host or not re.match(r'^[a-zA-Z0-9_-]+$', host):
        return jsonify({"error": "Host inválido o ausente"}), 400

    # 1. Contactar al agente de Mininet para detener ffmpeg
    agent_endpoint = f"{MININET_AGENT_URL}/mininet/stop_ffmpeg"
    payload = {"host": host}
    try:
        response = requests.post(agent_endpoint, json=payload, timeout=10)
        response.raise_for_status()
        agent_response = response.json()

        if not agent_response.get("success"):
            return jsonify({"error": agent_response.get("message", "Fallo al detener en el agente"), "details": agent_response.get("details")}), 500

        # 2. Actualizar el estado en la base de datos (transacción)
        conn = None
        cur = None
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cur = conn.cursor()
            
            # A. Marcar como inactivo en servidores_vlc_activos
            cur.execute("UPDATE servidores_vlc_activos SET status = 'inactivo', process_pid = NULL WHERE host_name = %s;", (host,))
            print(f"Servidor VLC en {host} marcado como inactivo en DB.")

            # B. Marcar como inactivo en la tabla 'hosts' también
            cur.execute("UPDATE hosts SET activo = FALSE WHERE nombre = %s;", (host,))
            print(f"Host '{host}' marcado como activo=FALSE en la tabla 'hosts'.")

            conn.commit() # Confirmar ambas operaciones
            
            if host in video_processes:
                del video_processes[host] # Limpiar caché local
        except psycopg2.Error as db_err:
            print(f"Error DB al actualizar estado VLC a inactivo: {db_err}")
            return jsonify({"error": "Proceso detenido, pero fallo al actualizar DB", "details": str(db_err)}), 500
        finally:
            if cur: cur.close()
            if conn: cur.close()

        return jsonify({
            "success": True,
            "message": f"Proceso de video en {host} fue terminado (vía agente) y estado actualizado."
        })

    except requests.exceptions.RequestException as e:
        print(f"Error al contactar al agente de Mininet en {MININET_AGENT_URL}: {e}")
        return jsonify({"error": "No se pudo contactar al agente de Mininet", "details": str(e)}), 502
    except Exception as e:
        print(f"Error inesperado en stop_vlc_server_route: {e}")
        return jsonify({"error": "Fallo inesperado", "details": str(e)}), 500


@servers_bp.route('/api/change_vlc_video', methods=['POST'])
def change_vlc_video_route():
    """
    Cambia la ruta del video para un servidor VLC activo en un host a través del agente remoto.
    Detiene el proceso actual y lo reinicia con la nueva ruta.
    """
    data = request.get_json()
    host = data.get('host')
    new_video_path = data.get('new_video_path')

    if not host or not re.match(r'^[a-zA-Z0-9_-]+$', host):
        return jsonify({"error": "Host inválido o ausente"}), 400
    if not new_video_path:
        return jsonify({"error": "La nueva ruta del video es requerida"}), 400

    # 1. Obtener IP y puerto actuales del host desde la DB
    conn = None
    cur = None
    ip_destino = None
    puerto = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        cur.execute("SELECT ip_destino, puerto FROM servidores_vlc_activos WHERE host_name = %s AND status = 'activo';", (host,))
        db_result = cur.fetchone()
        if db_result:
            ip_destino = db_result[0]
            puerto = db_result[1]
        else:
            return jsonify({"error": f"No se encontró información de transmisión activa para el host {host}"}), 404
    except psycopg2.Error as db_err:
        print(f"Error DB al obtener info para cambiar video: {db_err}")
        return jsonify({"error": "Fallo al consultar DB para cambiar video", "details": str(db_err)}), 500
    finally:
        if cur: cur.close()
        if conn: cur.close()
    
    if not ip_destino or not puerto:
        return jsonify({"error": f"No se pudo obtener la IP y puerto de destino para el host {host}"}), 500

    # 2. Detener el proceso existente a través del agente
    agent_stop_endpoint = f"{MININET_AGENT_URL}/mininet/stop_ffmpeg"
    stop_payload = {"host": host}
    try:
        stop_response = requests.post(agent_stop_endpoint, json=stop_payload, timeout=10)
        stop_response.raise_for_status()
        stop_agent_response = stop_response.json()
        if not stop_agent_response.get("success"):
            print(f"Advertencia: Agente reportó fallo al detener proceso en {host}: {stop_agent_response.get('message')}. Puede que el proceso ya no existiera.")
            # No es un error fatal si el proceso ya no existía, pero lo registramos
    except requests.exceptions.RequestException as e:
        print(f"Error al contactar agente para detener en change_vlc_video: {e}")
        return jsonify({"error": "Fallo al contactar agente para detener proceso existente", "details": str(e)}), 502

    # 3. Iniciar un nuevo proceso con la nueva ruta de video a través del agente
    agent_start_endpoint = f"{MININET_AGENT_URL}/mininet/start_ffmpeg"
    start_payload = {
        "host": host,
        "video_path": new_video_path,
        "ip_destino": ip_destino,
        "puerto": puerto
    }
    try:
        start_response = requests.post(agent_start_endpoint, json=start_payload, timeout=20)
        start_response.raise_for_status()
        start_agent_response = start_response.json()

        if not start_agent_response.get("success"):
            return jsonify({"error": start_agent_response.get("message", "Fallo al reiniciar en el agente"), "details": start_agent_response.get("details")}), 500

        # 4. Actualizar la base de datos con la nueva ruta y el nuevo PID
        conn = None
        cur = None
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cur = conn.cursor()
            cur.execute("""
                UPDATE servidores_vlc_activos
                SET video_path = %s, status = 'activo', process_pid = %s, last_updated = NOW()
                WHERE host_name = %s;
            """, (new_video_path, start_agent_response.get("ffmpeg_pid"), host))
            conn.commit()
            print(f"Ruta de video para {host} actualizada en DB a {new_video_path}.")
            # Actualizar caché local
            video_processes[host] = {
                "video_path": new_video_path,
                "ip_destino": ip_destino,
                "puerto": puerto,
                "status": "activo",
                "ffmpeg_pid": start_agent_response.get("ffmpeg_pid")
            }
        except psycopg2.Error as db_err:
            print(f"Error DB al actualizar ruta de video para {host}: {db_err}")
            return jsonify({"error": "Video cambiado, pero fallo al actualizar DB", "details": str(db_err)}), 500
        finally:
            if cur: cur.close()
            if conn: cur.close()

        return jsonify({
            "success": True,
            "message": f"Ruta de video cambiada para {host} a {new_video_path}. Nuevo proceso iniciado (vía agente) con PID {start_agent_response.get('ffmpeg_pid')}."
        })

    except requests.exceptions.RequestException as e:
        print(f"Error al contactar agente para iniciar en change_vlc_video: {e}")
        return jsonify({"error": "Fallo al contactar agente para iniciar nuevo proceso", "details": str(e)}), 502
    except Exception as e:
        print(f"Fallo inesperado en change_vlc_video_route: {e}")
        return jsonify({"error": "Fallo inesperado", "details": str(e)}), 500


@servers_bp.route('/api/active_vlc_servers', methods=['GET'])
def get_active_vlc_servers():
    """
    Retorna la lista de todos los hosts que están marcados como 'es_servidor = TRUE'
    en la tabla 'hosts', junto con los detalles de transmisión de 'servidores_vlc_activos'
    si existen.
    """
    query = """
        SELECT
            h.nombre AS host,
            sva.ip_destino,
            sva.puerto,
            sva.status,
            sva.video_path AS video
        FROM hosts h
        LEFT JOIN servidores_vlc_activos sva ON h.nombre = sva.host_name
        WHERE h.es_servidor = TRUE
        ORDER BY h.nombre;
    """
    data = fetch_all(query)
    return jsonify(data), 200


# --- Rutas existentes que interactúan con la tabla 'hosts' ---
# Estas rutas se mantienen ya que gestionan el rol 'es_servidor' en la tabla 'hosts'
# que es independiente de la tabla 'servidores_vlc_activos' que gestiona ffmpeg.

@servers_bp.route('/hosts/asignar-servidor', methods=['PUT'])
def asignar_servidores():
    data = request.get_json()
    nombres = data.get("nombres")

    if not nombres or not isinstance(nombres, list):
        return jsonify({"error": "Debe enviar una lista de nombres"}), 400

    query = "UPDATE hosts SET es_servidor = TRUE, activo = TRUE WHERE nombre = ANY(%s);"
    ok = execute_query(query, (nombres,))

    return jsonify({"message": "Hosts actualizados como servidores" if ok else "Error"}), 200 if ok else 500

@servers_bp.route('/hosts/no-servidores', methods=['GET'])
def listar_no_servidores():
    query = """
        SELECT nombre FROM hosts
        WHERE es_servidor = FALSE OR es_servidor IS NULL
        ORDER BY 
            CAST(split_part(nombre, '_', 1)::TEXT AS TEXT), 
            CAST(split_part(nombre, '_', 2)::INT AS INT);
    """
    data = fetch_all(query)
    return jsonify(data), 200

@servers_bp.route('/active_servers', methods=['GET'])
def listar_servidores_hosts_table():
    """
    Este endpoint lista los hosts marcados como 'es_servidor=TRUE' en la tabla 'hosts'.
    Es diferente de /api/active_vlc_servers que lista los procesos ffmpeg activos.
    """
    query = """
        SELECT nombre, activo FROM hosts
        WHERE es_servidor = TRUE
        ORDER BY nombre;
    """
    data = fetch_all(query)
    return jsonify(data), 200

@servers_bp.route('/active_servers/<nombre>', methods=['PUT'])
def actualizar_servidor_hosts_table(nombre):
    """
    Actualiza el estado 'activo' de un servidor en la tabla 'hosts'.
    """
    data = request.get_json()
    activo = data.get("activo")

    if activo is None:
        return jsonify({"error": "Falta parámetro 'activo'"}), 400

    query = "UPDATE hosts SET activo = %s WHERE nombre = %s;"
    params = (activo, nombre)

    ok = execute_query(query, params)

    return jsonify({"message": "Servidor actualizado" if ok else "Error"}), 200 if ok else 500

@servers_bp.route('/hosts/remover-servidor/<nombre>', methods=['PUT'])
def remover_servidor_hosts_table(nombre):
    try:
        query_hosts = "UPDATE hosts SET es_servidor = FALSE, activo = FALSE WHERE nombre = %s;"
        ok_hosts = execute_query(query_hosts, (nombre,))
        print(f"Host '{nombre}' marcado como es_servidor=FALSE y activo=FALSE en la tabla 'hosts'.")

        query_vlc = "DELETE FROM servidores_vlc_activos WHERE host_name = %s;"
        ok_vlc = execute_query(query_vlc, (nombre,))
        print(f"Entrada para {nombre} eliminada de 'servidores_vlc_activos'.")

        try:
            response_agent = requests.post(f"{MININET_AGENT_URL}/mininet/stop_ffmpeg", json={"host": nombre})
            if response_agent.ok:
                agent_response = response_agent.json()
                if agent_response.get("success"):
                    print(f"Proceso VLC en el agente para {nombre} detenido exitosamente.")
                else:
                    print(f"Advertencia: Agente reportó fallo al detener proceso VLC en {nombre}: {agent_response.get('message')}. Detalles: {agent_response.get('details')}")
            else:
                print(f"Advertencia: No se pudo conectar/detener el proceso VLC en el agente para {nombre}. Estado: {response_agent.status_code}, Respuesta: {response_agent.text}")
        except requests.exceptions.RequestException as e:
            print(f"Error de conexión con el agente de Mininet para detener VLC en {nombre}: {e}")
        except Exception as e:
            print(f"Error inesperado al detener VLC en el agente para {nombre}: {e}")

        if ok_hosts and ok_vlc:
            if nombre in video_processes:
                del video_processes[nombre]
            return jsonify({"message": "Servidor eliminado del rol y de la lista de VLC activos."}), 200
        else:
            return jsonify({"error": "No se pudo eliminar el rol de servidor o la entrada de VLC activo. Puede que el host no existiera o ya no tuviera el rol."}), 500

    except Exception as e:
        print(f"Error en remover_servidor_hosts_table: {e}")
        return jsonify({"error": "Error interno del servidor: " + str(e)}), 500
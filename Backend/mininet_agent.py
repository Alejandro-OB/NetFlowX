import subprocess
import re
import os
import atexit
import signal
import time
import sys
from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2 # Importar psycopg2

app = Flask(__name__)
CORS(app)

# Diccionario para almacenar los procesos de video (FFmpeg) activos en el agente (para servidores)
# Formato: { "h1_1": {"pid": ffmpeg_pid, "host_pid": mininet_host_pid_on_agent_machine, "server_ip": "10.0.0.1"} }
ffmpeg_server_processes = {}

# Diccionario para almacenar los procesos de FFplay (cliente) activos en el agente
# Formato: { "h1_1": {"pid": ffplay_client_pid, "host_pid": mininet_host_pid_on_agent_machine} }
ffplay_client_processes = {}

# Configuración de la base de datos
DB_NAME = os.environ.get('DB_NAME', 'geant_network')
DB_USER = os.environ.get('DB_USER', 'geant_user') # Asegúrate de que este usuario tenga permisos para SELECT en 'hosts'
DB_PASSWORD = os.environ.get('DB_PASSWORD', 'geant') # Reemplaza con tu contraseña real
DB_HOST = os.environ.get('DB_HOST', '192.168.18.151') # O la IP donde se ejecuta tu base de datos
DB_PORT = os.environ.get('DB_PORT', '5432')

def get_db_connection():
    """Establece y devuelve una conexión a la base de datos PostgreSQL."""
    try:
        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        return conn
    except Exception as e:
        print(f"Agente: Error conectando a la base de datos: {e}")
        return None

def get_host_ip_from_db(hostname):
    """
    Obtiene la dirección IPv4 de un host desde la base de datos.
    """
    conn = None
    try:
        conn = get_db_connection()
        if not conn:
            return None
        cursor = conn.cursor()
        cursor.execute("SELECT ipv4 FROM hosts WHERE nombre = %s", (hostname,))
        result = cursor.fetchone()
        if result:
            return result[0]
        return None
    except Exception as e:
        print(f"Agente: Error al consultar IP de {hostname} en la DB: {e}")
        return None
    finally:
        if conn:
            conn.close()


def get_host_pid(hostname):
    """
    Obtiene el PID del proceso de Mininet asociado a un hostname específico.
    Este PID es el del proceso 'mnexec' que ejecuta el shell del host.
    """
    try:
        result = subprocess.run(['pgrep', '-f', f'mininet:{hostname}'], capture_output=True, text=True, check=True)
        pid = result.stdout.strip().split('\n')[0]
        return int(pid)
    except Exception as e:
        print(f"Agente: Error obteniendo PID para '{hostname}': {e}")
        return None

def kill_media_processes_on_host(hostname, host_pid, process_type="any", specific_pid=None):
    """
    Mata procesos FFmpeg, FFplay o python3 -m http.server dentro del contexto de un host Mininet.
    Si se proporciona un PID específico, mata solo ese PID. Si no, elimina todos los procesos del tipo.
    """
    if not host_pid:
        print(f"[WARN] No se proporcionó host_pid para {hostname}")
        return

    try:
        # Si se especifica un PID, intenta matarlo directamente
        if specific_pid:
            subprocess.run(['mnexec', '-a', str(host_pid), 'kill', '-9', str(specific_pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"[OK] Proceso PID {specific_pid} ({process_type}) detenido en {hostname}")
            return

        # Seleccionar patrón de proceso
        patrones = {
            "server": ['ffmpeg', 'http.server', 'python3 -m http.server'],
            "client": ['ffplay'],
            "any": ['ffmpeg', 'ffplay', 'http.server', 'python3 -m http.server']
        }

        patrones_a_buscar = patrones.get(process_type, patrones["any"])

        for patron in patrones_a_buscar:
            result = subprocess.run(
                ['mnexec', '-a', str(host_pid), 'pgrep', '-f', patron],
                capture_output=True, text=True
            )
            pids = [pid for pid in result.stdout.strip().split('\n') if pid.isdigit()]

            if not pids:
                print(f"[INFO] No se encontraron procesos '{patron}' en {hostname}")
                continue

            for pid in pids:
                subprocess.run(['mnexec', '-a', str(host_pid), 'kill', '-9', pid],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print(f"[OK] Proceso {patron} (PID: {pid}) eliminado en {hostname}")

    except Exception as e:
        print(f"[ERROR] Error eliminando procesos en {hostname}: {e}")



def cleanup_agent_processes():
    """
    Función de limpieza que se ejecuta al cerrar el agente.
    Mata todos los procesos FFmpeg (servidor) y FFplay (cliente) iniciados por el agente.
    """
    print("Agente: Realizando limpieza de procesos activos (FFmpeg servidor y FFplay cliente)...")
    for host, info in list(ffmpeg_server_processes.items()):
        kill_media_processes_on_host(host, info.get("host_pid"), "server")
        del ffmpeg_server_processes[host]
    
    for host, info in list(ffplay_client_processes.items()):
        kill_media_processes_on_host(host, info.get("host_pid"), "client")
        del ffplay_client_processes[host]
    print("Agente: Limpieza completada.")

atexit.register(cleanup_agent_processes)

def signal_handler(signum, frame):
    print(f"Agente: Señal {signum} recibida. Iniciando limpieza y saliendo.")
    cleanup_agent_processes()
    sys.exit(0)

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)




@app.route('/mininet/start_http_server', methods=['POST'])
def start_http_server_on_host():
    """
    Inicia un servidor HTTP (python3 -m http.server) en un host de Mininet.
    Espera JSON con: host (el host que será el servidor), puerto.
    """
    data = request.get_json()
    host = data.get('host')
    puerto = data.get('puerto')

    if not all([host, puerto]):
        return jsonify({"error": "Faltan parámetros: host, puerto"}), 400
    
    if not re.match(r'^[a-zA-Z0-9_-]+$', host):
        return jsonify({"error": "Parámetro 'host' inválido"}), 400

    try:
        puerto = int(puerto)
        if not (1024 <= puerto <= 65535):
            raise ValueError
    except ValueError:
        return jsonify({"error": "Parámetro 'puerto' inválido"}), 400

    # Obtener IP desde la base de datos solo por información (no se usa en este caso)
    server_ip = get_host_ip_from_db(host)
    if not server_ip:
        return jsonify({"error": f"No se pudo obtener la IP del host '{host}' desde la base de datos."}), 500

    # Si ya hay un proceso activo, lo detenemos
    if host in ffmpeg_server_processes:
        kill_media_processes_on_host(host, ffmpeg_server_processes[host].get("host_pid"), "server")
        del ffmpeg_server_processes[host]

    pid_host = get_host_pid(host)
    if not pid_host:
        return jsonify({"error": f"No se pudo encontrar el PID del host de Mininet: {host}"}), 500

    try:
        # Iniciar el servidor HTTP con python3 -m http.server
        process = subprocess.Popen(
            ['mnexec', '-a', str(pid_host), 'python3', '-m', 'http.server', str(puerto)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid
        )
        ffmpeg_server_processes[host] = {"pid": process.pid, "host_pid": pid_host, "server_ip": server_ip}
        print(f"Agente: Servidor HTTP iniciado en {host} (IP: {server_ip}) en puerto {puerto}. PID: {process.pid}")
        return jsonify({"success": True, "message": f"Servidor HTTP iniciado en {server_ip}:{puerto}", "pid": process.pid, "server_ip": server_ip}), 200
    except Exception as e:
        print(f"Agente: Error al iniciar servidor HTTP en {host}: {e}")
        return jsonify({"error": f"Error al iniciar servidor HTTP: {e}"}), 500

@app.route('/mininet/stop_http_server', methods=['POST'])
def stop_http_server_on_host():
    """
    Detiene el proceso de servidor HTTP (python3 -m http.server) que se esté ejecutando en un host de Mininet.
    Espera JSON con: host.
    """
    data = request.get_json()
    host = data.get('host')

    if not host or not re.match(r'^[a-zA-Z0-9_-]+$', host):
        return jsonify({"error": "Parámetro 'host' inválido"}), 400

    pid_host = None
    if host in ffmpeg_server_processes:
        pid_host = ffmpeg_server_processes[host].get("host_pid")

    if not pid_host:
        pid_host = get_host_pid(host)

    if not pid_host:
        return jsonify({"error": f"No se encontró el PID del host '{host}'"}), 500

    # Detener proceso http.server en ese host
    try:
        kill_media_processes_on_host(host, pid_host, process_type="server")
        if host in ffmpeg_server_processes:
            del ffmpeg_server_processes[host]
        print(f"Agente: Servidor HTTP detenido y registro eliminado para {host}.")
        return jsonify({"success": True, "message": f"Servidor HTTP detenido en {host}"}), 200
    except Exception as e:
        print(f"Agente: Error al detener el servidor HTTP en {host}: {e}")
        return jsonify({"error": f"Error al detener servidor HTTP: {e}"}), 500




@app.route('/mininet/start_http_client', methods=['POST'])
def start_http_client_on_host():
    """
    Inicia un cliente FFplay en un host de Mininet para reproducir un video vía HTTP.
    Espera JSON con: host (cliente), video_file (nombre del archivo).
    El servidor siempre será 10.0.0.100 y el puerto 8080 (VIP HTTP).
    """
    data = request.get_json()
    host = data.get('host')
    video_file = data.get('video_file')

    # Validaciones básicas
    if not host or not video_file:
        return jsonify({"error": "Faltan parámetros: host o video_file"}), 400

    if not re.match(r'^[a-zA-Z0-9._/-]+$', video_file):
        return jsonify({"error": "Nombre de archivo inválido"}), 400

    pid_host = get_host_pid(host)
    if not pid_host:
        return jsonify({"error": f"No se pudo encontrar el PID del host Mininet: {host}"}), 500

    # IP virtual y puerto fijo
    server_ip = "10.0.0.100"
    puerto = 8080

    try:
        url = f"http://{server_ip}:{puerto}/{video_file}"
        process = subprocess.Popen(
            ['mnexec', '-a', str(pid_host), 'ffplay', '-autoexit', '-loglevel', 'quiet', url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid
        )
        ffplay_client_processes[host] = {"pid": process.pid, "host_pid": pid_host}
        print(f"Agente: Cliente FFplay iniciado en {host} accediendo a {url}. PID: {process.pid}")
        return jsonify({
            "success": True,
            "message": f"Cliente FFplay accediendo a {url}",
            "ffplay_client_pid": process.pid
        }), 200
    except Exception as e:
        print(f"Agente: Error al iniciar ffplay en {host}: {e}")
        return jsonify({"error": f"Error al iniciar cliente FFplay: {e}"}), 500

@app.route('/mininet/stop_http_client', methods=['POST'])
def stop_http_client_on_host():
    """
    Detiene el cliente FFplay que esté activo en un host Mininet.
    Espera JSON con: host.
    """
    data = request.get_json()
    host = data.get('host')

    if not host or host not in ffplay_client_processes:
        return jsonify({"message": "No se encontró cliente FFplay activo para este host."}), 404

    pid = ffplay_client_processes[host].get("pid")
    host_pid = ffplay_client_processes[host].get("host_pid")

    if pid and host_pid:
        kill_media_processes_on_host(host, host_pid, "client", specific_pid=pid)
        del ffplay_client_processes[host]
        return jsonify({"success": True, "message": f"Cliente FFplay detenido en {host}"}), 200
    else:
        return jsonify({"error": "PID o contexto del cliente incompleto para detenerlo."}), 500


if __name__ == '__main__':
    print("Agente: Intentando iniciar el servidor Flask...")
    app.run(host='0.0.0.0', port=5002, debug=True)
    print("Agente: Servidor Flask detenido.")
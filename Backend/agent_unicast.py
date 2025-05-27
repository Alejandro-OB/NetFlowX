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
DB_USER = os.environ.get('DB_USER', 'mininet_user') # Asegúrate de que este usuario tenga permisos para SELECT en 'hosts'
DB_PASSWORD = os.environ.get('DB_PASSWORD', 'mininet_password') # Reemplaza con tu contraseña real
DB_HOST = os.environ.get('DB_HOST', 'localhost') # O la IP donde se ejecuta tu base de datos
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
    Mata procesos de FFmpeg o FFplay que se estén ejecutando dentro del contexto
    de un host de Mininet específico.
    Si se proporciona specific_pid, mata solo ese PID. De lo contrario, mata todos los de ese tipo.
    'process_type' puede ser "server" (ffmpeg), "client" (ffplay) o "any".
    """
    if not host_pid:
        return
    
    if specific_pid:
        try:
            subprocess.run(['mnexec', '-a', str(host_pid), 'kill', '-9', str(specific_pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"Agente: Proceso PID {specific_pid} ({process_type}) limpiado en {hostname}.")
        except Exception as e:
            print(f"Agente: Error al limpiar proceso PID {specific_pid} ({process_type}) en {hostname}: {e}")
    else:
        try:
            process_name = 'ffmpeg'
            if process_type == "client":
                process_name = 'ffplay'
            
            result = subprocess.run(['mnexec', '-a', str(host_pid), 'pgrep', '-f', process_name], capture_output=True, text=True)
            pids = [p for p in result.stdout.strip().split('\n') if p.isdigit()]
            for pid in pids:
                subprocess.run(['mnexec', '-a', str(host_pid), 'kill', '-9', pid], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"Agente: {process_name.capitalize()} ({process_type}) limpiado en {hostname}.")
        except Exception as e:
            print(f"Agente: Error al limpiar {process_name.capitalize()} ({process_type}) en {hostname}: {e}")


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


@app.route('/mininet/start_ffmpeg_server', methods=['POST'])
def start_ffmpeg_server_on_host():
    """
    Inicia una transmisión de video usando FFmpeg en un host de Mininet (lado del servidor).
    El servidor transmitirá a su propia IP, obtenida de la base de datos.
    Espera JSON con: host (el host que será el servidor), video_path, puerto.
    """
    data = request.get_json()
    host = data.get('host') # El host que será el servidor de FFmpeg
    video_path = data.get('video_path')
    puerto = data.get('puerto')

    if not all([host, video_path, puerto]):
        return jsonify({"error": "Faltan parámetros: host, video_path, puerto"}), 400
    
    # Validaciones básicas
    if not re.match(r'^[a-zA-Z0-9_-]+$', host):
        return jsonify({"error": "Parámetro 'host' inválido"}), 400
    try:
        puerto = int(puerto)
        if not (1024 <= puerto <= 65535):
            raise ValueError
    except ValueError:
        return jsonify({"error": "Parámetro 'puerto' inválido"}), 400

    # *** NUEVA LÓGICA: Obtener la IP del propio host desde la base de datos ***
    server_ip = get_host_ip_from_db(host)
    if not server_ip:
        return jsonify({"error": f"No se pudo obtener la IP del host '{host}' desde la base de datos."}), 500
    
    # Si ya hay un proceso de FFmpeg de servidor para este host, lo matamos primero
    if host in ffmpeg_server_processes:
        kill_media_processes_on_host(host, ffmpeg_server_processes[host].get("host_pid"), "server")
        del ffmpeg_server_processes[host]

    pid_host = get_host_pid(host)
    if not pid_host:
        return jsonify({"error": f"No se pudo encontrar el PID del host de Mininet: {host}"}), 500

    try:
        # Comando FFmpeg para transmitir un video en bucle a la IP propia del servidor
        process = subprocess.Popen(
            ['mnexec', '-a', str(pid_host), 'ffmpeg',
             '-stream_loop', '-1', # Bucle infinito
             '-re', # Leer a velocidad nativa de fotogramas
             '-i', video_path,
             '-f', 'mpegts', f'udp://{server_ip}:{puerto}', # Ahora usa la IP del propio servidor
             '-loglevel', 'quiet'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid
        )
        ffmpeg_server_processes[host] = {"pid": process.pid, "host_pid": pid_host, "server_ip": server_ip}
        print(f"Agente: Transmisión FFmpeg iniciada para {host} (IP: {server_ip}) en puerto {puerto}. PID: {process.pid}")
        return jsonify({"success": True, "message": f"Transmisión FFmpeg iniciada en {server_ip}:{puerto}", "ffmpeg_pid": process.pid, "server_ip": server_ip}), 200
    except Exception as e:
        print(f"Agente: Error al iniciar ffmpeg en {host}: {e}")
        return jsonify({"error": f"Error al iniciar ffmpeg: {e}"}), 500

@app.route('/mininet/stop_ffmpeg_server', methods=['POST'])
def stop_ffmpeg_server_on_host():
    """
    Detiene el proceso FFmpeg que se esté ejecutando en un host de Mininet (lado del servidor).
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

    if pid_host:
        kill_media_processes_on_host(host, pid_host, "server")

    if host in ffmpeg_server_processes:
        del ffmpeg_server_processes[host]
        print(f"Agente: FFmpeg servidor detenido y registro eliminado para {host}.")
    else:
        print(f"Agente: No se encontró proceso FFmpeg de servidor activo para {host} en el registro.")

    return jsonify({"success": True, "message": f"FFmpeg servidor detenido en {host}"}), 200

# --- Rutas para el cliente FFplay (actualizadas para conectarse a la IP del servidor) ---

@app.route('/mininet/start_ffmpeg_client', methods=['POST'])
def start_ffmpeg_client_on_host():
    """
    Inicia un cliente FFplay en un host de Mininet para recibir y reproducir un stream unicast.
    Espera JSON con: host (el cliente), server_host_name (el nombre del host servidor que envía el stream), puerto.
    """
    data = request.get_json()
    host = data.get('host') # El host que será el cliente de FFplay
    server_host_name = data.get('server_host_name') # El nombre del host servidor
    puerto = data.get('puerto')

    if not all([host, server_host_name, puerto]):
        return jsonify({"error": "Faltan parámetros: host, server_host_name, puerto"}), 400
    
    # Validaciones básicas
    if not re.match(r'^[a-zA-Z0-9_-]+$', host):
        return jsonify({"error": "Parámetro 'host' inválido"}), 400
    if not re.match(r'^[a-zA-Z0-9_-]+$', server_host_name):
        return jsonify({"error": "Parámetro 'server_host_name' inválido"}), 400

    try:
        puerto = int(puerto)
        if not (1024 <= puerto <= 65535):
            raise ValueError
    except ValueError:
        return jsonify({"error": "Parámetro 'puerto' inválido"}), 400

    # *** NUEVA LÓGICA: Obtener la IP del host servidor desde la base de datos ***
    server_ip = get_host_ip_from_db(server_host_name)
    if not server_ip:
        return jsonify({"error": f"No se pudo obtener la IP del host servidor '{server_host_name}' desde la base de datos."}), 500

    # Si ya hay un proceso de FFplay cliente para este host, lo matamos primero
    if host in ffplay_client_processes:
        kill_media_processes_on_host(host, ffplay_client_processes[host].get("host_pid"), "client", specific_pid=ffplay_client_processes[host].get("pid"))
        del ffplay_client_processes[host]

    pid_host = get_host_pid(host)
    if not pid_host:
        return jsonify({"error": f"No se pudo encontrar el PID del host de Mininet: {host}"}), 500

    try:
        # Comando FFplay para recibir un stream UDP unicast y reproducirlo
        process = subprocess.Popen(
            ['mnexec', '-a', str(pid_host), 'ffplay',
             f'udp://{server_ip}:{puerto}'], # Conecta a la IP específica del servidor
            stdout=None,
            stderr=None,
            preexec_fn=os.setsid
        )
        ffplay_client_processes[host] = {"pid": process.pid, "host_pid": pid_host}
        print(f"Agente: Cliente FFplay iniciado en {host} conectando a {server_ip}:{puerto}. PID: {process.pid}")
        return jsonify({"success": True, "message": f"FFplay cliente iniciado en {host} conectando a {server_ip}:{puerto}", "ffplay_client_pid": process.pid}), 200
    except Exception as e:
        print(f"Agente: Error al iniciar FFplay cliente en {host}: {e}")
        return jsonify({"error": f"Error al iniciar FFplay cliente: {e}"}), 500

@app.route('/mininet/stop_ffmpeg_client', methods=['POST'])
def stop_ffmpeg_client_on_host():
    """
    Detiene el proceso FFplay (cliente) que se esté ejecutando en un host de Mininet.
    Espera JSON con: host.
    """
    data = request.get_json()
    host = data.get('host')

    if not host or not re.match(r'^[a-zA-Z0-9_-]+$', host):
        return jsonify({"error": "Parámetro 'host' inválido"}), 400

    if host not in ffplay_client_processes:
        print(f"Agente: No se encontró proceso FFplay cliente activo para {host} en el registro. Intentando limpieza general.")
        pid_host = get_host_pid(host)
        if pid_host:
            kill_media_processes_on_host(host, pid_host, "client")
        return jsonify({"success": True, "message": f"No se encontró FFplay cliente activo para {host} en el registro, se intentó detener cualquier proceso."}), 200

    specific_ffplay_pid = ffplay_client_processes[host].get("pid")
    host_pid_for_client = ffplay_client_processes[host].get("host_pid")

    if specific_ffplay_pid and host_pid_for_client:
        kill_media_processes_on_host(host, host_pid_for_client, "client", specific_pid=specific_ffplay_pid)
        del ffplay_client_processes[host]
        print(f"Agente: FFplay cliente PID {specific_ffplay_pid} detenido y registro eliminado para {host}.")
        return jsonify({"success": True, "message": f"FFplay cliente detenido en {host}"}), 200
    else:
        print(f"Agente: Información incompleta para detener FFplay cliente para {host}.")
        return jsonify({"error": f"Información incompleta para detener FFplay cliente para {host}."}), 500

if __name__ == '__main__':
    print("Agente: Intentando iniciar el servidor Flask...")
    app.run(host='0.0.0.0', port=5002, debug=True)
    print("Agente: Servidor Flask detenido.")
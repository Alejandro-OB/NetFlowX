import subprocess
import re
import os
import atexit
import signal
import time
import sys
from flask import Flask, request, jsonify
from flask_cors import CORS # Importar CORS

app = Flask(__name__)
CORS(app) # Habilitar CORS para toda la aplicación Flask del agente

# Diccionario para almacenar los procesos de video (FFmpeg) activos en el agente (para servidores)
# Formato: { "h1_1": {"pid": ffmpeg_pid, "host_pid": mininet_host_pid_on_agent_machine} }
ffmpeg_server_processes = {}

# Diccionario para almacenar los procesos de FFplay (cliente) activos en el agente
# Formato: { "h1_1": {"pid": ffplay_client_pid, "host_pid": mininet_host_pid_on_agent_machine} }
ffplay_client_processes = {}


def get_host_pid(hostname):
    """
    Obtiene el PID del proceso de Mininet asociado a un hostname específico.
    Este PID es el del proceso 'mnexec' que ejecuta el shell del host.
    """
    try:
        # Busca el PID del proceso 'mininet:<hostname>'
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
        # Matar un PID específico
        try:
            subprocess.run(['mnexec', '-a', str(host_pid), 'kill', '-9', str(specific_pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"Agente: Proceso PID {specific_pid} ({process_type}) limpiado en {hostname}.")
        except Exception as e:
            print(f"Agente: Error al limpiar proceso PID {specific_pid} ({process_type}) en {hostname}: {e}")
    else:
        # Matar todos los procesos de un tipo (comportamiento anterior para limpieza general)
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
        # Aquí se usa el comportamiento de matar todos los procesos de ese tipo
        kill_media_processes_on_host(host, info.get("host_pid"), "server")
        del ffmpeg_server_processes[host]
    
    for host, info in list(ffplay_client_processes.items()):
        # Aquí se usa el comportamiento de matar todos los procesos de ese tipo
        kill_media_processes_on_host(host, info.get("host_pid"), "client")
        del ffplay_client_processes[host]
    print("Agente: Limpieza completada.")

# Registrar la función de limpieza para que se ejecute al salir de la aplicación
atexit.register(cleanup_agent_processes)

# Manejar señales de terminación para asegurar la limpieza
def signal_handler(signum, frame):
    print(f"Agente: Señal {signum} recibida. Iniciando limpieza y saliendo.")
    cleanup_agent_processes()
    sys.exit(0)

# Registrar manejadores de señales para SIGTERM y SIGINT (Ctrl+C)
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


@app.route('/mininet/start_ffmpeg_server', methods=['POST'])
def start_ffmpeg_server_on_host():
    """
    Inicia una transmisión de video usando FFmpeg en un host de Mininet (lado del servidor).
    Espera JSON con: host, video_path, ip_multicast, puerto.
    """
    data = request.get_json()
    host = data.get('host')
    video_path = data.get('video_path')
    ip_multicast = data.get('ip_multicast')
    puerto = data.get('puerto')

    if not all([host, video_path, ip_multicast, puerto]):
        return jsonify({"error": "Faltan parámetros: host, video_path, ip_multicast, puerto"}), 400
    
    # Validaciones básicas
    if not re.match(r'^[a-zA-Z0-9_-]+$', host):
        return jsonify({"error": "Parámetro 'host' inválido"}), 400
    if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', ip_multicast):
        return jsonify({"error": "Parámetro 'ip_multicast' inválido"}), 400
    try:
        puerto = int(puerto)
        if not (1024 <= puerto <= 65535):
            raise ValueError
    except ValueError:
        return jsonify({"error": "Parámetro 'puerto' inválido"}), 400

    # Si ya hay un proceso de FFmpeg de servidor para este host, lo matamos primero
    if host in ffmpeg_server_processes:
        kill_media_processes_on_host(host, ffmpeg_server_processes[host].get("host_pid"), "server")
        del ffmpeg_server_processes[host]

    pid_host = get_host_pid(host)
    if not pid_host:
        return jsonify({"error": f"No se pudo encontrar el PID del host de Mininet: {host}"}), 500

    try:
        # Comando FFmpeg para transmitir un video en bucle a una dirección multicast UDP
        process = subprocess.Popen(
            ['mnexec', '-a', str(pid_host), 'ffmpeg',
             '-stream_loop', '-1', # Bucle infinito
             '-re', # Leer a velocidad nativa de fotogramas
             '-i', video_path,
             '-f', 'mpegts', f'udp://{ip_multicast}:{puerto}?ttl=1',
             '-loglevel', 'quiet'],
            stdout=subprocess.DEVNULL, # Redirigir stdout a /dev/null
            stderr=subprocess.DEVNULL, # Redirigir stderr a /dev/null
            preexec_fn=os.setsid # Desvincular el proceso hijo del padre
        )
        ffmpeg_server_processes[host] = {"pid": process.pid, "host_pid": pid_host}
        print(f"Agente: Transmisión FFmpeg iniciada para {host} a {ip_multicast}:{puerto}. PID: {process.pid}")
        return jsonify({"success": True, "message": f"Transmisión FFmpeg iniciada a {ip_multicast}:{puerto}", "ffmpeg_pid": process.pid}), 200
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

# --- Nuevas rutas para el cliente FFplay ---

@app.route('/mininet/start_ffmpeg_client', methods=['POST'])
def start_ffmpeg_client_on_host(): # Mantengo el nombre de la ruta para compatibilidad con clients.js
    """
    Inicia un cliente FFplay en un host de Mininet para recibir y reproducir un stream multicast.
    Espera JSON con: host, multicast_ip, puerto.
    """
    data = request.get_json()
    host = data.get('host')
    multicast_ip = data.get('multicast_ip')
    puerto = data.get('puerto')

    if not all([host, multicast_ip, puerto]):
        return jsonify({"error": "Faltan parámetros: host, multicast_ip, puerto"}), 400
    
    # Validaciones básicas
    if not re.match(r'^[a-zA-Z0-9_-]+$', host):
        return jsonify({"error": "Parámetro 'host' inválido"}), 400
    if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', multicast_ip):
        return jsonify({"error": "Parámetro 'multicast_ip' inválido"}), 400
    try:
        puerto = int(puerto)
        if not (1024 <= puerto <= 65535):
            raise ValueError
    except ValueError:
        return jsonify({"error": "Parámetro 'puerto' inválido"}), 400

    # Si ya hay un proceso de FFplay cliente para este host, lo matamos primero
    if host in ffplay_client_processes:
        # Aquí matamos el proceso específico que ya estaba registrado para este host
        kill_media_processes_on_host(host, ffplay_client_processes[host].get("host_pid"), "client", specific_pid=ffplay_client_processes[host].get("pid"))
        del ffplay_client_processes[host]

    pid_host = get_host_pid(host)
    if not pid_host:
        return jsonify({"error": f"No se pudo encontrar el PID del host de Mininet: {host}"}), 500

    try:
        # Comando FFplay para recibir un stream multicast UDP y reproducirlo
        process = subprocess.Popen(
            ['mnexec', '-a', str(pid_host), 'ffplay',
             f'udp://@{multicast_ip}:{puerto}'],
            stdout=None, # IMPORTANTE para depurar: Ver la salida de ffplay
            stderr=None, # IMPORTANTE para depurar: Ver la salida de ffplay
            preexec_fn=os.setsid # Desvincular el proceso hijo del padre
        )
        ffplay_client_processes[host] = {"pid": process.pid, "host_pid": pid_host}
        print(f"Agente: Cliente FFplay iniciado en {host} para {multicast_ip}:{puerto}. PID: {process.pid}")
        return jsonify({"success": True, "message": f"FFplay cliente iniciado en {host} para {multicast_ip}:{puerto}", "ffplay_client_pid": process.pid}), 200
    except Exception as e:
        print(f"Agente: Error al iniciar FFplay cliente en {host}: {e}")
        return jsonify({"error": f"Error al iniciar FFplay cliente: {e}"}), 500

@app.route('/mininet/stop_ffmpeg_client', methods=['POST']) # Mantengo el nombre de la ruta para compatibilidad con clients.js
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
        # Si no está en nuestro registro, intentamos una limpieza general por si acaso
        pid_host = get_host_pid(host)
        if pid_host:
            kill_media_processes_on_host(host, pid_host, "client")
        return jsonify({"success": True, "message": f"No se encontró FFplay cliente activo para {host} en el registro, se intentó detener cualquier proceso."}), 200


    # Obtener el PID específico del proceso FFplay que iniciamos para este host
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

@app.route('/mininet/ping_between_hosts', methods=['POST'])
def ping_between_hosts():
    from flask import Response
    import threading

    data = request.get_json()
    origen = data.get('origen')
    destino = data.get('destino')

    if not origen or not destino:
        return jsonify({"error": "Faltan parámetros: origen y destino"}), 400

    pid_origen = get_host_pid(origen)
    if not pid_origen:
        return jsonify({"error": f"No se encontró PID para {origen}"}), 500

    def generate():
        try:
            cmd = ['mnexec', '-a', str(pid_origen), 'ping', '-c', '3', destino]
            print(f"[DEBUG] Ejecutando: {' '.join(cmd)}")
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

            for line in iter(process.stdout.readline, ''):
                yield f"data: {line.strip()}\n\n"
                time.sleep(0.2)  # pequeño retraso para dar efecto de consola

            process.stdout.close()
            process.wait()
        except Exception as e:
            yield f"data: ERROR: {str(e)}\n\n"

    return Response(generate(), mimetype='text/event-stream')

@app.route('/mininet/ping_between_hosts_stream')
def ping_between_hosts_stream():
    from flask import Response, request

    origen = request.args.get('origen')
    destino = request.args.get('destino')

    if not origen or not destino:
        return Response("data: Faltan parámetros: origen y destino\n\n", mimetype='text/event-stream')

    pid_origen = get_host_pid(origen)
    if not pid_origen:
        return Response(f"data: No se encontró PID para {origen}\n\n", mimetype='text/event-stream')

    def generate():
        try:
            cmd = ['mnexec', '-a', str(pid_origen), 'ping', '-c', '3', destino]
            print(f"[DEBUG] Ejecutando: {' '.join(cmd)}")
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

            for line in iter(process.stdout.readline, ''):
                yield f"data: {line.strip()}\n\n"
                time.sleep(0.2)

            process.stdout.close()
            process.wait()
        except Exception as e:
            yield f"data: ERROR: {str(e)}\n\n"

    return Response(generate(), mimetype='text/event-stream')


if __name__ == '__main__':
    # El agente debe ejecutarse en la máquina donde está Mininet,
    # y debe ser accesible desde la máquina donde corre la aplicación Flask principal.
    # Se recomienda ejecutarlo con un servidor WSGI como Gunicorn en producción.
    print("Agente: Intentando iniciar el servidor Flask...") # Mensaje de depuración
    app.run(host='0.0.0.0', port=5002, debug=True) # debug=True solo para desarrollo
    print("Agente: Servidor Flask detenido.") # Este mensaje solo se verá si app.run() sale

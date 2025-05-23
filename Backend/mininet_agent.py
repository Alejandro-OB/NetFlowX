from flask import Flask, request, jsonify
import subprocess
import re
import os
import atexit
import signal
import time

app = Flask(__name__)

# Diccionario en memoria para guardar PID de ffmpeg por host
video_processes_agent = {} # { "h1_1": {"pid": 12345, "host_pid": 67890} }

# Función para obtener el PID del contenedor del host virtual en Mininet
def get_host_pid(hostname):
    try:
        # Busca el proceso 'mininet:<hostname>' que es el proceso del namespace del host
        result = subprocess.run(['pgrep', '-f', f'mininet:{hostname}'],
                                capture_output=True, text=True, check=True)
        pid = result.stdout.strip().split('\n')[0]
        return int(pid)
    except subprocess.CalledProcessError:
        # Mininet podría no estar corriendo o el host no existe
        return None
    except Exception:
        # Otros errores al obtener el PID
        return None

# Función para limpiar procesos de ffmpeg al cerrar el agente
def cleanup_agent_processes():
    print("Agente: Intentando terminar todos los procesos de video activos...")
    for host, info in list(video_processes_agent.items()):
        ffmpeg_pid = info.get("pid")
        host_pid = info.get("host_pid")

        if ffmpeg_pid and host_pid:
            try:
                # Usa mnexec para matar el proceso ffmpeg dentro del namespace del host
                subprocess.run(['mnexec', '-a', str(host_pid), 'kill', '-9', str(ffmpeg_pid)],
                               timeout=5, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print(f"Agente: Proceso ffmpeg ({ffmpeg_pid}) en {host} terminado.")
            except Exception:
                pass # Ignorar errores durante la limpieza
        
        if host in video_processes_agent:
            del video_processes_agent[host]
    print("Agente: Limpieza de procesos de video completada.")

# Registra la función de limpieza para que se ejecute al salir
atexit.register(cleanup_agent_processes)

# Manejadores de señal para una limpieza más robusta al detener el agente
def signal_handler_agent(signum, frame):
    print(f"Agente: Señal {signum} recibida. Iniciando limpieza...")
    cleanup_agent_processes()
    time.sleep(1) # Dar un pequeño tiempo para que la limpieza termine
    os._exit(0) # Salir del proceso

signal.signal(signal.SIGTERM, signal_handler_agent)
signal.signal(signal.SIGINT, signal_handler_agent)


@app.route('/mininet/start_ffmpeg', methods=['POST'])
def start_ffmpeg_on_host():
    data = request.get_json()

    host = data.get('host')
    video_path = data.get('video_path')
    ip_destino = data.get('ip_destino')
    puerto = data.get('puerto')

    # Validaciones básicas de parámetros
    if not all([host, video_path, ip_destino, puerto]):
        return jsonify({"error": "Faltan parámetros requeridos"}), 400

    if not re.match(r'^[a-zA-Z0-9_-]+$', host):
        return jsonify({"error": "Parámetro 'host' inválido"}), 400

    if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', ip_destino):
        return jsonify({"error": "Parámetro 'ip_destino' inválido"}), 400

    try:
        puerto = int(puerto)
        if not (1024 <= puerto <= 65535):
            raise ValueError("Puerto fuera de rango")
    except ValueError:
        return jsonify({"error": "Parámetro 'puerto' inválido"}), 400

    pid_host = get_host_pid(host)
    if not pid_host:
        return jsonify({"error": f"No se encontró el PID del host '{host}'. Asegúrate de que Mininet esté corriendo y el host exista."}), 404

    # Terminar proceso existente si lo hay
    if host in video_processes_agent and video_processes_agent[host].get("pid") is not None:
        existing_ffmpeg_pid = video_processes_agent[host]["pid"]
        try:
            subprocess.run(['mnexec', '-a', str(pid_host), 'kill', '-9', str(existing_ffmpeg_pid)],
                           check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        except Exception:
            pass # Ignorar errores al intentar matar un proceso que quizás ya no existe
        del video_processes_agent[host]

    # Verificar existencia del archivo de video
    try:
        check_file_cmd = ['mnexec', '-a', str(pid_host), 'test', '-f', video_path]
        check_result = subprocess.run(check_file_cmd, capture_output=True, text=True)
        if check_result.returncode != 0:
            return jsonify({"error": f"El archivo de video '{video_path}' NO existe o no es accesible en el host '{host}'"}), 400
    except Exception as e:
        return jsonify({"error": f"Error al verificar existencia del archivo en {host}: {str(e)}"}), 500

    try:
        # Comando ffmpeg para transmitir video en bucle
        process = subprocess.Popen(
            ['mnexec', '-a', str(pid_host), 'ffmpeg',
             '-stream_loop', '-1', '-re',
             '-i', video_path,
             '-f', 'mpegts', f'udp://{ip_destino}:{puerto}'],
            stdout=subprocess.DEVNULL, # Redirigir stdout a /dev/null
            stderr=subprocess.DEVNULL, # Redirigir stderr a /dev/null
            preexec_fn=os.setsid # Desvincular el proceso hijo del proceso padre
        )
        video_processes_agent[host] = {"pid": process.pid, "host_pid": pid_host}

        return jsonify({
            "success": True,
            "message": f"Transmisión iniciada en Mininet desde {host} a udp://{ip_destino}:{puerto}",
            "ffmpeg_pid": process.pid
        })
    except Exception as e:
        return jsonify({"error": "Fallo al iniciar el proceso ffmpeg", "details": str(e)}), 500


@app.route('/mininet/stop_ffmpeg', methods=['POST'])
def stop_ffmpeg_on_host():
    data = request.get_json()
    host = data.get('host')

    if not host or not re.match(r'^[a-zA-Z0-9_-]+$', host):
        return jsonify({"error": "Parámetro 'host' inválido"}), 400

    pid_host = get_host_pid(host)
    if not pid_host:
        return jsonify({"error": f"No se encontró el PID del host '{host}'"}), 404

    ffmpeg_pid = video_processes_agent.get(host, {}).get("pid")
    if not ffmpeg_pid:
        return jsonify({"error": f"No hay proceso ffmpeg registrado para el host {host}"}), 404

    try:
        subprocess.run(['mnexec', '-a', str(pid_host), 'kill', '-9', str(ffmpeg_pid)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        del video_processes_agent[host]
        return jsonify({"success": True, "message": f"Proceso ffmpeg ({ffmpeg_pid}) en {host} terminado."})
    except subprocess.CalledProcessError:
        if host in video_processes_agent:
            del video_processes_agent[host] # Limpiar la caché si el proceso ya no existe
        return jsonify({"success": True, "message": f"Proceso en {host} no encontrado o ya terminado."})
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Timeout al intentar terminar el proceso ffmpeg"}), 500
    except Exception as e:
        return jsonify({"error": "Fallo al detener el proceso ffmpeg", "details": str(e)}), 500

@app.route('/mininet/check_file', methods=['POST'])
def check_file_exists():
    data = request.get_json()
    host = data.get('host')
    file_path = data.get('file_path')

    if not all([host, file_path]):
        return jsonify({"error": "Faltan parámetros requeridos"}), 400
    if not re.match(r'^[a-zA-Z0-9_-]+$', host):
        return jsonify({"error": "Parámetro 'host' inválido"}), 400

    pid_host = get_host_pid(host)
    if not pid_host:
        return jsonify({"error": f"No se encontró el PID del host '{host}'"}), 404

    try:
        check_cmd = ['mnexec', '-a', str(pid_host), 'test', '-f', file_path]
        result = subprocess.run(check_cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return jsonify({"exists": True, "message": f"El archivo '{file_path}' existe en {host}."})
        else:
            return jsonify({"exists": False, "message": f"El archivo '{file_path}' NO existe en {host}.", "details": result.stderr.strip()})
    except Exception as e:
        return jsonify({"error": f"Error al verificar archivo en {host}: {str(e)}"}), 500


@app.route('/mininet/ping', methods=['GET'])
def agent_ping():
    return jsonify({"status": "ok", "message": "Agente Mininet operativo"})

if __name__ == '__main__':
    print("Agente: Iniciando el servidor Flask del agente...")
    # Asegúrate de que el puerto 5002 esté libre y sea accesible desde tu servidor Flask principal.
    app.run(host='0.0.0.0', port=5002) # debug=False en producción
    print("Agente: El servidor Flask del agente ha terminado.")

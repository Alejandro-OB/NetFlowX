from flask import Flask, request, jsonify
import subprocess
import re

app = Flask(__name__)

# Diccionario en memoria para guardar PID de ffmpeg por host
video_processes = {}

# Obtener el PID del contenedor del host virtual en Mininet
def get_host_pid(hostname):
    try:
        result = subprocess.run(['pgrep', '-f', f'mininet:{hostname}'],
                                capture_output=True, text=True)
        pid = result.stdout.strip().split('\n')[0]
        return int(pid)
    except Exception:
        return None

@app.route('/start_video', methods=['POST'])
def start_video():
    data = request.get_json()

    host = data.get('host')
    video_path = data.get('video_path', '/mininet/sample.mp4')
    ip_destino = data.get('ip_destino', '10.0.0.2')
    puerto = data.get('puerto', '5004')

    if not host or not re.match(r'^h\d+_\d+$', host):
        return jsonify({"error": "Parámetro 'host' inválido"}), 400

    pid_host = get_host_pid(host)
    if not pid_host:
        return jsonify({"error": f"No se encontró el PID del host '{host}'"}), 404

    try:
        # Lanzar directamente el binario ffmpeg dentro del host sin sh -c
        process = subprocess.Popen(
            ['mnexec', '-a', str(pid_host), 'ffmpeg',
             '-stream_loop', '-1', '-re',
             '-i', video_path,
             '-f', 'mpegts', f'udp://{ip_destino}:{puerto}'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        video_processes[host] = process.pid  # Guardar el PID real de ffmpeg

        return jsonify({
            "success": True,
            "message": f"Transmisión iniciada desde {host} a udp://{ip_destino}:{puerto}",
            "pid_host": pid_host,
            "pid_proceso": process.pid
        })

    except Exception as e:
        return jsonify({"error": "Fallo inesperado", "details": str(e)}), 500

@app.route('/servers/active_servers/<host>', methods=['DELETE'])
def delete_video(host):
    if not re.match(r'^h\d+_\d+$', host):
        return jsonify({"error": "Host inválido"}), 400

    pid_host = get_host_pid(host)
    if not pid_host:
        return jsonify({"error": f"No se encontró el PID del host '{host}'"}), 404

    pid = video_processes.get(host)
    if not pid:
        return jsonify({"error": f"No hay proceso registrado para el host {host}"}), 404

    try:
        # Matar el proceso directamente por PID dentro del namespace del host
        subprocess.run(['mnexec', '-a', str(pid_host), 'kill', '-9', str(pid)])
        del video_processes[host]

        return jsonify({
            "success": True,
            "message": f"Proceso {pid} en {host} fue terminado"
        })

    except Exception as e:
        return jsonify({"error": "Fallo al eliminar el proceso", "details": str(e)}), 500

@app.route('/ping', methods=['GET'])
def ping():
    return jsonify({"status": "ok", "message": "Agente operativo"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001)

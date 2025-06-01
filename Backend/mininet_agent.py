import subprocess
import re
import os
import atexit
import signal
import time
import psycopg2
from flask import Flask, request, jsonify

app = Flask(__name__)

# Diccionario en memoria para guardar PID de ffmpeg por host, incluyendo host_pid
# Esto es crucial para que mnexec -a funcione correctamente en las funciones de detención
video_processes_agent = {} # { "h1_1": {"pid": 12345, "host_pid": 67890, "last_active": timestamp} }

# Función para obtener el PID del contenedor del host virtual en Mininet
def get_host_pid(hostname):
    """
    Busca el PID del proceso 'mininet:<hostname>' que representa el namespace del host.
    """
    try:
        # Usa 'pgrep -f' para encontrar el proceso de mininet asociado al hostname
        result = subprocess.run(['pgrep', '-f', f'mininet:{hostname}'],
                                 capture_output=True, text=True, check=True)
        # Toma la primera línea de salida (el PID)
        pid = result.stdout.strip().split('\n')[0]
        return int(pid)
    except subprocess.CalledProcessError:
        print(f"Agente: No se encontró el PID del proceso Mininet para '{hostname}'.")
        return None
    except ValueError:
        print(f"Agente: pgrep para '{hostname}' devolvió una salida no numérica.")
        return None
    except Exception as e:
        print(f"Agente: Error inesperado al obtener PID del host '{hostname}': {e}")
        return None

# Función para limpiar procesos de ffmpeg al cerrar el agente
def cleanup_agent_processes():
    """
    Intenta terminar todos los procesos de video activos gestionados por el agente.
    """
    print("Agente: Intentando terminar todos los procesos de video activos...")
    for host in list(video_processes_agent.keys()):
        info = video_processes_agent.get(host)
        if not info:
            continue

        ffmpeg_pid = info.get("pid")
        host_pid = info.get("host_pid")

        # Antes de intentar matar el registrado, intenta matar cualquier ffmpeg
        # Esto es más robusto para la limpieza general
        kill_all_ffmpeg_on_host(host, host_pid)
            
        # Siempre eliminar la entrada de la caché en memoria del agente después de intentar la limpieza
        if host in video_processes_agent:
            del video_processes_agent[host]

    print("Agente: Limpieza de procesos de video completada.")

# Registra la función de limpieza para que se ejecute al salir
atexit.register(cleanup_agent_processes)

# Manejadores de señal para una limpieza más robusta al detener el agente
def signal_handler_agent(signum, frame):
    print(f"Agente: Señal {signum} recibida. Iniciando limpieza...")
    cleanup_agent_processes()
    time.sleep(1)
    os._exit(0)

signal.signal(signal.SIGTERM, signal_handler_agent)
signal.signal(signal.SIGINT, signal_handler_agent)

# --- NUEVA FUNCIÓN: Mata todos los procesos ffmpeg en un host específico ---
def kill_all_ffmpeg_on_host(hostname, host_pid):
    if not host_pid:
        print(f"Agente: No se puede limpiar FFmpeg en {hostname}: host_pid desconocido.")
        return

    try:
        # Busca PIDs de ffmpeg en el namespace del host
        cmd_find_ffmpeg = ['mnexec', '-a', str(host_pid), 'pgrep', '-f', 'ffmpeg']
        result_find = subprocess.run(cmd_find_ffmpeg, capture_output=True, text=True, check=False, timeout=5)

        if result_find.returncode == 0 and result_find.stdout.strip():
            pids_to_kill = [p for p in result_find.stdout.strip().split('\n') if p.isdigit()]
            
            if pids_to_kill:
                print(f"Agente: Encontrados PIDs de FFmpeg en {hostname} para detener: {pids_to_kill}")
                for pid in pids_to_kill:
                    try:
                        subprocess.run(
                            ['mnexec', '-a', str(host_pid), 'kill', '-9', str(pid)],
                            check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5
                        )
                        print(f"Agente: Proceso FFmpeg ({pid}) en {hostname} detenido.")
                    except subprocess.TimeoutExpired:
                        print(f"Agente: Timeout al intentar matar FFmpeg ({pid}) en {hostname}.")
                    except Exception as e:
                        print(f"Agente: Error al intentar matar FFmpeg ({pid}) en {hostname}: {e}")
            else:
                print(f"Agente: No se encontraron procesos FFmpeg activos para {hostname}.")
        else:
            print(f"Agente: No se encontraron procesos FFmpeg activos para {hostname} (pgrep output: '{result_find.stdout.strip()}').")
    except subprocess.TimeoutExpired:
        print(f"Agente: Timeout al intentar listar procesos FFmpeg en {hostname} para limpieza.")
    except Exception as e:
        print(f"Agente: Error inesperado al intentar limpiar procesos FFmpeg en {hostname}: {e}")


@app.route('/mininet/start_ffmpeg', methods=['POST'])
def start_ffmpeg_on_host():
    """
    Inicia un proceso ffmpeg para transmitir video en un host específico de Mininet.
    Antes de iniciar, asegura que no haya otros procesos ffmpeg activos en el host.
    """
    data = request.get_json()

    host = data.get('host')
    video_path = data.get('video_path')
    ip_destino = data.get('ip_destino')
    puerto = data.get('puerto')

    # Validaciones básicas de parámetros
    if not all([host, video_path, ip_destino, puerto]):
        return jsonify({"error": "Faltan parámetros requeridos (host, video_path, ip_destino, puerto)"}), 400

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

    # --- CAMBIO CLAVE AQUÍ: Matar *todos* los procesos ffmpeg existentes antes de iniciar uno nuevo ---
    print(f"Agente: Ejecutando limpieza de procesos FFmpeg en {host} antes de iniciar uno nuevo...")
    kill_all_ffmpeg_on_host(host, pid_host)
    # Limpiar también la entrada de la caché del agente, ya que hemos matado todo
    if host in video_processes_agent:
        del video_processes_agent[host]

    # Verificar existencia del archivo de video en el host de Mininet
    try:
        check_file_cmd = ['mnexec', '-a', str(pid_host), 'test', '-f', video_path]
        check_result = subprocess.run(check_file_cmd, capture_output=True, text=True, timeout=10)
        if check_result.returncode != 0:
            return jsonify({"error": f"El archivo de video '{video_path}' NO existe o no es accesible en el host '{host}'"}), 400
    except subprocess.TimeoutExpired:
        return jsonify({"error": f"Timeout al verificar existencia del archivo en {host}."}), 500
    except Exception as e:
        return jsonify({"error": f"Error al verificar existencia del archivo en {host}: {str(e)}"}), 500

    try:
        # Comando ffmpeg para transmitir video en bucle
        process = subprocess.Popen(
            ['mnexec', '-a', str(pid_host), 'ffmpeg',
             '-stream_loop', '-1', '-re',
             '-i', video_path,
             '-f', 'mpegts', f'udp://{ip_destino}:{puerto}',
             '-loglevel', 'quiet'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            preexec_fn=os.setsid
        )
        # Almacenar el PID del proceso ffmpeg y el PID del host de Mininet
        video_processes_agent[host] = {"pid": process.pid, "host_pid": pid_host}

        print(f"Agente: Proceso FFmpeg iniciado para {host}. Procesos activos: {video_processes_agent}")

        return jsonify({
            "success": True,
            "message": f"Transmisión iniciada en Mininet desde {host} a udp://{ip_destino}:{puerto}",
            "ffmpeg_pid": process.pid
        })
    except Exception as e:
        print(f"Agente: Fallo al iniciar el proceso ffmpeg en {host}: {e}")
        return jsonify({"error": "Fallo al iniciar el proceso ffmpeg", "details": str(e)}), 500


@app.route('/mininet/stop_ffmpeg', methods=['POST'])
def stop_ffmpeg_on_host():
    """
    Detiene un proceso ffmpeg específico en un host de Mininet.
    Se ha mejorado para intentar matar *todos* los procesos FFmpeg en el host.
    """
    data = request.get_json()
    host = data.get('host')

    if not host or not re.match(r'^[a-zA-Z0-9_-]+$', host):
        return jsonify({"error": "Parámetro 'host' inválido"}), 400

    # Obtener el host_pid directamente, si no está en caché, intentarlo
    # Esto es crucial si la entrada en video_processes_agent se perdió
    pid_host = get_host_pid(host)
    if not pid_host:
        print(f"Agente: No se encontró el PID del host '{host}'. Asumiendo que Mininet no está activo o el host no existe.")
        # Si no se puede obtener el PID del host, no se puede hacer nada
        if host in video_processes_agent:
            del video_processes_agent[host] # Limpiar la caché si no se puede acceder al host
        return jsonify({"success": True, "message": f"No se pudo encontrar el host '{host}' para detener FFmpeg."})

    # Intentar detener todos los procesos ffmpeg en el host
    print(f"Agente: Solicitud de detención para {host}. Ejecutando limpieza completa de FFmpeg en el host.")
    kill_all_ffmpeg_on_host(host, pid_host)

    # Limpiar la entrada de la caché del agente para este host
    if host in video_processes_agent:
        current_ffmpeg_pid = video_processes_agent[host].get("pid", "N/A")
        del video_processes_agent[host]
        print(f"Agente: Entrada de caché para {host} (PID: {current_ffmpeg_pid}) eliminada.")

    print(f"Agente: Procesos activos después de detener: {video_processes_agent}")
    return jsonify({"success": True, "message": f"Todos los procesos ffmpeg asociados a {host} han sido terminados."})


@app.route('/mininet/check_file', methods=['POST'])
def check_file_exists():
    """
    Verifica si un archivo existe en un host de Mininet.
    """
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
        result = subprocess.run(check_cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return jsonify({"exists": True, "message": f"El archivo '{file_path}' existe en {host}."})
        else:
            return jsonify({"exists": False, "message": f"El archivo '{file_path}' NO existe en {host}.", "details": result.stderr.strip()})
    except subprocess.TimeoutExpired:
        return jsonify({"error": f"Timeout al verificar archivo en {host}."}), 500
    except Exception as e:
        print(f"Agente: Error al verificar archivo en {host}: {e}")
        return jsonify({"error": f"Error al verificar archivo en {host}: {str(e)}"}), 500


@app.route('/mininet/ping', methods=['GET'])
def agent_ping():
    """
    Endpoint simple para verificar que el agente está operativo.
    """
    return jsonify({"status": "ok", "message": "Agente Mininet operativo"})

@app.route('/mininet/processes', methods=['GET'])
def get_running_processes():
    """
    Retorna la lista de procesos FFmpeg que el agente tiene registrados como activos.
    """
    # Retorna una copia para evitar modificar el diccionario original desde fuera
    return jsonify(video_processes_agent), 200

@app.route('/mininet/add_link', methods=['POST'])
def add_link():
    """
    Recibe JSON:
      {
        "id_origen": <int>,
        "id_destino": <int>,
        "ancho_banda": <int>  # en Mbps
      }

    1) Consulta la tabla 'puertos' para obtener (puerto_origen, puerto_destino).
    2) Crea dos patch‐ports OVS que conectan s<id_origen> <--> s<id_destino>,
       forzando con 'ofport_request' que el puerto interno coincida con esos puertos.
    3) Aplica un tc qdisc tipo TBF a cada interfaz patch, limitando a 'ancho_banda' Mbps.
    """

    data = request.get_json() or {}
    id_origen  = data.get('id_origen')
    id_destino = data.get('id_destino')
    bw_mbps    = data.get('ancho_banda')

    # --- 1) Validar parámetros ---
    if id_origen is None or id_destino is None or bw_mbps is None:
        return (jsonify({"error": "Faltan parámetros: id_origen, id_destino y/o ancho_banda"}), 400)
    try:
        id_origen  = int(id_origen)
        id_destino = int(id_destino)
        bw_mbps    = int(bw_mbps)
    except ValueError:
        return (jsonify({"error": "id_origen, id_destino y ancho_banda deben ser enteros"}), 400)
    if id_origen == id_destino:
        return (jsonify({"error": "id_origen e id_destino no pueden ser iguales"}), 400)

    # --- 2) Leer de la BD: puerto_origen / puerto_destino ---
    conn = None
    cur  = None
    try:
        conn = psycopg2.connect(
            dbname="geant_network",
            user="geant_user",
            password="geant",
            host="192.168.18.151",
            port="5432",
        )
        cur = conn.cursor()
        cur.execute("""
            SELECT puerto_origen, puerto_destino
            FROM puertos
            WHERE id_origen_switch = %s
              AND id_destino_switch = %s
            LIMIT 1;
        """, (id_origen, id_destino))
        row = cur.fetchone()
        if row is None:
            return (
                jsonify({
                    "error": f"No existe registro en 'puertos' para "
                             f"id_origen_switch={id_origen} y id_destino_switch={id_destino}"
                }),
                404
            )
        puerto_origen, puerto_destino = row
        if puerto_origen is None or puerto_destino is None:
            return (jsonify({"error": "Los campos puerto_origen/p_destino están vacíos en 'puertos'."}), 400)
    except psycopg2.Error as e:
        return (jsonify({"error": f"Error en la BD: {e}"}), 500)
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

    # Convertir a int (por si vienen como str)
    try:
        puerto_origen  = int(puerto_origen)
        puerto_destino = int(puerto_destino)
    except (ValueError, TypeError):
        return (jsonify({"error": "Valores de puerto_origen/puerto_destino no válidos"}), 400)

    # --- 3) Preparar nombres de switches e interfaces patch ---
    switch_A      = f"s{id_origen}"
    switch_B      = f"s{id_destino}"
    iface_A_to_B  = f"patch-{id_origen}-{id_destino}"
    iface_B_to_A  = f"patch-{id_destino}-{id_origen}"

    # --- 4) Comprobar que los bridges OVS existen ---
    try:
        subprocess.run(
            ["ovs-vsctl", "br-exists", switch_A],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        subprocess.run(
            ["ovs-vsctl", "br-exists", switch_B],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except subprocess.CalledProcessError:
        return (
            jsonify({"error": f"Alguno de los switches OVS ({switch_A} o {switch_B}) no existe."}),
            404
        )

    try:
        # 5.1) Patch en A
        subprocess.run([
            "ovs-vsctl", "add-port", switch_A, iface_A_to_B,
            "--", "set", "interface", iface_A_to_B,
            "type=patch",
            f"options:peer={iface_B_to_A}",
            f"ofport_request={puerto_origen}"
        ], check=True)

        # 5.2) Patch en B
        subprocess.run([
            "ovs-vsctl", "add-port", switch_B, iface_B_to_A,
            "--", "set", "interface", iface_B_to_A,
            "type=patch",
            f"options:peer={iface_A_to_B}",
            f"ofport_request={puerto_destino}"
        ], check=True)
    except subprocess.CalledProcessError as e:
        stderr_msg = ""
        try:
            stderr_msg = e.stderr.decode().strip()
        except:
            pass
        # Si el puerto ya existía (por ejemplo, un patch duplicado),
        # podemos detectarlo por “already exists” y seguir.
        if "already exists" in stderr_msg or "exists" in stderr_msg:
            # Continuamos para aplicar TC de todas formas
            pass
        else:
            return (
                jsonify({"error": f"Error al crear patch ports OVS: {stderr_msg or e}"}),
                500
            )

    for iface in (iface_A_to_B, iface_B_to_A):
        # 6.1) Eliminar qdisc previo (si existía)
        subprocess.run(
            ["tc", "qdisc", "del", "dev", iface, "root"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        # 6.2) Agregar TBF con la tasa de Mbps
        try:
            subprocess.run([
                "tc", "qdisc", "add", "dev", iface, "root", "tbf",
                "rate", f"{bw_mbps}mbit",
                "burst", "10kb",
                "latency", "70ms"
            ], check=True)
        except subprocess.CalledProcessError as e:
            return (
                jsonify({
                    "error": f"No se pudo aplicar límite de ancho de banda a {iface}: {e}"
                }),
                500
            )

    # --- 7) Responder éxito ---
    return (
        jsonify({
            "success": True,
            "message": (
                f"Enlace dinámico inyectado (patch) en Mininet: "
                f"{switch_A}:{puerto_origen} <--> {switch_B}:{puerto_destino} "
                f"(bw={bw_mbps} Mbps)"
            )
        }),
        200
    )

if __name__ == '__main__':
    print("Agente: Iniciando el servidor Flask del agente...")
    app.run(host='0.0.0.0', port=5002)
    print("Agente: El servidor Flask del agente ha terminado.")
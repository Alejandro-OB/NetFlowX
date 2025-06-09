import subprocess
import re
import os
import atexit
import signal
import time
import sys
import traceback
from flask import Flask, request, jsonify, Response
from flask_cors import CORS # Importar CORS
import psycopg2

app = Flask(__name__)
CORS(app) 

ffmpeg_server_processes = {}


ffplay_client_processes = {}

DB_CONFIG = {
    "dbname": "geant_network",  # Nombre de la base de datos
    "user": "geant_user",       # Usuario de la base de datos
    "password": "geant",        # Contraseña del usuario
    "host": "192.168.18.151",  # Dirección IP o hostname del servidor de la base de datos
    "port": "5432"             # Puerto de la base de datos (por defecto para PostgreSQL es 5432)
}

def limpiar_servidores_activos():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        cur.execute("DELETE FROM servidores_vlc_activos;")
        conn.commit()
        cur.close()
        conn.close()
        print("Agente: Tabla 'servidores_vlc_activos' limpiada al iniciar.")
    except Exception as e:
        print(f"Agente: Error al limpiar tabla servidores_vlc_activos: {e}")


def get_host_pid(hostname):

    try:
        result = subprocess.run(['pgrep', '-f', f'mininet:{hostname}'], capture_output=True, text=True, check=True)
        pid = result.stdout.strip().split('\n')[0]
        return int(pid)
    except Exception as e:
        print(f"Agente: Error obteniendo PID para '{hostname}': {e}")
        return None

def kill_media_processes_on_host(hostname, host_pid, process_type="any", specific_pid=None):

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
    Espera JSON con: host, video_path, ip_multicast, puerto.
    """
    data = request.get_json()
    host = data.get('host')
    video_path = data.get('video_path')
    ip_multicast = data.get('ip_multicast')
    puerto = data.get('puerto')

    if not all([host, video_path, ip_multicast, puerto]):
        return jsonify({"error": "Faltan parámetros: host, video_path, ip_multicast, puerto"}), 400
    
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

    if host in ffmpeg_server_processes:
        kill_media_processes_on_host(host, ffmpeg_server_processes[host].get("host_pid"), "server")
        del ffmpeg_server_processes[host]

    pid_host = get_host_pid(host)
    if not pid_host:
        return jsonify({"error": f"No se pudo encontrar el PID del host de Mininet: {host}"}), 500

    try:
        process = subprocess.Popen(
            ['mnexec', '-a', str(pid_host), 'ffmpeg',
             '-stream_loop', '-1',               # Bucle infinito
             '-re',                              # Leer a velocidad nativa de fotogramas
             '-i', video_path,                   # Ruta del video
             '-c:v', 'libx264',                  # Códec de video H.264
             '-preset', 'veryfast',              # Preset de codificación rápida
             '-b:v', '2M',                       # Bitrate de video
             '-maxrate', '2M',                   # Tasa máxima de bits
             '-bufsize', '4M',                   # Tamaño del búfer
             '-c:a', 'aac',                      # Códec de audio
             '-b:a', '128k',                     # Bitrate de audio
             '-f', 'mpegts',                     # Formato de salida
             f'udp://{ip_multicast}:{puerto}?ttl=1',  # Dirección de salida multicast
             '-loglevel', 'quiet']              # Silenciar la salida
            ,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, 
            preexec_fn=os.setsid 
        )
        ffmpeg_server_processes[host] = {"pid": process.pid, "host_pid": pid_host}
        print(f"Agente: Transmisión FFmpeg iniciada para {host} a {ip_multicast}:{puerto}. PID: {process.pid}")
        return jsonify({"success": True, "message": f"Transmisión FFmpeg iniciada a {ip_multicast}:{puerto}", "ffmpeg_pid": process.pid}), 200
    except Exception as e:
        print(f"Agente: Error al iniciar ffmpeg en {host}: {e}")
        return jsonify({"error": f"Error al iniciar ffmpeg: {e}"}), 500

@app.route('/mininet/stop_ffmpeg_server', methods=['POST'])
def stop_ffmpeg_server_on_host():

    data = request.get_json()
    host = data.get('host')
    ip_multicast = data.get('ip_multicast')

    if not host or not re.match(r'^[a-zA-Z0-9_-]+$', host):
        return jsonify({"error": "Parámetro 'host' inválido"}), 400
    if not ip_multicast or not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', ip_multicast):
        return jsonify({"error": "Parámetro 'ip_multicast' inválido"}), 400

    key = (host, ip_multicast)

    if key not in ffmpeg_server_processes:
        print(f"Agente: No se encontró proceso FFmpeg de servidor activo para {host} ({ip_multicast}) en el registro.")
        return jsonify({"success": True, "message": f"No se encontró proceso FFmpeg activo para {host} ({ip_multicast})"}), 200

    pid_host = ffmpeg_server_processes[key].get("host_pid")
    specific_pid = ffmpeg_server_processes[key].get("pid")

    if pid_host and specific_pid:
        kill_media_processes_on_host(host, pid_host, "server", specific_pid=specific_pid)
        print(f"Agente: FFmpeg servidor PID {specific_pid} detenido en {host} ({ip_multicast}).")

    del ffmpeg_server_processes[key]

    return jsonify({"success": True, "message": f"FFmpeg servidor detenido en {host} ({ip_multicast})"}), 200


@app.route('/mininet/start_ffmpeg_client', methods=['POST'])
def start_ffmpeg_client_on_host(): 

    data = request.get_json()
    host = data.get('host')
    multicast_ip = data.get('multicast_ip')
    puerto = data.get('puerto')

    if not all([host, multicast_ip, puerto]):
        return jsonify({"error": "Faltan parámetros: host, multicast_ip, puerto"}), 400
    
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

    if host in ffplay_client_processes:
        kill_media_processes_on_host(host, ffplay_client_processes[host].get("host_pid"), "client", specific_pid=ffplay_client_processes[host].get("pid"))
        del ffplay_client_processes[host]

    pid_host = get_host_pid(host)
    if not pid_host:
        return jsonify({"error": f"No se pudo encontrar el PID del host de Mininet: {host}"}), 500

    try:
        process = subprocess.Popen(
            ['mnexec', '-a', str(pid_host), 'ffplay',
            '-x', '320', '-y', '240', 
             '-an',                    
             f'udp://@{multicast_ip}:{puerto}'],
            stdout=None,
            stderr=None,
            preexec_fn=os.setsid
        )


        ffplay_client_processes[host] = {"pid": process.pid, "host_pid": pid_host}
        print(f"Agente: Cliente FFplay iniciado en {host} para {multicast_ip}:{puerto}. PID: {process.pid}")
        return jsonify({"success": True, "message": f"FFplay cliente iniciado en {host} para {multicast_ip}:{puerto}", "ffplay_client_pid": process.pid}), 200
    except Exception as e:
        print(f"Agente: Error al iniciar FFplay cliente en {host}: {e}")
        return jsonify({"error": f"Error al iniciar FFplay cliente: {e}"}), 500

@app.route('/mininet/stop_ffmpeg_client', methods=['POST']) 
def stop_ffmpeg_client_on_host():

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
                time.sleep(0.2)  

            process.stdout.close()
            process.wait()
        except Exception as e:
            yield f"data: ERROR: {str(e)}\n\n"

    return Response(generate(), mimetype='text/event-stream')

def get_host_db_info(identifier):

    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()

        cur.execute("SELECT id_host, nombre, ipv4 FROM hosts WHERE nombre = %s;", (identifier,))
        result = cur.fetchone()
        if result:
            return {"id_host": result[0], "nombre": result[1], "ipv4": result[2]}

        cur.execute("SELECT id_host, nombre, ipv4 FROM hosts WHERE ipv4 = %s;", (identifier,))
        result = cur.fetchone()
        if result:
            return {"id_host": result[0], "nombre": result[1], "ipv4": result[2]}

        return None
    except Exception as e:
        print(f"Error al obtener información del host para {identifier}: {e}")
        return None
    finally:
        if conn:
            conn.close()

def parse_ping_output(ping_output):

    rtt_match = re.search(r'rtt min/avg/max/mdev = [\d.]+/([\d.]+)/[\d.]+/([\d.]+) ms', ping_output)
    
    if rtt_match:
        avg_rtt = float(rtt_match.group(1)) 
        jitter = float(rtt_match.group(2))   
        return avg_rtt, jitter

    return None, None  



@app.route('/mininet/ping_between_hosts_stream', methods=['GET'])
def ping_between_hosts_stream():
    data = request.args  
    origen_identifier = data.get('origen')
    destino_identifier = data.get('destino')

    try:
        ping_count = int(data.get('count', 1))
        interval = float(data.get('interval', 1))
    except ValueError:
        return Response("data: ERROR: Parámetros 'count' o 'interval' inválidos.\n\n", mimetype='text/event-stream'), 400

    if not origen_identifier or not destino_identifier:
        return Response("data: ERROR: Parámetros 'origen' y 'destino' son requeridos.\n\n", mimetype='text/event-stream'), 400

    origen_info = get_host_db_info(origen_identifier)
    destino_info = get_host_db_info(destino_identifier)

    if not origen_info:
        print(f"Agente: No se encontró información para el host de origen: {origen_identifier}")
        return Response(f"data: ERROR: No se encontró información para el host de origen: {origen_identifier}\n\n", mimetype='text/event-stream'), 404
    if not destino_info:
        print(f"Agente: No se encontró información para el host de destino: {destino_identifier}")
        return Response(f"data: ERROR: No se encontró información para el host de destino: {destino_identifier}\n\n", mimetype='text/event-stream'), 404

    id_origen = origen_info["id_host"]
    id_destino = destino_info["id_host"]
    nombre_origen = origen_info["nombre"]
    nombre_destino = destino_info["nombre"]
    ping_target_ip = destino_info["ipv4"]
    def generate_ping_stream():
        conn = None
        cur = None
        id_latencia = None
        ping_process = None

        try:
            conn = psycopg2.connect(**DB_CONFIG)
            cur = conn.cursor()
            time.sleep(2)
            cur.execute(
                "SELECT id_ruta FROM rutas_ping WHERE host_origen = %s AND host_destino = %s "
                "ORDER BY timestamp DESC LIMIT 1;",
                (id_origen, id_destino)  
            )
            ruta_result = cur.fetchone()

            if ruta_result:
                id_ruta = ruta_result[0]
            else:
                raise ValueError(f"No se encontró la ruta entre los hosts {id_origen} y {id_destino} en la tabla rutas_ping.")

            cur.execute(
                "INSERT INTO latencias (host_origen, host_destino, timestamp, id_ruta) VALUES (%s, %s, NOW(), %s) RETURNING id_latencia;",
                (nombre_origen, nombre_destino, id_ruta)  
            )
            id_latencia = cur.fetchone()[0]
            conn.commit()
            yield f"data: Ping iniciado (ID de registro en BD: {id_latencia})...\n\n"

            pid_origen = get_host_pid(nombre_origen)
            if not pid_origen:
                yield "data: ERROR: No se encontró PID para el host origen.\n\n"
                return

            ping_command = ['mnexec', '-a', str(pid_origen), 'ping', '-c', '3', ping_target_ip]
            yield f"data: Ejecutando Ping entre {nombre_origen} y {nombre_destino}\n\n"

            ping_process = subprocess.Popen(
                ping_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  
                text=True
            )

            full_output_lines = []
            for line in iter(ping_process.stdout.readline, ''):
                full_output_lines.append(line)
                yield f"data: {line.strip()}\n\n"  

            ping_process.stdout.close()
            return_code = ping_process.wait(timeout=(ping_count * interval * 2 + 5))  

            stdout_str = "".join(full_output_lines)

            if return_code == 0:
                latency_match = re.search(r"rtt min/avg/max/mdev = [\d.]+/([\d.]+)/[\d.]+/([\d.]+) ms", stdout_str)
                if latency_match:
                    avg_latency = float(latency_match.group(1))
                    jitter = float(latency_match.group(2))  

                    cur.execute(
                        "UPDATE latencias SET rtt_ms = %s, jitter_ms = %s WHERE id_latencia = %s;",
                        (avg_latency, jitter, id_latencia)  
                    )
                    conn.commit()
                    yield f"data: --- FIN DE PING ---\n\n"
                    yield f"data: Latencia promedio: {avg_latency} ms\n\n"
                    yield f"data: Jitter: {jitter} ms\n\n"
                    yield f"data: STATUS: success\n\n"
                else:
                    error_message = "No se pudo parsear la latencia o jitter del ping."
                    yield f"data: ERROR: {error_message}. Salida completa: {stdout_str}\n\n"
                    yield f"data: STATUS: error\n\n"
            else:
                error_message = f"El comando ping falló con código de salida {return_code}."
                yield f"data: ERROR: {error_message}. Salida completa: {stdout_str}\n\n"
                yield f"data: STATUS: error\n\n"

        except subprocess.TimeoutExpired:
            if ping_process:
                ping_process.kill()
                ping_process.communicate()  
            error_message = "El comando ping excedió el tiempo de espera."
            if conn and cur and id_latencia:
                cur.execute(
                    "UPDATE latencias SET exit_code = %s WHERE id_latencia = %s;",
                    (124, error_message, id_latencia)  
                )
                conn.commit()
            yield f"data: ERROR: {error_message}\n\n"
            yield f"data: STATUS: error\n\n"
        except Exception as e:
            error_message = f"Error interno en el agente al ejecutar ping: {e}"
            import traceback
            traceback.print_exc()  
            if conn and cur and id_latencia:
                cur.execute(
                    "UPDATE latencias SET error_message = %s WHERE id_latencia = %s;",
                    (error_message, id_latencia)
                )
                conn.commit()
            yield f"data: ERROR: {error_message}\n\n"
            yield f"data: STATUS: error\n\n"
        finally:
            if conn:
                conn.close()

    return Response(generate_ping_stream(), mimetype='text/event-stream')


def crear_patch(id_origen, id_destino, bw_mbps, puerto_origen, puerto_destino):
    swA = f"s{id_origen}"
    swB = f"s{id_destino}"
    ifaceA = f"patch-{id_origen}-{id_destino}"
    ifaceB = f"patch-{id_destino}-{id_origen}"
    warning_msgs = []

    try:
        subprocess.run([
            "ovs-vsctl", "add-port", swA, ifaceA,
            "--", "set", "interface", ifaceA,
            "type=patch",
            f"options:peer={ifaceB}",
            f"ofport_request={puerto_origen}"
        ], check=True, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        warning_msgs.append(f"Error creando patch en {swA}: {e.stderr.decode(errors='ignore') if e.stderr else str(e)}")

    try:
        subprocess.run([
            "ovs-vsctl", "add-port", swB, ifaceB,
            "--", "set", "interface", ifaceB,
            "type=patch",
            f"options:peer={ifaceA}",
            f"ofport_request={puerto_destino}"
        ], check=True, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        warning_msgs.append(f"Error creando patch en {swB}: {e.stderr.decode(errors='ignore') if e.stderr else str(e)}")

    time.sleep(0.5)

    ports_reales = {}
    for iface in (ifaceA, ifaceB):
        try:
            ofport_raw = subprocess.check_output([
                "ovs-vsctl", "get", "Interface", iface, "ofport"
            ]).decode().strip()
            ports_reales[iface] = int(ofport_raw)
        except Exception as e:
            raise RuntimeError(f"No se pudo obtener ofport para {iface}: {e}")

    tc_errors = []
    for iface in (ifaceA, ifaceB):
        subprocess.run(["tc", "qdisc", "del", "dev", iface, "root"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            subprocess.run([
                "tc", "qdisc", "add", "dev", iface, "root", "tbf",
                "rate", f"{bw_mbps}mbit",
                "burst", "10kb",
                "latency", "70ms"
            ], check=True, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as e:
            tc_errors.append(f"{iface}: {e.stderr.decode(errors='ignore') if e.stderr else str(e)}")

    return ports_reales, warning_msgs, tc_errors


@app.route('/mininet/add_link', methods=['POST'])
def add_link():
    import traceback  

    try:
        data = request.get_json() or {}
        id_origen = int(data.get('id_origen'))
        id_destino = int(data.get('id_destino'))
        bw_mbps = int(data.get('ancho_banda'))

        if id_origen == id_destino or bw_mbps <= 0:
            return jsonify({"error": "Parámetros inválidos"}), 400

        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        cur.execute("""
            SELECT puerto_origen, puerto_destino
            FROM puertos
            WHERE (id_origen_switch = %s AND id_destino_switch = %s)
               OR (id_origen_switch = %s AND id_destino_switch = %s)
            LIMIT 1;
        """, (id_origen, id_destino, id_destino, id_origen))
        row = cur.fetchone()
        cur.close()
        conn.close()

        if row is None:
            return jsonify({
                "error": f"No hay registro en 'puertos' para switches {id_origen} y {id_destino}"
            }), 404

        puerto_origen, puerto_destino = row

        ports_reales, warnings_patch, tc_errors = crear_patch(
            id_origen, id_destino, bw_mbps,
            puerto_origen=puerto_origen,
            puerto_destino=puerto_destino
        )

        response = {
            "success": True,
            "message": f"Patch creado entre {id_origen}↔{id_destino}, bw={bw_mbps} Mbps",
            "ports_reales": ports_reales
        }
        if warnings_patch:
            response["warning"] = " | ".join(warnings_patch)
        if tc_errors:
            response["tc_warning"] = "; ".join(tc_errors)

        return jsonify(response), 200

    except Exception as ex:
        import traceback  
        traceback.print_exc()
        return jsonify({"error": f"Exception interna: {str(ex)}"}), 500


@app.route('/mininet/update_link', methods=['POST'])
def update_link():
    import traceback
    import time

    try:
        data = request.get_json() or {}
        oldA = int(data.get('old_id_origen'))
        oldB = int(data.get('old_id_destino'))
        newA = int(data.get('new_id_origen'))
        newB = int(data.get('new_id_destino'))
        bw  = int(data.get('ancho_banda'))

        if oldA <= 0 or oldB <= 0 or newA <= 0 or newB <= 0 or bw <= 0:
            return jsonify({"error": "IDs y ancho de banda deben ser enteros positivos"}), 400

        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        cur.execute("""
            SELECT puerto_origen, puerto_destino, id_origen_switch, id_destino_switch
            FROM puertos
            WHERE (id_origen_switch = %s AND id_destino_switch = %s)
               OR (id_origen_switch = %s AND id_destino_switch = %s)
            LIMIT 1;
        """, (oldA, oldB, oldB, oldA))
        row = cur.fetchone()
        cur.close()
        conn.close()

        if row is None:
            return jsonify({"error": f"No se encontró en BD un enlace entre {oldA} y {oldB}"}), 404

        puerto_oldA, puerto_oldB, real_oldA, real_oldB = row
        sw_oldA = f"s{real_oldA}"
        sw_oldB = f"s{real_oldB}"
        iface_phys_oldA = f"{sw_oldA}-eth{puerto_oldA}"
        iface_phys_oldB = f"{sw_oldB}-eth{puerto_oldB}"
        patch_oldAB = f"patch-{real_oldA}-{real_oldB}"
        patch_oldBA = f"patch-{real_oldB}-{real_oldA}"

        for cmd in [
            ["ovs-vsctl", "del-port", sw_oldA, iface_phys_oldA],
            ["ovs-vsctl", "del-port", sw_oldB, iface_phys_oldB],
            ["ovs-vsctl", "del-port", sw_oldA, patch_oldAB],
            ["ovs-vsctl", "del-port", sw_oldB, patch_oldBA]
        ]:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        row2 = None
        for intento in range(3):
            print(f"[AGENTE] Intento {intento+1}: buscando enlace {newA}↔{newB} en BD",flush=True)
            try:
                conn2 = psycopg2.connect(**DB_CONFIG)
                cur2 = conn2.cursor()
                cur2.execute("""
                    SELECT puerto_origen, puerto_destino, id_origen_switch, id_destino_switch
                    FROM puertos
                    WHERE (id_origen_switch = %s AND id_destino_switch = %s)
                       OR (id_origen_switch = %s AND id_destino_switch = %s)
                    LIMIT 1;
                """, (newA, newB, newB, newA))
                row2 = cur2.fetchone()
                cur2.close()
                conn2.close()

                if row2:
                    print("[AGENTE] Enlace encontrado:", row2)
                    break
                else:
                    print("[AGENTE] Enlace aún no aparece. Esperando...")
                    time.sleep(0.3)
            except Exception as db_err:
                print("[AGENTE] Error en consulta:", db_err)
                time.sleep(0.3)

        if row2 is None:
            return jsonify({"error": f"No se encontró en BD el nuevo enlace entre {newA} y {newB}"}), 404

        puerto_nuevo_A, puerto_nuevo_B, real_newA, real_newB = row2
        sw_newA = f"s{real_newA}"
        sw_newB = f"s{real_newB}"
        iface_phys_newA = f"{sw_newA}-eth{puerto_nuevo_A}"
        iface_phys_newB = f"{sw_newB}-eth{puerto_nuevo_B}"

        for sw, iface in [(sw_newA, iface_phys_newA), (sw_newB, iface_phys_newB)]:
            try:
                subprocess.run(["ovs-vsctl", "add-port", sw, iface],
                               check=True, stderr=subprocess.PIPE)
            except subprocess.CalledProcessError:
                pass

        ports_reales, warnings_patch, tc_errors = crear_patch(
            real_newA, real_newB, bw,
            puerto_origen=puerto_nuevo_A,
            puerto_destino=puerto_nuevo_B
        )

        respuesta = {
            "success": True,
            "message": (
                f"Enlace {sw_newA}-eth{puerto_nuevo_A} ↔ {sw_newB}-eth{puerto_nuevo_B} recreado "
                f"con patch y BW {bw} Mbps. Puertos reales: {ports_reales}"
            ),
            "ports_reales": ports_reales
        }
        if warnings_patch:
            respuesta["warning"] = " | ".join(warnings_patch)
        if tc_errors:
            respuesta["tc_warning"] = "; ".join(tc_errors)

        return jsonify(respuesta), 200

    except Exception as ex:
        traceback.print_exc()
        return jsonify({"error": f"Exception interna: {str(ex)}"}), 500


@app.route('/mininet/delete_link', methods=['POST'])
def delete_link():


    import traceback  

    try:
        data = request.get_json() or {}
        A = int(data.get('id_origen'))
        B = int(data.get('id_destino'))

        if A <= 0 or B <= 0:
            return jsonify({"error": "IDs deben ser enteros positivos"}), 400

        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        cur.execute("""
            SELECT puerto_origen, puerto_destino, id_origen_switch, id_destino_switch
            FROM puertos
            WHERE (id_origen_switch = %s AND id_destino_switch = %s)
               OR (id_origen_switch = %s AND id_destino_switch = %s)
            LIMIT 1;
        """, (A, B, B, A))

        row = cur.fetchone()
        cur.close()
        conn.close()

        if row is None:
            return jsonify({
                "success": True,
                "message": f"No había enlace físico A={A}↔B={B} en BD. Intentando eliminar patch."
            }), 200

        puerto_origen_old, puerto_destino_old, id_origen_real, id_destino_real = row

        if puerto_origen_old is None or puerto_destino_old is None:
            return jsonify({"error": "Puertos vacíos en BD"}), 400

        swA = f"s{A}"
        swB = f"s{B}"
        iface_physA = f"{swA}-eth{puerto_origen_old}"
        iface_physB = f"{swB}-eth{puerto_destino_old}"

        subprocess.run(
            ["ovs-vsctl", "del-port", swA, iface_physA],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        subprocess.run(
            ["ovs-vsctl", "del-port", swB, iface_physB],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

        patchAB = f"patch-{A}-{B}"
        patchBA = f"patch-{B}-{A}"
        subprocess.run(
            ["ovs-vsctl", "del-port", swA, patchAB],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        subprocess.run(
            ["ovs-vsctl", "del-port", swB, patchBA],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

        return jsonify({
            "success": True,
            "message": f"Interfaces físicas {iface_physA}, {iface_physB} y patch-ports {patchAB}, {patchBA} eliminados (si existían)."
        }), 200

    except Exception as ex:
        traceback.print_exc()
        return jsonify({"error": f"Exception interna: {str(ex)}"}), 500

@app.route('/mininet/status', methods=['GET'])
def mininet_status():

    import subprocess

    def is_mininet_running():
        try:
            result = subprocess.run(
                ["pgrep", "-f", "mnexec"],
                capture_output=True, text=True
            )
            return bool(result.stdout.strip())
        except Exception:
            return False

    def detect_mininet_switches():
        try:
            result = subprocess.run(
                ["ovs-vsctl", "list-br"],
                capture_output=True, text=True, check=True
            )
            bridges = result.stdout.strip().split('\n')
            return any(bridge.startswith('s') for bridge in bridges)
        except Exception:
            return False

    running = is_mininet_running() or detect_mininet_switches()
    return jsonify({"running": running}), 200


if __name__ == '__main__':

    print("Agente: Intentando iniciar el servidor Flask...") 
    app.run(host='0.0.0.0', port=5002, debug=True) 
    print("Agente: Servidor Flask detenido.") 
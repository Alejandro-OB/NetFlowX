from flask import Blueprint, request, jsonify
from services.db import execute_query
import socket

bp = Blueprint('config', __name__)

@bp.route('/', methods=['POST'])
def guardar_configuracion():
    data = request.get_json()

    balanceo = data.get('algoritmo_balanceo')
    enrutamiento = data.get('algoritmo_enrutamiento')

    if not balanceo or not enrutamiento:
        return jsonify({"error": "Faltan datos"}), 400

    query = """
        INSERT INTO configuracion (algoritmo_balanceo, algoritmo_enrutamiento)
        VALUES (%s, %s);
    """
    ok = execute_query(query, (balanceo, enrutamiento))

    if ok:
        return jsonify({"message": "Configuración guardada correctamente"}), 200
    else:
        return jsonify({"error": "No se pudo guardar"}), 500

@bp.route('/pesos', methods=['POST'])
def guardar_pesos():
    data = request.get_json()

    if not isinstance(data, list):
        return jsonify({"error": "Formato inválido"}), 400

    success = True
    for item in data:
        nombre = item.get("servidor")
        peso = item.get("peso")

        if not nombre or peso is None:
            continue

        query = "INSERT INTO pesos_vlc (nombre_servidor, peso) VALUES (%s, %s);"
        ok = execute_query(query, (nombre, peso))
        if not ok:
            success = False

    if success:
        return jsonify({"message": "Pesos guardados correctamente"}), 200
    else:
        return jsonify({"error": "Ocurrió un error al guardar uno o más pesos"}), 500

@bp.route('/servidores', methods=['GET'])
def listar_servidores():
    query = """
        SELECT nombre, activo FROM hosts
        WHERE es_servidor = TRUE
        ORDER BY nombre;
    """
    from services.db import fetch_all
    data = fetch_all(query)
    return jsonify(data), 200

def enviar_comando_a_mininet(comando):
    try:
        with socket.create_connection(("192.168.18.153", 9000), timeout=5) as s:
            s.sendall(comando.encode())
            respuesta = s.recv(1024).decode()
            return respuesta.strip()
    except Exception as e:
        return f"Error al conectar con agente Mininet: {str(e)}"
    
@bp.route('/servidores/<nombre>', methods=['PUT'])
def cambiar_estado_servidor(nombre):
    from services.db import execute_query
    data = request.get_json()
    activo = data.get("activo")

    if activo is None:
        return jsonify({"error": "Falta parámetro 'activo'"}), 400

    query = "UPDATE hosts SET activo = %s WHERE nombre = %s;"
    ok = execute_query(query, (activo, nombre))
    if ok and activo:
        respuesta = enviar_comando_a_mininet(f"activar {nombre}")
        print(f"[Backend] Respuesta de VM: {respuesta}")

    return jsonify({"message": "Servidor actualizado" if ok else "Error"}), 200 if ok else 500

@bp.route('/hosts/asignar-servidor', methods=['PUT'])
def asignar_servidores():
    from services.db import execute_query
    data = request.get_json()
    nombres = data.get("nombres")

    if not nombres or not isinstance(nombres, list):
        return jsonify({"error": "Debe enviar una lista de nombres"}), 400

    query = "UPDATE hosts SET es_servidor = TRUE WHERE nombre = ANY(%s);"
    ok = execute_query(query, (nombres,))

    return jsonify({"message": "Hosts actualizados como servidores" if ok else "Error"}), 200 if ok else 500

@bp.route('/hosts/no-servidores', methods=['GET'])
def listar_no_servidores():
    from services.db import fetch_all
    query = """
        SELECT nombre FROM hosts
        WHERE es_servidor = FALSE OR es_servidor IS NULL
        ORDER BY 
            CAST(split_part(nombre, '_', 1)::TEXT AS TEXT), 
            CAST(split_part(nombre, '_', 2)::INT AS INT);
    """
    data = fetch_all(query)
    return jsonify(data), 200



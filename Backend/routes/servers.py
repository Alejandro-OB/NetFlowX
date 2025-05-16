from flask import Blueprint, jsonify, request
import requests 
import socket

servers_bp = Blueprint('servers', __name__)

AGENTE_MININET_URL = "http://192.168.18.207:5001"

@servers_bp.route('/start_video', methods=['POST'])
def start_video():
    if not request.is_json:
        return jsonify({"error": "Content-Type debe ser application/json"}), 400

    data = request.get_json()
    host_name = data.get('host')
    video_path = data.get('video_path', 'sample.mp4')

    if not host_name:
        return jsonify({"error": "Falta parámetro 'host'"}), 400

    # Verificar agente
    try:
        r = requests.get(f"{AGENTE_MININET_URL}/ping", timeout=5)
        if r.status_code != 200:
            raise ConnectionError("Agente Mininet no responde")
    except Exception as e:
        return jsonify({
            "error": "No se puede contactar al agente",
            "details": str(e)
        }), 502

    # Enviar comando al agente
    try:
        resp = requests.post(
            f"{AGENTE_MININET_URL}/start_video",
            json={"host": host_name, "video_path": video_path, "client_ip": "10.0.0.2", "port": "5004"},
            headers={'Content-Type': 'application/json'},
            timeout=15
        )

        # Validar que la respuesta sea JSON
        try:
            resp_json = resp.json()
        except ValueError:
            return jsonify({
                "error": "El agente devolvió una respuesta no válida",
                "raw_response": resp.text
            }), 502

        if resp.status_code != 200:
            return jsonify({"error": resp_json.get("error", "Fallo del agente")}), resp.status_code

        # Actualizar DB
        from services.db import execute_query
        execute_query("UPDATE hosts SET es_servidor = TRUE, activo = TRUE WHERE nombre = %s", (host_name,))

        return jsonify({
            "success": True,
            "host": host_name,
            "stream_url": "udp://10.0.0.2:5004",
            "pid": resp_json.get("pid")
        })

    except requests.exceptions.Timeout:
        return jsonify({
            "error": "Timeout al contactar agente",
            "timeout": "15 segundos"
        }), 504
    except Exception as e:
        return jsonify({
            "error": "Error inesperado",
            "details": str(e)
        }), 500


@servers_bp.route('/hosts/asignar-servidor', methods=['PUT'])
def asignar_servidores():
    from services.db import execute_query
    data = request.get_json()
    nombres = data.get("nombres")

    if not nombres or not isinstance(nombres, list):
        return jsonify({"error": "Debe enviar una lista de nombres"}), 400

    query = "UPDATE hosts SET es_servidor = TRUE WHERE nombre = ANY(%s);"
    ok = execute_query(query, (nombres,))

    return jsonify({"message": "Hosts actualizados como servidores" if ok else "Error"}), 200 if ok else 500

@servers_bp.route('/hosts/no-servidores', methods=['GET'])
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

@servers_bp.route('/active_servers', methods=['GET'])
def listar_servidores():
    query = """
        SELECT nombre, activo FROM hosts
        WHERE es_servidor = TRUE
        ORDER BY nombre;
    """
    from services.db import fetch_all
    data = fetch_all(query)
    return jsonify(data), 200

@servers_bp.route('/active_servers/<nombre>', methods=['PUT'])
def actualizar_servidor(nombre):
    from services.db import execute_query
    data = request.get_json()
    activo = data.get("activo")

    if activo is None:
        return jsonify({"error": "Falta parámetro 'activo'"}), 400

    if activo:
        query = "UPDATE hosts SET activo = TRUE WHERE nombre = %s;"
        params = (nombre,)
    else:
        query = "UPDATE hosts SET activo = FALSE WHERE nombre = %s;"
        params = (nombre,)

    ok = execute_query(query, params)

    return jsonify({"message": "Servidor actualizado" if ok else "Error"}), 200 if ok else 500


@servers_bp.route('/active_servers/<host>', methods=['DELETE'])
def delete_active_server(host):
    import requests
    try:
        agente_url = f"{AGENTE_MININET_URL}/servers/active_servers/{host}"
        r = requests.delete(agente_url, timeout=5)
        return r.json(), r.status_code
    except Exception as e:
        return {"error": f"Error al contactar agente: {str(e)}"}, 500

@servers_bp.route('/hosts/remover-servidor/<nombre>', methods=['PUT'])
def remover_servidor(nombre):
    from services.db import execute_query
    query = "UPDATE hosts SET es_servidor = FALSE WHERE nombre = %s;"
    ok = execute_query(query, (nombre,))
    return jsonify({"message": "Servidor eliminado del rol"}), 200 if ok else 500


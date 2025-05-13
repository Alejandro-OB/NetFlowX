from flask import Blueprint, jsonify, request
from config import get_db_connection
import json

# Crear un Blueprint para las rutas de reglas y logs
reglas_bp = Blueprint('reglas', __name__)

# Ruta para obtener todas las reglas
@reglas_bp.route('/', methods=['GET'])
def obtener_reglas():
    """Retrieve all rules stored in the PostgreSQL database."""
    try:
        conn = get_db_connection()  # Usamos la conexión a PostgreSQL
        cursor = conn.cursor()

        # Get all rules from the database
        cursor.execute("SELECT * FROM reglas")
        reglas = cursor.fetchall()

        if not reglas:
            return jsonify({"message": "No rules registered."}), 200

        # Convert results to JSON format
        reglas_lista = []
        for regla in reglas:
            reglas_lista.append({
                "dpid": regla[0],  
                "rule_id": regla[1],  
                "priority": regla[2],  
                "eth_type": regla[3],
                "ip_proto": regla[4],
                "ipv4_src": regla[5],
                "ipv4_dst": regla[6],
                "tcp_src": regla[7],
                "tcp_dst": regla[8],
                "in_port": regla[9],
                "actions": json.loads(regla[10]) if regla[10] else []  # Suponiendo que "actions" es un campo JSON
            })

        return jsonify({"switches": reglas_lista})

    except Exception as e:
        return jsonify({"error": f"Error fetching rules: {str(e)}"}), 500

@reglas_bp.route("/<int:dpid>", methods=["POST"])
def agregar_regla(dpid):
    """Add a new rule to the PostgreSQL database."""
    try:
        data = request.json
        if not all(k in data for k in ["rule_id", "eth_type", "priority", "actions"]):
            return jsonify({"error": "Missing required fields."}), 400

        try:
            # Verificar si el campo 'actions' es un JSON válido
            json.dumps(data["actions"])
        except ValueError:
            return jsonify({"error": "The 'actions' field must be valid JSON"}), 400

        conn = get_db_connection()  # Conexión a PostgreSQL
        cursor = conn.cursor()

        # Verificar si ya existe una regla con el mismo rule_id
        cursor.execute("SELECT * FROM reglas WHERE rule_id = %s", (data["rule_id"],))
        if cursor.fetchone():
            return jsonify({"error": "A rule with this ID already exists."}), 400

        # Insertar la nueva regla
        cursor.execute("""
            INSERT INTO reglas (dpid, rule_id, priority, eth_type, ip_proto, ipv4_src, ipv4_dst, tcp_src, tcp_dst, in_port, actions)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            dpid,
            int(data["rule_id"]),
            int(data["priority"]),
            int(data["eth_type"]),
            int(data.get("ip_proto", 0)),
            data.get("ipv4_src"),
            data.get("ipv4_dst"),
            int(data.get("tcp_src", 0)) if data.get("tcp_src") else None,
            int(data.get("tcp_dst", 0)) if data.get("tcp_dst") else None,
            int(data.get("in_port", 0)) if data.get("in_port") else None,
            json.dumps(data["actions"])  # Convertir 'actions' a JSON si es válido
        ))

        conn.commit()
        return jsonify({"message": "Rule added successfully", "rule_id": data["rule_id"]})

    except Exception as e:
        return jsonify({"error": f"Error adding rule: {str(e)}"}), 500



# Ruta para obtener una regla específica por su `rule_id`
@reglas_bp.route('/buscar/<int:rule_id>', methods=['GET'])
def obtener_regla(rule_id):
    """Retrieve a specific rule by its Rule ID from the PostgreSQL database."""
    try:
        conn = get_db_connection()  # Conexión a PostgreSQL
        cursor = conn.cursor()

        # Buscar la regla por rule_id
        cursor.execute("SELECT * FROM reglas WHERE rule_id = %s", (rule_id,))
        regla = cursor.fetchone()

        if not regla:
            return jsonify({'error': 'Rule not found'}), 404

        # Recuperar los valores de la regla usando índices (tuplas en PostgreSQL)
        return jsonify({
            "dpid": regla[0],  # dpid está en la columna 2 (índice 1)
            "rule_id": regla[1],  # rule_id está en la columna 3 (índice 2)
            "priority": regla[2],  # priority está en la columna 4 (índice 3)
            "eth_type": regla[3],  # eth_type está en la columna 5 (índice 4)
            "ip_proto": regla[4],  # ip_proto está en la columna 6 (índice 5)
            "ipv4_src": regla[5],  # ipv4_src está en la columna 7 (índice 6)
            "ipv4_dst": regla[6],  # ipv4_dst está en la columna 8 (índice 7)
            "tcp_src": regla[7],   # tcp_src está en la columna 9 (índice 8)
            "tcp_dst": regla[8],   # tcp_dst está en la columna 10 (índice 9)
            "in_port": regla[9],  # in_port está en la columna 11 (índice 10)
            "actions": json.loads(regla[10]) if regla[10] else []  # actions está en la columna 12 (índice 11)
        })

    except Exception as e:
        return jsonify({'error': f'Error fetching rule: {str(e)}'}), 500


# Ruta para modificar una regla existente
@reglas_bp.route("/modificar/<int:rule_id>", methods=["PUT"])
def modificar_regla(rule_id):
    """Update an existing rule in the PostgreSQL database."""
    try:
        data = request.json
        if not data:
            return jsonify({"error": "No data provided for modification"}), 400

        conn = get_db_connection()  # Conexión a PostgreSQL
        cursor = conn.cursor()

        # Buscar la regla por rule_id
        cursor.execute("SELECT * FROM reglas WHERE rule_id = %s", (rule_id,))
        regla = cursor.fetchone()

        if not regla:
            return jsonify({"error": "Rule not found"}), 404

        valid_columns = [
            "dpid", "priority", "eth_type", "ip_proto", "ipv4_src", "ipv4_dst",
            "tcp_src", "tcp_dst", "in_port", "actions"
        ]

        fields_to_update = []
        values = []
        for key, value in data.items():
            if key in valid_columns:
                if key == "actions":
                    try:
                        # Verificar si el campo actions es un JSON válido
                        json.dumps(value)
                        value = json.dumps(value)
                    except ValueError:
                        return jsonify({"error": "The 'actions' field must be valid JSON"}), 400
                fields_to_update.append(f"{key} = %s")
                values.append(value)

        if not fields_to_update:
            return jsonify({"error": "No valid fields provided for update"}), 400

        values.append(rule_id)
        sql_update = f"UPDATE reglas SET {', '.join(fields_to_update)} WHERE rule_id = %s"
        
        cursor.execute(sql_update, values)
        conn.commit()

        return jsonify({"message": "Rule modified successfully", "rule_id": rule_id})

    except Exception as e:
        return jsonify({"error": f"Error modifying rule: {str(e)}"}), 500


    except Exception as e:
        conn.rollback()
        return jsonify({"error": f"Error modifying rule: {str(e)}"}), 500

# Ruta para eliminar una regla
@reglas_bp.route("/eliminar/<int:rule_id>", methods=["DELETE"])
def eliminar_regla(rule_id):
    """Delete a specific rule from the PostgreSQL database."""
    try:
        conn = get_db_connection()  # Conexión a PostgreSQL
        cursor = conn.cursor()

        # Verificar si la regla existe
        cursor.execute("SELECT * FROM reglas WHERE rule_id = %s", (rule_id,))
        regla = cursor.fetchone()

        if not regla:
            return jsonify({"error": "Rule not found"}), 404

        dpid = regla[2]  # Asumiendo que 'dpid' está en la columna 3 (índice 2)

        # Eliminar la regla
        cursor.execute("DELETE FROM reglas WHERE rule_id = %s", (rule_id,))
        conn.commit()

        # Verificar si el switch tiene más reglas asociadas
        cursor.execute("SELECT COUNT(*) FROM reglas WHERE dpid = %s", (dpid,))
        count = cursor.fetchone()[0]

        
        return jsonify({"message": "Rule deleted successfully", "rule_id": rule_id})

    except Exception as e:
        conn.rollback()
        return jsonify({"error": f"Error deleting rule: {str(e)}"}), 500

# Ruta para obtener todos los logs
@reglas_bp.route('/logs', methods=['GET'])
def obtener_logs():
    """Retrieve all change logs from the PostgreSQL database."""
    try:
        conn = get_db_connection()  # Conexión a PostgreSQL
        cursor = conn.cursor()

        # Ejecutar la consulta para obtener todos los logs ordenados por timestamp descendente
        cursor.execute("SELECT * FROM logs ORDER BY fecha DESC")
        logs = cursor.fetchall()

        if not logs:
            return jsonify({"message": "No log records."}), 200

        logs_lista = []
        for log in logs:
            logs_lista.append({
                "id": log[0],  # id está en la primera columna (índice 0)
                "timestamp": log[12],  # timestamp está en la segunda columna (índice 1)
                "dpid": log[1],  # dpid está en la tercera columna (índice 2)
                "rule_id": log[2],  # rule_id está en la cuarta columna (índice 3)
                "action": log[13],  # action está en la quinta columna (índice 4)
                "priority": log[3],  # priority está en la sexta columna (índice 5)
                "eth_type": log[4],  # eth_type está en la séptima columna (índice 6)
                "ip_proto": log[5],  # ip_proto está en la octava columna (índice 7)
                "ipv4_src": log[6],  # ipv4_src está en la novena columna (índice 8)
                "ipv4_dst": log[7],  # ipv4_dst está en la décima columna (índice 9)
                "tcp_src": log[8],  # tcp_src está en la undécima columna (índice 10)
                "tcp_dst": log[9],  # tcp_dst está en la duodécima columna (índice 11)
                "in_port": log[10],  # in_port está en la decimotercera columna (índice 12)
                "actions": json.loads(log[11]) if log[11] else []  # actions está en la decimocuarta columna (índice 13)
            })

        return jsonify(logs_lista)

    except Exception as e:
        return jsonify({"error": f"Error fetching logs: {str(e)}"}), 500


@reglas_bp.route('/max_rule_id', methods=['GET'])
def obtener_max_rule_id():
    """Retrieve the next available rule_id (maximum + 1) from the PostgreSQL database."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        cur.execute("SELECT MAX(rule_id) FROM reglas")
        max_rule_id = cur.fetchone()[0]

        next_rule_id = (max_rule_id + 1) if max_rule_id is not None else 1
        return jsonify({"next_rule_id": next_rule_id})

    except Exception as e:
        return jsonify({'error': f'Error fetching next rule_id: {str(e)}'}), 500

@reglas_bp.route('/buscar/<int:rule_id>', methods=['GET'])
def obtener_regla_para_modificar(rule_id):
    """Retrieve a specific rule by its Rule ID from the PostgreSQL database for modification."""
    try:
        conn = get_db_connection()  # Usamos la conexión a PostgreSQL
        cursor = conn.cursor()

        # Buscar la regla por rule_id
        cursor.execute("SELECT * FROM reglas WHERE rule_id = %s", (rule_id,))
        regla = cursor.fetchone()

        if not regla:
            return jsonify({'error': 'Rule not found'}), 404

        # Retornar los datos de la regla en formato JSON
        return jsonify({
            "rule_id": regla[1],  # rule_id está en la columna 3 (índice 2)
            "priority": regla[2],  # priority está en la columna 4 (índice 3)
            "eth_type": regla[3],  # eth_type está en la columna 5 (índice 4)
            "ip_proto": regla[4],  # ip_proto está en la columna 6 (índice 5)
            "ipv4_src": regla[5],  # ipv4_src está en la columna 7 (índice 6)
            "ipv4_dst": regla[6],  # ipv4_dst está en la columna 8 (índice 7)
            "tcp_src": regla[7],   # tcp_src está en la columna 9 (índice 8)
            "tcp_dst": regla[8],   # tcp_dst está en la columna 10 (índice 9)
            "in_port": regla[9],  # in_port está en la columna 11 (índice 10)
            "actions": json.loads(regla[11]) if regla[10] else []  # actions está en la columna 12 (índice 11)
        })

    except Exception as e:
        return jsonify({'error': f'Error fetching rule: {str(e)}'}), 500

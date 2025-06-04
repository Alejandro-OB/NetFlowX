from flask import Flask, jsonify, send_from_directory, render_template, request, g
from flask_cors import CORS
import logging

# Blueprints
from routes.topology import topology_bp
from routes import config
from routes.reglas import reglas_bp
# Configuración desde archivo externo
from config import Config
from routes.config import video_bp 
import psycopg2
import psycopg2.extras
import json
from config import Config
# Añade esto cerca de los otros imports
from routes.servers import servers_bp
# NUEVO: Importar el blueprint de solicitudes de cliente
from routes.client_requests import client_requests_bp
from routes.dijkstra import dijkstra_bp
from routes.igmp_server import igmp_bp
from routes.stats import bp as stats_dashboard_bp


def get_db():
    """
    Obtiene una conexión a la base de datos y la almacena en el contexto de la aplicación.
    """
    if 'db' not in g:
        g.db = psycopg2.connect(Config.get_db_uri())
    return g.db

def create_app():
    """
    Crea y configura la instancia de la aplicación Flask.
    """
    app = Flask(__name__)
    app.config.from_object(Config)
    

    # CORS: permitir sólo orígenes confiables
    # Se permite cualquier origen para desarrollo, pero en producción se debería restringir
    CORS(app, resources={r"/*": {"origins": "*"}})


    # Registro de Blueprints
    app.register_blueprint(topology_bp, url_prefix='/topology')
    app.register_blueprint(config.bp, url_prefix='/config')
    #app.register_blueprint(stats.bp, url_prefix='/stats')
    app.register_blueprint(reglas_bp, url_prefix='/reglas')
    app.register_blueprint(video_bp, url_prefix='/config/video')
    app.register_blueprint(servers_bp, url_prefix='/servers')
    app.register_blueprint(client_requests_bp, url_prefix='/client')
    app.register_blueprint(dijkstra_bp, url_prefix='/dijkstra')
    app.register_blueprint(igmp_bp, url_prefix='/igmp')
    app.register_blueprint(stats_dashboard_bp, url_prefix='/stats')


    # Rutas utilitarias
    @app.route('/')
    def index():
        """Sirve el archivo index.html."""
        return send_from_directory('.', 'templates/index.html')
    
    @app.route('/icons/<path:filename>')
    def custom_static(filename):
        return send_from_directory('icons', filename)
        
    @app.route('/ping')
    def ping():
        """Endpoint de prueba para verificar que el servidor está funcionando."""
        return jsonify({"message": "pong"}), 200
    
    @app.route('/sdn-manager')
    def sdn_manager():
        """Sirve la plantilla sdn_manager.html (si aplica)."""
        return render_template('sdn_manager.html')
    
    # Manejo de errores
    @app.errorhandler(404)
    def not_found(error):
        """Manejador para rutas no encontradas (404)."""
        return jsonify({"error": "Ruta no encontrada"}), 404

    @app.teardown_appcontext
    def close_db(error):
        """
        Cierra la conexión a la base de datos al finalizar el contexto de la aplicación.
        """
        db = g.pop('db', None)
        if db is not None:
            db.close()

    return app

# Bloque para ejecutar la aplicación directamente
if __name__ == '__main__':
    app = create_app()
    # Ejecuta el servidor Flask en modo de depuración.
    # host='0.0.0.0' hace que el servidor sea accesible desde cualquier IP.
    # port=5000 es el puerto predeterminado de Flask.
    app.run(host='0.0.0.0', port=5000, debug=True)


from flask import Flask, jsonify, send_from_directory, render_template, request, g
from flask_cors import CORS
import logging

# Blueprints
from routes.topology import topology_bp
from routes import config, stats
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


def get_db():
    if 'db' not in g:
        g.db = psycopg2.connect(Config.get_db_uri())
    return g.db

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    

    # CORS: permitir sólo orígenes confiables
    CORS(app, resources={r"/*": {"origins": "*"}})




    # Registro de Blueprints
    app.register_blueprint(topology_bp, url_prefix='/topology')
    app.register_blueprint(config.bp, url_prefix='/config')
    app.register_blueprint(stats.bp, url_prefix='/stats')
    app.register_blueprint(reglas_bp, url_prefix='/reglas')
    app.register_blueprint(video_bp, url_prefix='/config/video')
    app.register_blueprint(servers_bp, url_prefix='/servers')
    


    # Rutas utilitarias
    @app.route('/')
    def index():
        return send_from_directory('.', 'index.html')
    @app.route('/ping')
    def ping():
        return jsonify({"message": "pong"}), 200
    
    @app.route('/sdn-manager')
    def sdn_manager():
        return render_template('sdn_manager.html')
    
    # Manejo de errores
    @app.errorhandler(404)
    def not_found(error):
        return jsonify({"error": "Ruta no encontrada"}), 404

    @app.errorhandler(500)
    def internal_error(error):
        return jsonify({"error": "Error interno del servidor"}), 500

    return app


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    app = create_app()
    app.run(host='0.0.0.0', port=5000, debug=True)

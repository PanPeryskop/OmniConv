import os
from flask import Flask
from flask_cors import CORS

from .config import Config


def cleanup_folder(folder_path):
    if os.path.exists(folder_path):
        for filename in os.listdir(folder_path):
            file_path = os.path.join(folder_path, filename)
            try:
                if os.path.isfile(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    import shutil
                    shutil.rmtree(file_path)
            except:
                pass


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    CORS(app)
    
    from .routes.websocket import init_socketio
    socketio = init_socketio(app)
    app.socketio = socketio
    
    cleanup_folder(app.config['UPLOAD_FOLDER'])
    cleanup_folder(app.config['OUTPUT_FOLDER'])
    
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)
    
    from .routes.views import views_bp
    from .routes.api import api_bp
    
    app.register_blueprint(views_bp)
    app.register_blueprint(api_bp, url_prefix='/api')
    
    from .routes.swagger import swagger_bp
    app.register_blueprint(swagger_bp, url_prefix='/api')
    
    from .routes.youtube import youtube_bp
    app.register_blueprint(youtube_bp)
    
    from .utils.exceptions import register_error_handlers
    register_error_handlers(app)
    
    @app.context_processor
    def inject_network_info():
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('10.255.255.255', 1))
            local_ip = s.getsockname()[0]
            s.close()
        except:
            local_ip = '127.0.0.1'
        return dict(local_ip=local_ip)
    
    return app

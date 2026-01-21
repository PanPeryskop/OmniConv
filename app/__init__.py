import os
from flask import Flask
from flask_cors import CORS

from .config import Config


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    CORS(app)
    
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)
    
    from .routes.views import views_bp
    from .routes.api import api_bp
    
    app.register_blueprint(views_bp)
    app.register_blueprint(api_bp, url_prefix='/api')
    
    from .utils.exceptions import register_error_handlers
    register_error_handlers(app)
    
    return app

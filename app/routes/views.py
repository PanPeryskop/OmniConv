from flask import Blueprint, render_template, session, jsonify, send_from_directory, current_app
import json
import os
from datetime import datetime

views_bp = Blueprint('views', __name__)


@views_bp.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(current_app.root_path, 'static'),
                               'ico.ico', mimetype='image/vnd.microsoft.icon')


@views_bp.route('/')
def index():
    return render_template('index.html')


@views_bp.route('/batch')
def batch():
    return render_template('batch.html')


@views_bp.route('/compress')
def compress():
    return render_template('compress.html')


@views_bp.route('/about')
def about():
    from ..services import (
        AudioConverter, 
        VideoConverter, 
        ImageConverter, 
        DocumentConverter,
        OCRService
    )
    
    formats = {
        'audio': {
            'input': sorted(AudioConverter.get_supported_input_formats()),
            'output': sorted(AudioConverter.get_supported_output_formats())
        },
        'video': {
            'input': sorted(VideoConverter.get_supported_input_formats()),
            'output': sorted(VideoConverter.get_supported_output_formats())
        },
        'image': {
            'input': sorted(ImageConverter.get_supported_input_formats()),
            'output': sorted(ImageConverter.get_supported_output_formats())
        },
        'document': {
            'input': sorted(DocumentConverter.get_supported_input_formats()),
            'output': sorted(DocumentConverter.get_supported_output_formats())
        },
        'ocr': {
            'input': sorted(OCRService.get_supported_input_formats()),
            'output': sorted(OCRService.get_supported_output_formats())
        }
    }
    
    return render_template('about.html', formats=formats)


@views_bp.route('/dashboard')
def dashboard():
    from ..services.stats import stats_service
    stats = stats_service.get_stats()
    return render_template('dashboard.html', stats=stats)

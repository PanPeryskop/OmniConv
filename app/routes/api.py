from flask import Blueprint, current_app
from werkzeug.exceptions import RequestEntityTooLarge
from .api_common import api_response
from .api_convert import convert_bp
from .api_compress import compress_bp
from .api_pdf import pdf_bp

api_bp = Blueprint('api', __name__)

api_bp.register_blueprint(convert_bp)
api_bp.register_blueprint(compress_bp)
api_bp.register_blueprint(pdf_bp)

@api_bp.errorhandler(RequestEntityTooLarge)
def handle_file_too_large(e):
    max_size = current_app.config.get('MAX_CONTENT_LENGTH', 0) / (1024 * 1024)
    return api_response(error={'type': 'FileTooLargeError', 'message': f'File exceeds maximum size of {max_size:.0f}MB'}, success=False), 413

@api_bp.route('/capabilities', methods=['GET'])
def get_capabilities():
    from ..services import (
        AudioConverter, VideoConverter, ImageConverter, DocumentConverter, OCRService,
        VideoCompressor, AudioCompressor, ImageCompressor, PdfCompressor
    )
    capabilities = {
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
        },
        'compress': {
            'input': sorted(
                VideoCompressor.get_supported_formats()
                | AudioCompressor.get_supported_formats()
                | ImageCompressor.get_supported_formats()
                | PdfCompressor.get_supported_formats()
            ),
            'pdf_modes': ['lossless', 'balanced', 'strong', 'extreme', 'target']
        }
    }
    return api_response(data=capabilities)

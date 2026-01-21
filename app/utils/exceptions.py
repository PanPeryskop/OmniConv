from flask import jsonify


class ConversionError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class UnsupportedFormatError(ConversionError):
    def __init__(self, format_type: str, supported: list = None):
        message = f"Unsupported format: {format_type}"
        if supported:
            message += f". Supported formats: {', '.join(supported)}"
        super().__init__(message, 400)


class FileTooLargeError(ConversionError):
    def __init__(self, max_size_mb: int):
        message = f"File exceeds maximum size limit of {max_size_mb}MB"
        super().__init__(message, 413)


class FileNotFoundError(ConversionError):
    def __init__(self, file_id: str):
        message = f"File not found: {file_id}"
        super().__init__(message, 404)


class PasswordRequiredError(ConversionError):
    def __init__(self):
        message = "Password required for encrypted PDF"
        super().__init__(message, 401)


class InvalidPasswordError(ConversionError):
    def __init__(self):
        message = "Invalid password for encrypted PDF"
        super().__init__(message, 401)


class OCRError(ConversionError):
    def __init__(self, detail: str = None):
        message = "OCR processing failed"
        if detail:
            message += f": {detail}"
        super().__init__(message, 500)


class ConversionJobNotFoundError(ConversionError):
    def __init__(self, job_id: str):
        message = f"Conversion job not found: {job_id}"
        super().__init__(message, 404)


def register_error_handlers(app):
    @app.errorhandler(ConversionError)
    def handle_conversion_error(error):
        response = {
            'success': False,
            'error': {
                'type': error.__class__.__name__,
                'message': error.message
            },
            'data': None
        }
        return jsonify(response), error.status_code
    
    @app.errorhandler(413)
    def handle_file_too_large(error):
        response = {
            'success': False,
            'error': {
                'type': 'FileTooLargeError',
                'message': 'File exceeds maximum upload size'
            },
            'data': None
        }
        return jsonify(response), 413
    
    @app.errorhandler(404)
    def handle_not_found(error):
        response = {
            'success': False,
            'error': {
                'type': 'NotFoundError',
                'message': 'Resource not found'
            },
            'data': None
        }
        return jsonify(response), 404
    
    @app.errorhandler(500)
    def handle_internal_error(error):
        response = {
            'success': False,
            'error': {
                'type': 'InternalError',
                'message': 'An internal error occurred. Please try again.'
            },
            'data': None
        }
        return jsonify(response), 500

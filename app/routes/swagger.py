from flask import Blueprint, jsonify, render_template

swagger_bp = Blueprint('swagger', __name__)

@swagger_bp.route('/docs')
def swagger_ui():
    return render_template('api_docs.html')

@swagger_bp.route('/swagger.json')
def swagger_spec():
    spec = {
        "openapi": "3.0.0",
        "info": {
            "title": "OmniConv API",
            "version": "1.0.0",
            "description": "Universal AI-Powered File Converter API"
        },
        "servers": [
            {"url": "/api", "description": "Local API Server"}
        ],
        "paths": {
            "/convert": {
                "post": {
                    "summary": "Start a file conversion",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "file_id": {"type": "string"},
                                        "output_format": {"type": "string"},
                                        "options": {"type": "object"}
                                    }
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "Conversion started",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "success": {"type": "boolean"},
                                            "data": {
                                                "type": "object",
                                                "properties": {
                                                    "job_id": {"type": "string"},
                                                    "status": {"type": "string"}
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            },
            "/upload": {
                "post": {
                    "summary": "Upload a file",
                    "requestBody": {
                        "content": {
                            "multipart/form-data": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "file": {"type": "string", "format": "binary"}
                                    }
                                }
                            }
                        }
                    },
                    "responses": {
                        "200": {
                            "description": "File uploaded"
                        }
                    }
                }
            },
            "/status/{job_id}": {
                "get": {
                    "summary": "Get job status",
                    "parameters": [
                        {"name": "job_id", "in": "path", "required": True, "schema": {"type": "string"}}
                    ],
                    "responses": {
                        "200": {
                            "description": "Job status"
                        }
                    }
                }
            }
        }
    }
    return jsonify(spec)

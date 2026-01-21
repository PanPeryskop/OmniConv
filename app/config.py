import os
from pathlib import Path


class Config:
    BASE_DIR = Path(__file__).parent.parent
    UPLOAD_FOLDER = BASE_DIR / 'uploads'
    OUTPUT_FOLDER = BASE_DIR / 'outputs'
    
    SECRET_KEY = os.environ.get('SECRET_KEY', 'omniconv-secret-key-change-in-production')
    MAX_CONTENT_LENGTH = 500 * 1024 * 1024
    
    AUDIO_INPUT = {'mp3', 'wav', 'ogg', 'flac', 'm4a', 'aac', 'ac3', 'alac', 
                   'dts', 'eac3', 'tta', 'wv', 'aiff', 'ape', 'wma', 'opus'}
    AUDIO_OUTPUT = {'mp3', 'wav', 'ogg', 'flac', 'm4a', 'aiff'}  # AAC disabled - not working
    
    VIDEO_INPUT = {'mp4', 'avi', 'mkv', 'mov', 'wmv', 'flv', 'webm', 
                   '3gp', 'mpeg', 'mpg', 'm4v', 'ts', 'mts', 'vob'}
    VIDEO_OUTPUT = {'mp4', 'webm', 'avi', 'mkv', 'mov', 'gif'}
    
    IMAGE_INPUT = {'jpg', 'jpeg', 'png', 'gif', 'bmp', 'tiff', 'tif', 
                   'webp', 'ico', 'heic', 'heif'}
    IMAGE_OUTPUT = {'png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp', 'tiff', 'ico', 'pdf'}
    
    DOCUMENT_INPUT = {'pdf'}
    DOCUMENT_OUTPUT = {'docx', 'txt'}  # pdf_ocr disabled - OCR not working
    
    OCR_ENABLED = False  # OCR disabled - not working
    OCR_DEFAULT_LANG = 'en'
    
    CLEANUP_AFTER_HOURS = 1


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False
    SECRET_KEY = os.environ.get('SECRET_KEY')

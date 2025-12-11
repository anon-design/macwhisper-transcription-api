#!/usr/bin/env python3
"""
Configuración para MacWhisper Transcription API
"""
import os
from pathlib import Path

# Directorio base del proyecto
BASE_DIR = Path(__file__).parent.parent

# Servidor HTTP
HOST = "0.0.0.0"
PORT = 3001  # Puerto diferente a Parakeet API (3000)

# Ruta de carpeta vigilada (MacWhisper guarda los .txt en el mismo folder)
WATCHED_FOLDER = BASE_DIR / "watched_input"

# MacWhisper Configuration
# Nota: Estos valores deben configurarse manualmente en MacWhisper Settings
# - Watch Folder: {WATCHED_FOLDER}
# - Output Format: Plain Text (.txt)
# - Output Location: Same as source (MacWhisper guarda el .txt junto al audio)
# - Auto-Transcribe: Enabled

# Queue System
MAX_CONCURRENT_JOBS = 2  # Máximo de transcripciones simultáneas
MAX_QUEUE_SIZE = 50  # Máximo de jobs en cola
JOB_TIMEOUT = 600  # 10 minutos timeout por job
POLLING_INTERVAL = 0.5  # Segundos entre polls para detectar output

# Rate Limiting
RATE_LIMIT_PER_MINUTE = 10  # Requests por minuto por IP
RATE_LIMIT_WINDOW = 60  # Ventana en segundos

# File Validation
SUPPORTED_FORMATS = ['mp3', 'wav', 'm4a', 'flac', 'ogg', 'opus', 'webm', 'aac']
MAX_FILE_SIZE_MB = 500  # 500MB max
MAX_AUDIO_DURATION = 7200  # 2 horas max (en segundos)

# Job Management
JOB_RETENTION_TIME = 3600  # 1 hora - tiempo que se mantienen jobs completados en memoria
CLEANUP_INTERVAL = 300  # 5 minutos - intervalo para limpiar jobs viejos

# File Cleanup Configuration
KEEP_AUDIO_FILES = True  # True = conservar audios, False = borrarlos después de procesar
KEEP_TRANSCRIPTION_FILES = True  # True = conservar .txt, False = borrarlos después de procesar
ARCHIVE_FOLDER = BASE_DIR / "audio_archive"  # Folder donde se mueven los archivos procesados (si KEEP_* = True)

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = "json"  # json o text

# Output Parser
# MacWhisper genera archivos .txt con el texto transcrito
# Formato esperado: archivo de texto plano con la transcripción
OUTPUT_FILE_EXTENSION = ".txt"

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

# Rutas de carpetas vigiladas
WATCHED_INPUT_DIR = BASE_DIR / "watched_input"
WATCHED_OUTPUT_DIR = BASE_DIR / "watched_output"

# MacWhisper Configuration
# Nota: Estos valores deben configurarse manualmente en MacWhisper Settings
# - Watch Folder: {WATCHED_INPUT_DIR}
# - Output Format: Plain Text (.txt)
# - Output Location: {WATCHED_OUTPUT_DIR} (si es configurable)
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

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = "json"  # json o text

# Output Parser
# MacWhisper genera archivos .txt con el texto transcrito
# Formato esperado: archivo de texto plano con la transcripción
OUTPUT_FILE_EXTENSION = ".txt"

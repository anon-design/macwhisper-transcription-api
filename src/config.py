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
# Usando el folder de MacWhisper del usuario
# MacWhisper usa el MISMO folder para input y output
WATCHED_INPUT_DIR = Path("/Users/transcriptionserver/MacwhisperWatched")
WATCHED_OUTPUT_DIR = Path("/Users/transcriptionserver/MacwhisperWatched")

# Alias para compatibilidad con código existente
WATCHED_FOLDER = WATCHED_INPUT_DIR

# MacWhisper Configuration
# Nota: Estos valores deben configurarse manualmente en MacWhisper Settings
# - Watch Folder: {WATCHED_INPUT_DIR}
# - Output Format: Plain Text (.txt)
# - Output Location: Same as source (MacWhisper guarda el .txt junto al audio)
# - Auto-Transcribe: Enabled

# Queue System
MAX_CONCURRENT_JOBS = 1  # Máximo de transcripciones simultáneas
MAX_QUEUE_SIZE = 50  # Máximo de jobs en cola

# Timeouts - OPTIMIZADOS para respuesta rápida
# Para un archivo de 1MB: 60 + (1 * 30) = 90 segundos
# Para un archivo de 10MB: 60 + (10 * 30) = 360 segundos (6 min)
MIN_JOB_TIMEOUT = 60  # 1 minuto mínimo (archivos pequeños)
JOB_TIMEOUT = 60  # Base timeout en segundos (era 600)
JOB_TIMEOUT_PER_MB = 30  # Segundos adicionales por MB (era 10)
MAX_JOB_TIMEOUT = 600  # 10 minutos máximo (era 1800)

MAX_RETRIES = 2  # Número máximo de reintentos para jobs con timeout
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
LOG_TO_FILE = True  # Habilitar logging a archivo
LOG_DIR = BASE_DIR / "logs"
LOG_FILE_MAX_BYTES = 10 * 1024 * 1024  # 10 MB por archivo
LOG_FILE_BACKUP_COUNT = 7  # Mantener últimos 7 archivos (1 semana si rotación diaria)

# Output Parser
# MacWhisper genera archivos .txt con el texto transcrito
# Formato esperado: archivo de texto plano con la transcripción
OUTPUT_FILE_EXTENSION = ".txt"

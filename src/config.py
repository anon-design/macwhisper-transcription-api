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
WATCHED_INPUT_DIR = Path("/Users/JC/MacwhisperWatched")
WATCHED_OUTPUT_DIR = Path("/Users/JC/MacwhisperWatched")

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

# Timeouts - SINCRONIZADOS con cliente (Mediclic backend)
#
# ARQUITECTURA DE TIMEOUTS:
# - Cliente tiene timeout DINÁMICO: base 15s + 30s/MB, max 600s
# - API tiene timeout DINÁMICO: base 12s + 25s/MB, max 540s
# - API timeout es ~10% menor para dar margen al cliente
#
# EJEMPLOS:
# ┌──────────────┬──────────┬────────────────┬────────────────┐
# │ Duración     │ Tamaño   │ Cliente (max)  │ API (interno)  │
# ├──────────────┼──────────┼────────────────┼────────────────┤
# │ 1 minuto     │ 0.1 MB   │ 18s            │ 14.5s          │
# │ 10 minutos   │ 1 MB     │ 45s            │ 37s            │
# │ 30 minutos   │ 3 MB     │ 105s           │ 87s            │
# │ 1 hora       │ 6 MB     │ 195s           │ 162s           │
# │ 2 horas      │ 12 MB    │ 375s           │ 312s           │
# │ 5+ horas     │ 30+ MB   │ 600s (max)     │ 540s (max)     │
# └──────────────┴──────────┴────────────────┴────────────────┘
#
MIN_JOB_TIMEOUT = 12  # 12 segundos mínimo (archivos pequeños)
JOB_TIMEOUT = 12  # Base timeout en segundos
JOB_TIMEOUT_PER_MB = 25  # Segundos adicionales por MB
MAX_JOB_TIMEOUT = 540  # 9 minutos máximo (10% menos que cliente)

# SIN reintentos internos - el cliente (Mediclic) hace el failover entre servidores
# Si MacWhisper falla, es mejor retornar error rápido y dejar que el cliente
# haga failover a M1 Pro o Groq, en lugar de reintentar internamente
MAX_RETRIES = 0
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

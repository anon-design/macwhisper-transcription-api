#!/usr/bin/env python3
"""
Sistema de monitoreo para MacWhisper y detección de problemas
"""
import os
import time
import psutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from src import config
from src.logger import get_logger

logger = get_logger()


def is_macwhisper_running() -> Tuple[bool, Optional[int]]:
    """
    Verifica si MacWhisper está corriendo

    Returns:
        Tuple[bool, Optional[int]]: (is_running, pid)
    """
    try:
        for proc in psutil.process_iter(['pid', 'name']):
            if 'MacWhisper' in proc.info['name']:
                return True, proc.info['pid']
        return False, None
    except Exception as e:
        logger.error(f"Error checking MacWhisper status: {e}")
        return False, None


def get_macwhisper_info() -> Dict:
    """
    Obtiene información detallada de MacWhisper

    Returns:
        Dict: Información de estado, memoria, CPU, etc.
    """
    is_running, pid = is_macwhisper_running()

    if not is_running:
        return {
            "running": False,
            "pid": None,
            "status": "not_running",
            "error": "MacWhisper process not found"
        }

    try:
        proc = psutil.Process(pid)

        # Obtener info del proceso
        with proc.oneshot():
            memory_info = proc.memory_info()
            cpu_percent = proc.cpu_percent(interval=0.1)
            create_time = proc.create_time()
            uptime = time.time() - create_time

        return {
            "running": True,
            "pid": pid,
            "status": "healthy",
            "uptime_seconds": round(uptime, 2),
            "uptime_hours": round(uptime / 3600, 2),
            "memory_mb": round(memory_info.rss / (1024 * 1024), 2),
            "cpu_percent": round(cpu_percent, 2),
            "num_threads": proc.num_threads()
        }

    except psutil.NoSuchProcess:
        return {
            "running": False,
            "pid": pid,
            "status": "process_died",
            "error": "Process existed but died during check"
        }
    except Exception as e:
        logger.error(f"Error getting MacWhisper info: {e}")
        return {
            "running": is_running,
            "pid": pid,
            "status": "error",
            "error": str(e)
        }


def check_orphaned_files() -> Dict:
    """
    Detecta archivos de audio sin su correspondiente transcripción .txt

    Returns:
        Dict: Lista de archivos huérfanos y estadísticas
    """
    try:
        input_dir = config.WATCHED_INPUT_DIR

        if not input_dir.exists():
            return {
                "orphaned_files": [],
                "count": 0,
                "error": "Input directory does not exist"
            }

        # Obtener todos los archivos de audio
        audio_extensions = config.SUPPORTED_FORMATS
        audio_files = []
        for ext in audio_extensions:
            audio_files.extend(input_dir.glob(f"*.{ext}"))

        # Obtener todos los archivos .txt
        txt_files = set(f.stem for f in input_dir.glob("*.txt"))

        # Detectar huérfanos (archivos de audio sin .txt correspondiente)
        orphaned = []
        for audio_file in audio_files:
            if audio_file.stem not in txt_files:
                file_stat = audio_file.stat()
                age_seconds = time.time() - file_stat.st_mtime

                orphaned.append({
                    "filename": audio_file.name,
                    "size_mb": round(file_stat.st_size / (1024 * 1024), 2),
                    "age_seconds": round(age_seconds, 2),
                    "age_minutes": round(age_seconds / 60, 2),
                    "modified_at": file_stat.st_mtime
                })

        # Ordenar por edad (más viejos primero)
        orphaned.sort(key=lambda x: x['age_seconds'], reverse=True)

        if orphaned:
            logger.warning(
                f"Found {len(orphaned)} orphaned files",
                count=len(orphaned),
                files=[f['filename'] for f in orphaned]
            )

        return {
            "orphaned_files": orphaned,
            "count": len(orphaned),
            "total_audio_files": len(audio_files),
            "total_txt_files": len(txt_files)
        }

    except Exception as e:
        logger.error(f"Error checking orphaned files: {e}")
        return {
            "orphaned_files": [],
            "count": 0,
            "error": str(e)
        }


def cleanup_old_files(max_age_hours: int = 24) -> Dict:
    """
    Limpia archivos antiguos de la carpeta watched

    Args:
        max_age_hours: Edad máxima en horas antes de limpiar

    Returns:
        Dict: Estadísticas de limpieza
    """
    try:
        input_dir = config.WATCHED_INPUT_DIR
        cutoff_time = time.time() - (max_age_hours * 3600)

        cleaned_files = []
        total_size_mb = 0

        for file_path in input_dir.glob("*"):
            if file_path.is_file():
                file_stat = file_path.stat()

                if file_stat.st_mtime < cutoff_time:
                    size_mb = file_stat.st_size / (1024 * 1024)
                    cleaned_files.append({
                        "filename": file_path.name,
                        "size_mb": round(size_mb, 2),
                        "age_hours": round((time.time() - file_stat.st_mtime) / 3600, 2)
                    })

                    total_size_mb += size_mb
                    file_path.unlink()

        if cleaned_files:
            logger.info(
                f"Cleaned {len(cleaned_files)} old files",
                count=len(cleaned_files),
                total_size_mb=round(total_size_mb, 2)
            )

        return {
            "cleaned_files": cleaned_files,
            "count": len(cleaned_files),
            "total_size_mb": round(total_size_mb, 2),
            "max_age_hours": max_age_hours
        }

    except Exception as e:
        logger.error(f"Error cleaning old files: {e}")
        return {
            "cleaned_files": [],
            "count": 0,
            "error": str(e)
        }


def get_watched_folder_stats() -> Dict:
    """
    Obtiene estadísticas de la carpeta watched

    Returns:
        Dict: Estadísticas de archivos en la carpeta
    """
    try:
        input_dir = config.WATCHED_INPUT_DIR

        if not input_dir.exists():
            return {"error": "Input directory does not exist"}

        # Contar archivos por tipo
        audio_count = 0
        txt_count = 0
        other_count = 0
        total_size_mb = 0

        audio_extensions = config.SUPPORTED_FORMATS

        for file_path in input_dir.glob("*"):
            if file_path.is_file():
                size_mb = file_path.stat().st_size / (1024 * 1024)
                total_size_mb += size_mb

                ext = file_path.suffix.lower().lstrip('.')
                if ext in audio_extensions:
                    audio_count += 1
                elif ext == 'txt':
                    txt_count += 1
                else:
                    other_count += 1

        return {
            "total_files": audio_count + txt_count + other_count,
            "audio_files": audio_count,
            "txt_files": txt_count,
            "other_files": other_count,
            "total_size_mb": round(total_size_mb, 2),
            "path": str(input_dir)
        }

    except Exception as e:
        logger.error(f"Error getting folder stats: {e}")
        return {"error": str(e)}


def calculate_dynamic_timeout(file_size_mb: float) -> int:
    """
    Calcula el timeout dinámico basado en el tamaño del archivo.

    SINCRONIZADO con cliente (Mediclic backend) que tiene timeout de 15s.
    La API debe responder ANTES para evitar failover innecesario a Groq.

    Fórmula: base + (size_mb * per_mb)
    Ejemplo para 0.1MB: 10 + (0.1 * 15) = 11.5 segundos
    Ejemplo para 1MB: 10 + (1 * 15) = 25 segundos
    Ejemplo para 5MB: 10 + (5 * 15) = 85 -> capped at 60 segundos

    Args:
        file_size_mb: Tamaño del archivo en MB

    Returns:
        int: Timeout en segundos (entre MIN y MAX)
    """
    base_timeout = config.JOB_TIMEOUT
    extra_time = file_size_mb * config.JOB_TIMEOUT_PER_MB
    timeout = int(base_timeout + extra_time)

    # Asegurar mínimo (para archivos muy pequeños)
    min_timeout = getattr(config, 'MIN_JOB_TIMEOUT', 60)
    timeout = max(timeout, min_timeout)

    # No exceder el máximo
    return min(timeout, config.MAX_JOB_TIMEOUT)

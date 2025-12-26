#!/usr/bin/env python3
"""
Sistema de logging estructurado
"""
import logging
import sys
import json
from datetime import datetime
from pathlib import Path
from logging.handlers import RotatingFileHandler
from typing import Optional, Dict, Any
from src import config


class StructuredLogger:
    """Logger con salida estructurada (JSON) y formato legible"""

    def __init__(
        self,
        name: str = "macwhisper-api",
        level: int = logging.INFO,
        structured: bool = False
    ):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)
        self.structured = structured

        # Evitar duplicar handlers
        if not self.logger.handlers:
            # Handler para stdout (consola)
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(level)

            if structured:
                console_handler.setFormatter(JSONFormatter())
            else:
                # Formato legible para humanos
                formatter = logging.Formatter(
                    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S'
                )
                console_handler.setFormatter(formatter)

            self.logger.addHandler(console_handler)

            # Handler para archivo (si está habilitado)
            if config.LOG_TO_FILE:
                try:
                    # Crear directorio de logs si no existe
                    config.LOG_DIR.mkdir(parents=True, exist_ok=True)

                    # Archivo de log con rotación
                    log_file = config.LOG_DIR / "api.log"

                    file_handler = RotatingFileHandler(
                        log_file,
                        maxBytes=config.LOG_FILE_MAX_BYTES,
                        backupCount=config.LOG_FILE_BACKUP_COUNT
                    )
                    file_handler.setLevel(level)

                    # Siempre usar formato estructurado en archivo para facilitar parsing
                    file_handler.setFormatter(JSONFormatter())

                    self.logger.addHandler(file_handler)

                    # Log sin contexto extra para evitar errores durante inicialización
                    self.logger.info(f"File logging enabled: {log_file}")

                except Exception as e:
                    # Si falla el file logging, continuar con console logging
                    self.logger.error(f"Failed to setup file logging: {e}")

    def _log(
        self,
        level: int,
        message: str,
        **context: Any
    ) -> None:
        """Log con contexto adicional"""
        if context:
            # Si hay contexto, incluirlo en extra
            self.logger.log(level, message, extra={'context': context})
        else:
            self.logger.log(level, message)

    def info(self, message: str, **context: Any) -> None:
        """Log nivel INFO"""
        self._log(logging.INFO, message, **context)

    def warning(self, message: str, **context: Any) -> None:
        """Log nivel WARNING"""
        self._log(logging.WARNING, message, **context)

    def error(self, message: str, **context: Any) -> None:
        """Log nivel ERROR"""
        self._log(logging.ERROR, message, **context)

    def debug(self, message: str, **context: Any) -> None:
        """Log nivel DEBUG"""
        self._log(logging.DEBUG, message, **context)

    def log_request(
        self,
        method: str,
        path: str,
        status: int,
        duration_ms: float,
        **extra: Any
    ) -> None:
        """Log de request HTTP"""
        self.info(
            f"{method} {path} -> {status}",
            method=method,
            path=path,
            status=status,
            duration_ms=duration_ms,
            **extra
        )

    def log_transcription(
        self,
        job_id: str,
        duration_sec: float,
        words: int,
        rtf: float,
        **extra: Any
    ) -> None:
        """Log de transcripción completada"""
        self.info(
            f"Transcription {job_id[:8]}... completed",
            job_id=job_id,
            duration_sec=duration_sec,
            words=words,
            rtf=rtf,
            **extra
        )


class JSONFormatter(logging.Formatter):
    """Formatter que serializa logs a JSON"""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            'timestamp': datetime.utcnow().isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
        }

        # Añadir contexto extra si existe
        if hasattr(record, 'context'):
            log_data['context'] = record.context

        # Añadir info de excepción si existe
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)

        return json.dumps(log_data)


# Logger global singleton
_global_logger: Optional[StructuredLogger] = None


def get_logger() -> StructuredLogger:
    """Obtiene el logger global singleton"""
    global _global_logger

    if _global_logger is None:
        _global_logger = StructuredLogger()

    return _global_logger

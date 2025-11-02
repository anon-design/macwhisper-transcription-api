#!/usr/bin/env python3
"""
Sistema de logging estructurado
"""
import logging
import sys
import json
from datetime import datetime
from typing import Optional, Dict, Any


class StructuredLogger:
    """Logger con salida estructurada (JSON) y formato legible"""

    def __init__(
        self,
        name: str = "parakeet-api",
        level: int = logging.INFO,
        structured: bool = False
    ):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)
        self.structured = structured

        # Evitar duplicar handlers
        if not self.logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setLevel(level)

            if structured:
                handler.setFormatter(JSONFormatter())
            else:
                # Formato legible para humanos
                formatter = logging.Formatter(
                    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S'
                )
                handler.setFormatter(formatter)

            self.logger.addHandler(handler)

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

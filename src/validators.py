#!/usr/bin/env python3
"""
Validadores para archivos de audio y requests
"""
import os
import mimetypes
from pathlib import Path
from typing import Optional, Tuple
from src import config


class ValidationError(Exception):
    """Error de validación personalizado"""
    pass


class AudioValidator:
    """Validador de archivos de audio"""

    @staticmethod
    def validate_file_exists(file_path: str) -> None:
        """Valida que el archivo existe"""
        if not os.path.exists(file_path):
            raise ValidationError(f"Archivo no encontrado: {file_path}")

    @staticmethod
    def validate_file_size(file_path: str, max_size_mb: int = None) -> None:
        """Valida el tamaño del archivo"""
        max_size = max_size_mb or config.MAX_FILE_SIZE_MB
        file_size = os.path.getsize(file_path)
        file_size_mb = file_size / (1024 * 1024)

        if file_size_mb > max_size:
            raise ValidationError(
                f"Archivo demasiado grande: {file_size_mb:.1f}MB. "
                f"Máximo permitido: {max_size}MB"
            )

    @staticmethod
    def validate_audio_format(file_path: str, original_filename: Optional[str] = None) -> str:
        """
        Valida que el archivo sea un formato de audio soportado

        Args:
            file_path: Ruta al archivo (puede ser temporal sin extensión)
            original_filename: Nombre original del archivo (con extensión)

        Returns:
            str: Formato detectado (mp3, wav, etc.)
        """
        # Si tenemos el nombre original, usarlo primero
        if original_filename:
            ext = Path(original_filename).suffix.lower().lstrip('.')
            if ext in config.SUPPORTED_FORMATS:
                return ext

        # Intentar detectar por extensión del archivo
        ext = Path(file_path).suffix.lower().lstrip('.')

        if ext in config.SUPPORTED_FORMATS:
            return ext

        # Intentar detectar por MIME type
        mime_type, _ = mimetypes.guess_type(original_filename or file_path)

        if mime_type and mime_type.startswith('audio/'):
            # Extraer formato del MIME type
            format_name = mime_type.split('/')[-1]
            if format_name in config.SUPPORTED_FORMATS:
                return format_name

        raise ValidationError(
            f"Formato de audio no soportado. "
            f"Formatos válidos: {', '.join(config.SUPPORTED_FORMATS)}"
        )

    @staticmethod
    def validate_audio_duration(duration: float) -> None:
        """Valida la duración del audio"""
        if duration <= 0:
            raise ValidationError("Duración de audio inválida: debe ser mayor a 0")

        if duration > config.MAX_AUDIO_DURATION:
            max_duration_min = config.MAX_AUDIO_DURATION / 60
            duration_min = duration / 60
            raise ValidationError(
                f"Audio demasiado largo: {duration_min:.1f} min. "
                f"Máximo permitido: {max_duration_min:.0f} min"
            )

    @staticmethod
    def validate_audio_file(file_path: str, original_filename: Optional[str] = None) -> Tuple[str, float]:
        """
        Validación completa de archivo de audio

        Args:
            file_path: Ruta al archivo (puede ser temporal)
            original_filename: Nombre original del archivo (opcional)

        Returns:
            Tuple[str, float]: (formato, duración estimada)
        """
        # 1. Validar existencia
        AudioValidator.validate_file_exists(file_path)

        # 2. Validar tamaño
        AudioValidator.validate_file_size(file_path)

        # 3. Validar formato
        audio_format = AudioValidator.validate_audio_format(file_path, original_filename)

        # Obtener duración (estimada basada en tamaño de archivo)
        # Nota: Esta es una estimación. La duración real se obtiene con ffprobe
        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)

        # Estimación conservadora: ~1MB por minuto para MP3 a 128kbps
        # Para formatos sin pérdida (WAV, FLAC) la relación es diferente
        if audio_format in ['wav', 'flac']:
            estimated_duration = file_size_mb * 10  # ~10MB por minuto para WAV 16kHz mono
        else:
            estimated_duration = file_size_mb * 60  # ~1MB por minuto para MP3

        return audio_format, estimated_duration


class RequestValidator:
    """Validador de requests HTTP"""

    @staticmethod
    def validate_multipart_field(field, expected_name: str = 'file') -> None:
        """Valida que el campo multipart sea correcto"""
        if not field:
            raise ValidationError(
                f"Campo '{expected_name}' requerido en multipart/form-data"
            )

        if field.name != expected_name:
            raise ValidationError(
                f"Campo esperado: '{expected_name}', recibido: '{field.name}'"
            )

    @staticmethod
    def validate_content_type(content_type: Optional[str]) -> None:
        """Valida el content type del request"""
        if not content_type:
            raise ValidationError("Content-Type header requerido")

        if not content_type.startswith('multipart/form-data'):
            raise ValidationError(
                f"Content-Type inválido: {content_type}. "
                "Se requiere 'multipart/form-data'"
            )


def validate_transcription_request(file_path: str, original_filename: Optional[str] = None) -> dict:
    """
    Validación completa de request de transcripción

    Args:
        file_path: Ruta al archivo temporal
        original_filename: Nombre original del archivo con extensión

    Returns:
        dict: Información de validación (formato, tamaño, etc.)
    """
    try:
        audio_format, estimated_duration = AudioValidator.validate_audio_file(file_path, original_filename)

        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)

        return {
            "valid": True,
            "format": audio_format,
            "file_size_mb": round(file_size_mb, 2),
            "estimated_duration_sec": round(estimated_duration, 1)
        }

    except ValidationError as e:
        return {
            "valid": False,
            "error": str(e)
        }

#!/usr/bin/env python3
"""
Servicio de transcripción usando MacWhisper Watched Folders
"""
import os
import time
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Tuple
from src import config
from src.file_watcher import TranscriptionWatcher
from src.logger import get_logger

logger = get_logger()

# Formatos que MacWhisper acepta en watched folder (probado)
MACWHISPER_ACCEPTED_FORMATS = {'mp3', 'm4a', 'wav', 'flac', 'aiff', 'aif'}
# Formatos que requieren conversión a MP3
FORMATS_NEEDING_CONVERSION = {'opus', 'ogg', 'webm', 'wma', 'amr', 'aac'}


def check_ffmpeg_available() -> bool:
    """Verifica si ffmpeg está disponible en el sistema"""
    try:
        # Probar primero con homebrew path
        result = subprocess.run(
            ['/opt/homebrew/bin/ffmpeg', '-version'],
            capture_output=True,
            timeout=5
        )
        return result.returncode == 0
    except:
        try:
            # Probar path normal
            result = subprocess.run(
                ['ffmpeg', '-version'],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except:
            return False


def get_ffmpeg_path() -> str:
    """Obtiene la ruta de ffmpeg"""
    if os.path.exists('/opt/homebrew/bin/ffmpeg'):
        return '/opt/homebrew/bin/ffmpeg'
    return 'ffmpeg'


def convert_to_mp3(input_path: str, output_path: str) -> bool:
    """
    Convierte un archivo de audio a MP3 usando ffmpeg

    Args:
        input_path: Ruta del archivo de entrada
        output_path: Ruta del archivo MP3 de salida

    Returns:
        bool: True si la conversión fue exitosa
    """
    ffmpeg = get_ffmpeg_path()

    try:
        result = subprocess.run(
            [
                ffmpeg,
                '-i', input_path,
                '-acodec', 'libmp3lame',
                '-q:a', '2',  # Alta calidad
                '-y',  # Sobrescribir si existe
                output_path
            ],
            capture_output=True,
            timeout=120  # 2 minutos máximo para conversión
        )

        if result.returncode == 0:
            logger.info(
                "Audio converted to MP3 successfully",
                input=input_path,
                output=output_path
            )
            return True
        else:
            logger.error(
                "ffmpeg conversion failed",
                stderr=result.stderr.decode()[:500]
            )
            return False

    except subprocess.TimeoutExpired:
        logger.error("ffmpeg conversion timed out", input=input_path)
        return False
    except Exception as e:
        logger.error(f"ffmpeg conversion error: {e}", input=input_path)
        return False


class MacWhisperService:
    """
    Servicio que coordina la transcripción usando MacWhisper

    Flujo:
    1. Recibe archivo temporal
    2. Lo mueve a watched_folder/ con UUID en el nombre
    3. Espera a que MacWhisper lo procese (genera .txt en el mismo folder)
    4. Lee el resultado del .txt
    5. Retorna la transcripción
    """

    def __init__(self):
        self.watcher = TranscriptionWatcher()

        # Verificar que la carpeta exista
        config.WATCHED_FOLDER.mkdir(parents=True, exist_ok=True)

        # Verificar ffmpeg para conversión de formatos
        self.ffmpeg_available = check_ffmpeg_available()
        if not self.ffmpeg_available:
            logger.warning(
                "ffmpeg not available - opus/ogg/webm files will fail. "
                "Install with: brew install ffmpeg"
            )

        logger.info(
            "MacWhisperService initialized",
            watched_folder=str(config.WATCHED_FOLDER),
            ffmpeg_available=self.ffmpeg_available
        )

    def transcribe(self, temp_file_path: str, job_id: str, original_filename: str) -> Dict:
        """
        Transcribe un archivo de audio usando MacWhisper

        Args:
            temp_file_path: Ruta al archivo temporal
            job_id: UUID del job
            original_filename: Nombre original del archivo

        Returns:
            Dict: Resultado de la transcripción con estructura similar a Parakeet API
        """
        start_time = time.time()

        try:
            # 1. Mover archivo a watched_input con job_id en el nombre
            input_file = self._copy_to_watched_folder(
                temp_file_path,
                job_id,
                original_filename
            )

            logger.info(
                "File copied to watched folder",
                job_id=job_id,
                input_file=str(input_file)
            )

            # 2. Esperar a que MacWhisper procese el archivo
            # Esto es bloqueante pero async-safe si se llama desde async context
            output_file = self._wait_for_output_sync(job_id)

            if not output_file:
                raise TimeoutError(
                    f"MacWhisper did not produce output within {config.JOB_TIMEOUT}s"
                )

            # 3. Leer el resultado
            text = self.watcher.read_transcription(output_file)

            # 4. Calcular métricas
            processing_time = time.time() - start_time

            # Obtener info del archivo original
            file_size = os.path.getsize(temp_file_path)
            file_size_mb = file_size / (1024 * 1024)

            # Estimar duración de audio (conservador)
            ext = Path(original_filename).suffix.lower().lstrip('.')
            if ext in ['wav', 'flac']:
                estimated_duration = file_size_mb * 10  # ~10MB por minuto para WAV
            else:
                estimated_duration = file_size_mb * 60  # ~1MB por minuto para MP3

            # Calcular RTF (Real-Time Factor)
            rtf = processing_time / estimated_duration if estimated_duration > 0 else 0

            # Calcular palabras
            words = len(text.split()) if text else 0

            result = {
                "text": text,
                "words": words,
                "processing_time": round(processing_time, 2),
                "audio_duration": estimated_duration,  # Estimado
                "rtf": round(rtf, 4),
                "format": ext,
                "file_size_mb": round(file_size_mb, 2),
                "model": "MacWhisper (WhisperKit Pro / Whisper Large V3)",
                "job_id": job_id
            }

            logger.log_transcription(
                job_id=job_id,
                duration_sec=estimated_duration,
                words=words,
                rtf=rtf
            )

            # 5. Limpiar archivos temporales
            self.watcher.cleanup_files(job_id)

            return result

        except Exception as e:
            logger.error(f"Transcription failed: {e}", job_id=job_id)
            # Intentar limpiar archivos
            try:
                self.watcher.cleanup_files(job_id)
            except:
                pass
            raise

    def _copy_to_watched_folder(
        self,
        source_path: str,
        job_id: str,
        original_filename: str
    ) -> Path:
        """
        Copia el archivo al watched folder con job_id en el nombre.
        Si el formato no es aceptado por MacWhisper, lo convierte a MP3.

        Formato: {job_id}_{original_filename}
        Ejemplo: abc123-def456_test.mp3
        """
        ext = Path(original_filename).suffix.lower().lstrip('.')

        # Verificar si necesita conversión a MP3
        if ext in FORMATS_NEEDING_CONVERSION:
            # Cambiar extensión a .mp3
            base_name = Path(original_filename).stem
            dest_filename = f"{job_id}_{base_name}.mp3"
            dest_path = config.WATCHED_FOLDER / dest_filename

            logger.info(
                "Converting audio to MP3 for MacWhisper compatibility",
                job_id=job_id,
                original_format=ext,
                source=source_path
            )

            # Convertir a MP3
            if not convert_to_mp3(source_path, str(dest_path)):
                raise RuntimeError(
                    f"Failed to convert {ext} to MP3. Ensure ffmpeg is installed."
                )

            return dest_path
        else:
            # Formato aceptado, copiar directamente
            dest_filename = f"{job_id}_{original_filename}"
            dest_path = config.WATCHED_FOLDER / dest_filename
            shutil.copy2(source_path, dest_path)
            return dest_path

    def _wait_for_output_sync(self, job_id: str) -> str:
        """
        Versión síncrona de wait_for_output para compatibilidad

        En la versión async del servidor, esto se llamará desde un executor
        """
        import asyncio

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        return loop.run_until_complete(
            self.watcher.wait_for_output(job_id)
        )

    async def transcribe_async(
        self,
        temp_file_path: str,
        job_id: str,
        original_filename: str,
        timeout: float = None
    ) -> Dict:
        """
        Versión asíncrona de transcribe() para uso con aiohttp

        Args:
            temp_file_path: Ruta al archivo temporal
            job_id: UUID del job
            original_filename: Nombre original del archivo
            timeout: Timeout dinámico en segundos (opcional)

        Returns:
            Dict: Resultado de la transcripción
        """
        start_time = time.time()

        # Usar timeout dinámico si se proporciona
        effective_timeout = timeout if timeout is not None else config.JOB_TIMEOUT

        try:
            # 1. Mover archivo a watched_input
            input_file = self._copy_to_watched_folder(
                temp_file_path,
                job_id,
                original_filename
            )

            logger.info(
                "File copied to watched folder",
                job_id=job_id,
                input_file=str(input_file),
                timeout=effective_timeout
            )

            # 2. Esperar output (async) con timeout dinámico y verificación de archivo fuente
            output_file = await self.watcher.wait_for_output(
                job_id,
                source_file=str(input_file),  # Para detectar si se borra
                timeout=effective_timeout
            )

            if not output_file:
                raise TimeoutError(
                    f"MacWhisper did not produce output within {effective_timeout}s"
                )

            # 3. Leer resultado
            text = self.watcher.read_transcription(output_file)

            # 4. Calcular métricas
            processing_time = time.time() - start_time

            file_size = os.path.getsize(temp_file_path)
            file_size_mb = file_size / (1024 * 1024)

            ext = Path(original_filename).suffix.lower().lstrip('.')
            if ext in ['wav', 'flac']:
                estimated_duration = file_size_mb * 10
            else:
                estimated_duration = file_size_mb * 60

            rtf = processing_time / estimated_duration if estimated_duration > 0 else 0
            words = len(text.split()) if text else 0

            result = {
                "text": text,
                "words": words,
                "processing_time": round(processing_time, 2),
                "audio_duration": estimated_duration,
                "rtf": round(rtf, 4),
                "format": ext,
                "file_size_mb": round(file_size_mb, 2),
                "model": "MacWhisper (WhisperKit Pro / Whisper Large V3)",
                "job_id": job_id
            }

            logger.log_transcription(
                job_id=job_id,
                duration_sec=estimated_duration,
                words=words,
                rtf=rtf
            )

            # 5. Limpiar
            self.watcher.cleanup_files(job_id)

            return result

        except Exception as e:
            logger.error(f"Transcription failed: {e}", job_id=job_id)
            try:
                self.watcher.cleanup_files(job_id)
            except:
                pass
            raise

#!/usr/bin/env python3
"""
File watcher para detectar cuando MacWhisper genera archivos de transcripción
"""
import asyncio
import os
import time
from pathlib import Path
from typing import Optional
from src import config
from src.logger import get_logger

logger = get_logger()


class TranscriptionWatcher:
    """
    Monitorea la carpeta watched esperando que aparezcan archivos de transcripción

    MacWhisper deposita archivos .txt en la MISMA carpeta que el audio.
    Esta clase hace polling para detectarlos.
    """

    def __init__(self):
        self.watched_folder = config.WATCHED_FOLDER
        logger.info("TranscriptionWatcher initialized", watched_folder=str(self.watched_folder))

    async def wait_for_output(
        self,
        job_id: str,
        timeout: float = config.JOB_TIMEOUT
    ) -> Optional[str]:
        """
        Espera a que aparezca el archivo de transcripción para un job específico

        Args:
            job_id: UUID del job
            timeout: Timeout en segundos

        Returns:
            Optional[str]: Ruta al archivo de transcripción si se encontró, None si timeout
        """
        start_time = time.time()
        poll_interval = config.POLLING_INTERVAL

        logger.info(
            "Waiting for transcription output",
            job_id=job_id,
            timeout=timeout,
            poll_interval=poll_interval
        )

        while (time.time() - start_time) < timeout:
            # Buscar archivo que contenga el job_id en el nombre
            output_file = self._find_output_file(job_id)

            if output_file and output_file.exists():
                # Verificar que el archivo no esté siendo escrito (esperar a que sea estable)
                if await self._is_file_stable(output_file):
                    logger.info(
                        "Transcription output found",
                        job_id=job_id,
                        file=str(output_file),
                        wait_time=time.time() - start_time
                    )
                    return str(output_file)

            # Esperar antes del siguiente poll
            await asyncio.sleep(poll_interval)

        logger.warning(
            "Timeout waiting for transcription output",
            job_id=job_id,
            timeout=timeout
        )
        return None

    def _find_output_file(self, job_id: str) -> Optional[Path]:
        """
        Busca el archivo de output correspondiente al job_id

        MacWhisper guarda los .txt en la MISMA carpeta que el audio.

        Buscamos por job_id que está incluido en el nombre del archivo
        """
        try:
            # MacWhisper guarda los .txt en la misma carpeta que el audio
            input_dir = config.WATCHED_INPUT_DIR

            # Use os.listdir() instead of Path.glob() to avoid sandboxing issues
            all_files = os.listdir(str(input_dir))
            txt_files = [f for f in all_files if f.endswith('.txt')]
            output_files = [input_dir / f for f in txt_files]

            # Solo loguear si hay archivos para reducir ruido
            if len(output_files) > 0:
                logger.debug(f"Polling: found {len(output_files)} txt files: {[f.name for f in output_files]}", job_id=job_id)

            # Buscar archivo que contenga el job_id
            for output_file in output_files:
                if job_id in output_file.stem:
                    logger.info(f"Match found: {output_file.name}", job_id=job_id)
                    return output_file

            return None

        except Exception as e:
            logger.error(f"Error finding output file: {e}", job_id=job_id)
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}", job_id=job_id)
            return None

    async def _is_file_stable(
        self,
        file_path: Path,
        check_interval: float = 0.5,
        stable_time: float = 1.0
    ) -> bool:
        """
        Verifica que el archivo esté estable (no está siendo escrito)

        Args:
            file_path: Ruta al archivo
            check_interval: Intervalo entre checks
            stable_time: Tiempo que debe permanecer sin cambios

        Returns:
            bool: True si el archivo es estable
        """
        try:
            initial_size = file_path.stat().st_size
            await asyncio.sleep(stable_time)
            final_size = file_path.stat().st_size

            return initial_size == final_size and final_size > 0

        except Exception as e:
            logger.error(f"Error checking file stability: {e}", file=str(file_path))
            return False

    def read_transcription(self, file_path: str) -> str:
        """
        Lee el contenido del archivo de transcripción

        Args:
            file_path: Ruta al archivo .txt

        Returns:
            str: Contenido del archivo
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()

            logger.info(
                "Transcription file read",
                file=file_path,
                chars=len(content)
            )

            return content

        except Exception as e:
            logger.error(f"Error reading transcription file: {e}", file=file_path)
            raise

    def cleanup_files(self, job_id: str):
        """
        Limpia o archiva archivos de audio y transcripción según configuración

        Args:
            job_id: UUID del job
        """
        try:
            files = list(self.watched_folder.glob(f"*{job_id}*"))

            for file in files:
                is_audio = file.suffix.lower() in [f'.{fmt}' for fmt in config.SUPPORTED_FORMATS]
                is_transcription = file.suffix.lower() == '.txt'

                # Determinar si debemos conservar el archivo
                should_keep = (
                    (is_audio and config.KEEP_AUDIO_FILES) or
                    (is_transcription and config.KEEP_TRANSCRIPTION_FILES)
                )

                if should_keep:
                    # Mover a folder de archivo
                    config.ARCHIVE_FOLDER.mkdir(parents=True, exist_ok=True)
                    dest = config.ARCHIVE_FOLDER / file.name

                    # Si existe, agregar timestamp para evitar sobrescribir
                    if dest.exists():
                        import time
                        timestamp = int(time.time())
                        dest = config.ARCHIVE_FOLDER / f"{file.stem}_{timestamp}{file.suffix}"

                    file.rename(dest)
                    logger.info("File archived", file=str(file), dest=str(dest))
                else:
                    # Borrar el archivo
                    file.unlink()
                    logger.info("File deleted", file=str(file))

        except Exception as e:
            logger.error(f"Error cleaning up files: {e}", job_id=job_id)

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
    Monitorea la carpeta de output esperando que aparezcan archivos de transcripción

    MacWhisper deposita archivos .txt en la carpeta de output cuando termina.
    Esta clase hace polling para detectarlos.
    """

    def __init__(self, output_dir: Path = config.WATCHED_OUTPUT_DIR):
        self.output_dir = output_dir
        logger.info("TranscriptionWatcher initialized", output_dir=str(output_dir))

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

        MacWhisper guarda los .txt en la MISMA carpeta que el audio (watched_input/)
        en lugar de en una carpeta separada de output.

        Buscamos por job_id que está incluido en el nombre del archivo
        """
        try:
            # MacWhisper guarda los .txt en watched_input/, no en watched_output/
            input_dir = config.WATCHED_INPUT_DIR

            logger.info(f"DEBUG: input_dir type={type(input_dir)}, value={input_dir}", job_id=job_id)
            logger.info(f"DEBUG: input_dir.exists()={input_dir.exists()}, is_dir()={input_dir.is_dir()}", job_id=job_id)

            # Use os.listdir() instead of Path.glob() to avoid sandboxing issues
            all_files = os.listdir(str(input_dir))
            txt_files = [f for f in all_files if f.endswith('.txt')]
            output_files = [input_dir / f for f in txt_files]

            logger.info(f"Polling for output: found {len(output_files)} txt files", job_id=job_id)

            if len(output_files) > 0:
                logger.info(f"DEBUG: Files found: {[f.name for f in output_files]}", job_id=job_id)

            # Buscar archivo que contenga el job_id
            for output_file in output_files:
                logger.info(f"DEBUG: Checking {output_file.name}, stem={output_file.stem}, match={job_id in output_file.stem}", job_id=job_id)
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
        Limpia archivos input y output de un job

        Args:
            job_id: UUID del job
        """
        try:
            # Limpiar todos los archivos (audio + .txt) de la carpeta watched_input
            # MacWhisper guarda ambos en la misma carpeta
            input_files = list(config.WATCHED_INPUT_DIR.glob(f"*{job_id}*"))
            for input_file in input_files:
                input_file.unlink()
                logger.info("File cleaned", file=str(input_file))

        except Exception as e:
            logger.error(f"Error cleaning up files: {e}", job_id=job_id)

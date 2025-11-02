#!/usr/bin/env python3
"""
Sistema de colas para manejo eficiente de transcripciones concurrentes
"""
import asyncio
import uuid
import time
from typing import Dict, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from src import config
from src.logger import get_logger

logger = get_logger()


class JobStatus(str, Enum):
    """Estados de un job de transcripción"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class TranscriptionJob:
    """Representa un job de transcripción"""
    job_id: str
    file_path: str  # Ruta temporal del archivo
    original_filename: str
    status: JobStatus = JobStatus.PENDING
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    result: Optional[Dict] = None
    error: Optional[str] = None

    def get_age(self) -> float:
        """Retorna la edad del job en segundos"""
        return time.time() - self.created_at

    def get_processing_time(self) -> Optional[float]:
        """Retorna el tiempo de procesamiento en segundos"""
        if self.started_at and self.completed_at:
            return self.completed_at - self.started_at
        return None

    def to_dict(self) -> Dict:
        """Convierte el job a diccionario para JSON response"""
        return {
            "job_id": self.job_id,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "processing_time": self.get_processing_time(),
            "age": self.get_age(),
            "result": self.result,
            "error": self.error
        }


class JobQueue:
    """
    Gestor de cola de jobs de transcripción con control de concurrencia

    Features:
    - asyncio.Queue para manejo asíncrono
    - Semaphore para limitar concurrencia
    - Tracking de jobs en memoria
    - Limpieza automática de jobs viejos
    """

    def __init__(self):
        # Eliminamos asyncio.Queue - solo usamos dict para tracking
        self.semaphore = asyncio.Semaphore(config.MAX_CONCURRENT_JOBS)
        self.jobs: Dict[str, TranscriptionJob] = {}
        self.workers_running = False
        self._cleanup_task = None

        logger.info(
            "JobQueue initialized",
            max_queue_size=config.MAX_QUEUE_SIZE,
            max_concurrent_jobs=config.MAX_CONCURRENT_JOBS
        )

    async def create_job(self, file_path: str, original_filename: str) -> str:
        """
        Crea un nuevo job y lo agrega al tracking

        Args:
            file_path: Ruta temporal del archivo
            original_filename: Nombre original del archivo

        Returns:
            str: job_id del job creado

        Raises:
            asyncio.QueueFull: Si se alcanzó el límite máximo de jobs
        """
        # Verificar límite de cola con jobs pendientes/procesando
        pending_jobs = sum(
            1 for job in self.jobs.values()
            if job.status in (JobStatus.PENDING, JobStatus.PROCESSING)
        )

        if pending_jobs >= config.MAX_QUEUE_SIZE:
            logger.error(
                "Queue full, cannot add job",
                pending_jobs=pending_jobs,
                max_size=config.MAX_QUEUE_SIZE
            )
            raise asyncio.QueueFull("Transcription queue is full")

        job_id = str(uuid.uuid4())

        job = TranscriptionJob(
            job_id=job_id,
            file_path=file_path,
            original_filename=original_filename
        )

        # Trackear el job
        self.jobs[job_id] = job

        logger.info(
            "Job created and queued",
            job_id=job_id,
            filename=original_filename,
            queue_size=pending_jobs + 1
        )

        return job_id

    def get_job(self, job_id: str) -> Optional[TranscriptionJob]:
        """Obtiene un job por su ID"""
        return self.jobs.get(job_id)

    def update_job_status(
        self,
        job_id: str,
        status: JobStatus,
        result: Optional[Dict] = None,
        error: Optional[str] = None
    ):
        """Actualiza el status de un job"""
        job = self.jobs.get(job_id)
        if not job:
            logger.warning("Job not found for update", job_id=job_id)
            return

        job.status = status

        if status == JobStatus.PROCESSING and not job.started_at:
            job.started_at = time.time()

        if status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.TIMEOUT):
            job.completed_at = time.time()
            job.result = result
            job.error = error

        logger.info(
            "Job status updated",
            job_id=job_id,
            status=status.value,
            processing_time=job.get_processing_time()
        )

    async def cleanup_old_jobs(self):
        """Limpia jobs completados/fallidos que sean muy viejos"""
        current_time = time.time()
        jobs_to_remove = []

        for job_id, job in self.jobs.items():
            # Si el job está completado/fallido y es más viejo que retention time
            if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.TIMEOUT):
                if (current_time - job.created_at) > config.JOB_RETENTION_TIME:
                    jobs_to_remove.append(job_id)

        for job_id in jobs_to_remove:
            del self.jobs[job_id]
            logger.info("Old job cleaned up", job_id=job_id)

        if jobs_to_remove:
            logger.info(
                "Cleanup completed",
                jobs_removed=len(jobs_to_remove),
                jobs_remaining=len(self.jobs)
            )

    async def start_cleanup_task(self):
        """Inicia tarea de limpieza periódica"""
        while True:
            await asyncio.sleep(config.CLEANUP_INTERVAL)
            await self.cleanup_old_jobs()

    def get_queue_stats(self) -> Dict:
        """Obtiene estadísticas de la cola"""
        status_counts = {
            JobStatus.PENDING.value: 0,
            JobStatus.PROCESSING.value: 0,
            JobStatus.COMPLETED.value: 0,
            JobStatus.FAILED.value: 0,
            JobStatus.TIMEOUT.value: 0
        }

        for job in self.jobs.values():
            status_counts[job.status.value] += 1

        # Calculate pending jobs (pending + processing)
        pending_jobs = sum(
            1 for job in self.jobs.values()
            if job.status in (JobStatus.PENDING, JobStatus.PROCESSING)
        )

        return {
            "queue_size": pending_jobs,
            "total_jobs": len(self.jobs),
            "max_queue_size": config.MAX_QUEUE_SIZE,
            "max_concurrent_jobs": config.MAX_CONCURRENT_JOBS,
            "status_counts": status_counts
        }


# Global queue instance
_global_queue: Optional[JobQueue] = None


def get_job_queue() -> JobQueue:
    """Obtiene la instancia global de JobQueue (singleton)"""
    global _global_queue
    if _global_queue is None:
        _global_queue = JobQueue()
    return _global_queue

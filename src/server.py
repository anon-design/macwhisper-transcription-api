#!/usr/bin/env python3
"""
Servidor HTTP para API de transcripción con MacWhisper Watched Folders

Features:
- Cola de jobs con semáforo para control de concurrencia
- Retry automático en caso de timeout
- Watchdog para detectar jobs stuck y MacWhisper no responsivo
- Health checks mejorados
- Cleanup automático de jobs inconsistentes
"""
import os
import sys
import time
import traceback
import asyncio
import subprocess
from pathlib import Path

from aiohttp import web
import json

# Importar módulos locales
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.macwhisper_service import MacWhisperService
from src.queue_manager import get_job_queue, JobStatus
from src.validators import validate_transcription_request, ValidationError
from src.rate_limiter import RateLimiter
from src.logger import get_logger
from src import config
from src import monitoring

# Logger y rate limiter globales
logger = get_logger()
rate_limiter = RateLimiter()
job_queue = get_job_queue()


# ============================================================================
# MacWhisper Monitor - Detecta y recupera de estados stuck
# ============================================================================

class MacWhisperMonitor:
    """Monitor de salud de MacWhisper con capacidad de restart."""

    def __init__(self):
        self.consecutive_failures = 0
        self.last_successful_transcription = None
        self.restart_count = 0
        self.max_restarts_per_hour = 3
        self.restart_timestamps = []

    async def check_processing_health(self):
        """
        Verifica si MacWhisper está procesando archivos activamente.
        Returns: Tuple[bool, str] - (is_healthy, reason)
        """
        # 1. Verificar que el proceso esté corriendo
        is_running, pid = monitoring.is_macwhisper_running()
        if not is_running:
            return False, "MacWhisper process not running"

        # 2. Verificar archivos huérfanos por demasiado tiempo
        orphaned = monitoring.check_orphaned_files()
        for file in orphaned.get('orphaned_files', []):
            if file['age_minutes'] > 5:
                return False, f"File {file['filename']} waiting for {file['age_minutes']:.1f} minutes"

        return True, "OK"

    def record_successful_transcription(self):
        """Registra una transcripción exitosa."""
        self.last_successful_transcription = time.time()
        self.consecutive_failures = 0

    def can_restart(self):
        """Verifica si podemos reiniciar (rate limiting)."""
        current_time = time.time()
        one_hour_ago = current_time - 3600

        # Limpiar timestamps viejos
        self.restart_timestamps = [
            ts for ts in self.restart_timestamps
            if ts > one_hour_ago
        ]

        return len(self.restart_timestamps) < self.max_restarts_per_hour

    async def restart_macwhisper(self):
        """Reinicia MacWhisper de forma segura."""
        if not self.can_restart():
            logger.error(f"Rate limit exceeded: {len(self.restart_timestamps)} restarts in last hour")
            return False

        logger.warning("Attempting to restart MacWhisper")

        try:
            # 1. Quit gracefully
            subprocess.run(
                ['osascript', '-e', 'tell application "MacWhisper" to quit'],
                capture_output=True,
                timeout=10
            )

            # 2. Esperar a que cierre
            await asyncio.sleep(5)

            # 3. Verificar que cerró
            is_running, _ = monitoring.is_macwhisper_running()
            if is_running:
                subprocess.run(['pkill', '-9', 'MacWhisper'], capture_output=True, timeout=5)
                await asyncio.sleep(2)

            # 4. Reabrir
            subprocess.run(['open', '-a', 'MacWhisper'], capture_output=True, timeout=10)

            # 5. Esperar a que inicie
            await asyncio.sleep(10)

            # 6. Verificar que esté corriendo
            is_running, pid = monitoring.is_macwhisper_running()

            if is_running:
                self.restart_timestamps.append(time.time())
                self.restart_count += 1
                logger.info(f"MacWhisper restarted successfully (PID: {pid})")
                return True
            else:
                logger.error("MacWhisper failed to start after restart attempt")
                return False

        except subprocess.TimeoutExpired:
            logger.error("Timeout during MacWhisper restart")
            return False
        except Exception as e:
            logger.error(f"Error restarting MacWhisper: {e}")
            return False


# Instancia global del monitor
macwhisper_monitor = MacWhisperMonitor()


# ============================================================================
# Middlewares
# ============================================================================

def get_client_ip(request) -> str:
    """Obtiene la IP del cliente del request"""
    forwarded_for = request.headers.get('X-Forwarded-For')
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()

    peername = request.transport.get_extra_info('peername')
    if peername:
        return peername[0]

    return "unknown"


@web.middleware
async def rate_limit_middleware(request, handler):
    """Middleware de rate limiting"""
    if request.path == '/health':
        return await handler(request)

    client_ip = get_client_ip(request)
    allowed, remaining = rate_limiter.is_allowed(client_ip)

    if not allowed:
        retry_after = rate_limiter.get_retry_after(client_ip)

        logger.warning(
            f"Rate limit exceeded for {client_ip}",
            ip=client_ip,
            path=request.path,
            retry_after=retry_after
        )

        return web.json_response(
            {
                "success": False,
                "error": "Rate limit exceeded",
                "retry_after_seconds": round(retry_after, 1)
            },
            status=429,
            headers={
                'Retry-After': str(int(retry_after) + 1),
                'X-RateLimit-Limit': str(config.RATE_LIMIT_PER_MINUTE),
                'X-RateLimit-Remaining': '0'
            }
        )

    response = await handler(request)
    response.headers['X-RateLimit-Limit'] = str(config.RATE_LIMIT_PER_MINUTE)
    response.headers['X-RateLimit-Remaining'] = str(remaining)

    return response


@web.middleware
async def logging_middleware(request, handler):
    """Middleware de logging de requests"""
    start_time = time.time()

    try:
        response = await handler(request)

        duration_ms = (time.time() - start_time) * 1000

        logger.log_request(
            method=request.method,
            path=request.path,
            status=response.status,
            duration_ms=duration_ms,
            ip=get_client_ip(request)
        )

        return response

    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000

        logger.error(
            f"Request failed: {str(e)}",
            method=request.method,
            path=request.path,
            duration_ms=duration_ms,
            ip=get_client_ip(request)
        )

        raise


# ============================================================================
# Handlers de Endpoints
# ============================================================================

async def handle_transcribe(request):
    """
    Endpoint POST /transcribe - Envía archivo a la cola de transcripción

    Query params:
    - wait=true: Modo sincrónico - espera hasta que complete y retorna el resultado
    - wait=false (default): Modo asíncrono - retorna job_id inmediatamente
    """
    try:
        wait_for_result = request.query.get('wait', '').lower() == 'true'

        reader = await request.multipart()
        field = await reader.next()

        if not field or field.name != 'file':
            return web.json_response(
                {"success": False, "error": "Campo 'file' requerido en multipart/form-data"},
                status=400
            )

        temp_path = f"/tmp/macwhisper_upload_{os.getpid()}_{int(time.time())}_{id(request)}.tmp"
        original_filename = field.filename if hasattr(field, 'filename') else None

        try:
            with open(temp_path, 'wb') as f:
                while True:
                    chunk = await field.read_chunk()
                    if not chunk:
                        break
                    f.write(chunk)

            # Verificar que MacWhisper esté corriendo
            is_running, pid = monitoring.is_macwhisper_running()
            if not is_running:
                return web.json_response(
                    {
                        "success": False,
                        "error": "MacWhisper is not running. Please start MacWhisper app.",
                        "code": "MACWHISPER_NOT_RUNNING"
                    },
                    status=503
                )

            logger.info("MacWhisper health check passed", pid=pid)

            # Validar archivo
            validation = validate_transcription_request(temp_path, original_filename)

            if not validation['valid']:
                return web.json_response(
                    {"success": False, "error": validation['error']},
                    status=400
                )

            file_size_mb = validation['file_size_mb']

            logger.info(
                "Audio file validated",
                format=validation['format'],
                size_mb=file_size_mb,
                sync_mode=wait_for_result
            )

            # Crear job
            job_id = await job_queue.create_job(temp_path, original_filename)

            job = job_queue.get_job(job_id)
            if job:
                job.file_size_mb = file_size_mb
                job.temp_file_path = temp_path  # Guardar referencia al temp file

            # Iniciar procesamiento en background
            asyncio.create_task(process_job(job_id, temp_path, original_filename))

            # MODO SINCRÓNICO
            if wait_for_result:
                dynamic_timeout = monitoring.calculate_dynamic_timeout(file_size_mb)

                logger.info(
                    f"Synchronous mode: waiting for job to complete",
                    job_id=job_id,
                    file_size_mb=file_size_mb,
                    dynamic_timeout=dynamic_timeout
                )

                poll_interval = 0.5
                max_wait = dynamic_timeout
                elapsed = 0.0

                while elapsed < max_wait:
                    await asyncio.sleep(poll_interval)
                    elapsed += poll_interval

                    job = job_queue.get_job(job_id)

                    if not job:
                        return web.json_response(
                            {"success": False, "error": "Job not found"},
                            status=404
                        )

                    if job.status == JobStatus.COMPLETED:
                        logger.info(f"Job completed synchronously", job_id=job_id, elapsed=elapsed)
                        return web.json_response({
                            "success": True,
                            "status": "completed",
                            "job_id": job_id,
                            "result": job.result
                        })

                    elif job.status == JobStatus.FAILED:
                        return web.json_response({
                            "success": False,
                            "status": "failed",
                            "job_id": job_id,
                            "error": job.error
                        }, status=500)

                    elif job.status == JobStatus.TIMEOUT:
                        return web.json_response({
                            "success": False,
                            "status": "timeout",
                            "job_id": job_id,
                            "error": job.error
                        }, status=504)

                return web.json_response({
                    "success": False,
                    "error": f"Timeout waiting for result after {max_wait}s",
                    "job_id": job_id
                }, status=504)

            # MODO ASÍNCRONO
            else:
                return web.json_response({
                    "success": True,
                    "job_id": job_id,
                    "status": "queued",
                    "message": f"Job queued for processing. Use GET /job/{job_id} to check status"
                })

        except asyncio.QueueFull:
            return web.json_response(
                {"success": False, "error": "Queue is full, try again later"},
                status=503
            )

    except ValidationError as e:
        logger.warning(f"Validation error: {e}")
        return web.json_response(
            {"success": False, "error": str(e)},
            status=400
        )
    except Exception as e:
        logger.error(f"Transcription error: {e}")
        traceback.print_exc()
        return web.json_response(
            {"success": False, "error": str(e)},
            status=500
        )


async def handle_job_status(request):
    """Endpoint GET /job/{job_id} - Consulta el status de un job"""
    job_id = request.match_info['job_id']

    job = job_queue.get_job(job_id)

    if not job:
        return web.json_response(
            {"success": False, "error": f"Job {job_id} not found"},
            status=404
        )

    job_dict = job.to_dict()

    if job.status == JobStatus.COMPLETED:
        return web.json_response({
            "success": True,
            "status": "completed",
            **job_dict
        })

    elif job.status == JobStatus.FAILED:
        return web.json_response({
            "success": False,
            "status": "failed",
            **job_dict
        }, status=500)

    elif job.status == JobStatus.TIMEOUT:
        return web.json_response({
            "success": False,
            "status": "timeout",
            **job_dict
        }, status=504)

    else:
        return web.json_response({
            "success": True,
            "status": job.status.value,
            **job_dict
        })


async def handle_queue_status(request):
    """Endpoint GET /queue - Info del estado de la cola"""
    stats = job_queue.get_queue_stats()

    return web.json_response({
        "success": True,
        **stats
    })


async def handle_job_history(request):
    """Endpoint GET /jobs/history - Historial de jobs"""
    try:
        limit = int(request.query.get('limit', '100'))
        limit = min(limit, 500)
    except ValueError:
        limit = 100

    jobs = job_queue.get_job_history(limit=limit)

    return web.json_response({
        "success": True,
        "jobs": jobs,
        "count": len(jobs),
        "limit": limit
    })


async def handle_health(request):
    """Endpoint GET /health - Health check mejorado"""
    macwhisper_info = monitoring.get_macwhisper_info()
    orphaned_info = monitoring.check_orphaned_files()
    folder_stats = monitoring.get_watched_folder_stats()
    queue_stats = job_queue.get_queue_stats()

    overall_status = "healthy"
    warnings = []

    if not macwhisper_info.get("running"):
        overall_status = "unhealthy"
        warnings.append("MacWhisper is not running")

    if orphaned_info.get("count", 0) > 0:
        overall_status = "degraded" if overall_status == "healthy" else overall_status
        warnings.append(f"{orphaned_info['count']} orphaned files detected")

    # Detectar jobs stuck
    stuck_count = sum(1 for job in job_queue.jobs.values()
                     if job.status == JobStatus.PROCESSING
                     and job.started_at
                     and (time.time() - job.started_at) > 1800)
    if stuck_count > 0:
        overall_status = "degraded" if overall_status == "healthy" else overall_status
        warnings.append(f"{stuck_count} jobs stuck in processing")

    return web.json_response({
        "status": overall_status,
        "warnings": warnings,
        "model": "MacWhisper (WhisperKit Pro / Whisper Large V3)",
        "backend": "Watched Folders",
        "compute": "MacWhisper App",
        "macwhisper": macwhisper_info,
        "orphaned_files": orphaned_info,
        "watched_folder": folder_stats,
        "queue": queue_stats,
        "monitor": {
            "consecutive_failures": macwhisper_monitor.consecutive_failures,
            "restart_count": macwhisper_monitor.restart_count,
            "last_successful_transcription": macwhisper_monitor.last_successful_transcription
        },
        "features": {
            "watched_folders": True,
            "queue_system": True,
            "rate_limiting": True,
            "validation": True,
            "auto_retry": True,
            "dynamic_timeout": True,
            "file_logging": config.LOG_TO_FILE,
            "watchdog": True,
            "auto_restart": True
        },
        "limits": {
            "max_file_size_mb": config.MAX_FILE_SIZE_MB,
            "max_audio_duration_min": config.MAX_AUDIO_DURATION / 60,
            "rate_limit_per_minute": config.RATE_LIMIT_PER_MINUTE,
            "max_queue_size": config.MAX_QUEUE_SIZE,
            "max_concurrent_jobs": config.MAX_CONCURRENT_JOBS,
            "job_timeout_base": config.JOB_TIMEOUT,
            "job_timeout_max": config.MAX_JOB_TIMEOUT,
            "max_retries": config.MAX_RETRIES
        },
        "paths": {
            "watched_folder": str(config.WATCHED_FOLDER),
            "log_dir": str(config.LOG_DIR) if config.LOG_TO_FILE else None
        }
    })


async def handle_rate_limit_status(request):
    """Endpoint GET /rate-limit - Estado de rate limiting para el cliente"""
    client_ip = get_client_ip(request)
    stats = rate_limiter.get_stats(client_ip)

    return web.json_response({
        "ip": client_ip,
        **stats
    })


async def handle_cleanup_stuck(request):
    """
    POST /admin/cleanup-stuck - Limpia jobs en estado inconsistente
    """
    cleaned = 0
    details = []

    for job_id, job in list(job_queue.jobs.items()):
        reason = None

        # Jobs "processing" por más de 30 minutos
        if job.status == JobStatus.PROCESSING:
            if job.started_at and (time.time() - job.started_at) > 1800:
                reason = f"stuck in processing for {(time.time() - job.started_at)/60:.1f} minutes"

        # Jobs con timestamps negativos
        if job.started_at and job.completed_at:
            if job.completed_at < job.started_at:
                reason = "invalid timestamps (negative processing time)"

        if reason:
            job_queue.update_job_status(
                job_id, JobStatus.FAILED,
                error=f"Cleaned by admin: {reason}"
            )
            cleaned += 1
            details.append({"job_id": job_id, "reason": reason})

    return web.json_response({
        "success": True,
        "cleaned_jobs": cleaned,
        "details": details
    })


async def handle_restart_macwhisper(request):
    """
    POST /admin/restart-macwhisper - Reinicia MacWhisper manualmente
    """
    if macwhisper_monitor.can_restart():
        success = await macwhisper_monitor.restart_macwhisper()
        return web.json_response({
            "success": success,
            "message": "MacWhisper restarted" if success else "Failed to restart MacWhisper",
            "restart_count": macwhisper_monitor.restart_count
        })
    else:
        return web.json_response({
            "success": False,
            "error": "Rate limit exceeded for restarts",
            "restarts_in_last_hour": len(macwhisper_monitor.restart_timestamps)
        }, status=429)


# ============================================================================
# Job Processing
# ============================================================================

async def process_job(job_id: str, temp_file: str, original_filename: str):
    """
    Procesa un job de transcripción en background.

    Features:
    - Semáforo para control de concurrencia
    - Retry automático con backoff exponencial
    - Cleanup solo en estados terminales
    - FIX: Reset completo de timestamps en retry
    """
    job = job_queue.get_job(job_id)
    if not job:
        logger.error("Job not found", job_id=job_id)
        return

    try:
        # Verificar salud de MacWhisper antes de procesar
        is_healthy, reason = await macwhisper_monitor.check_processing_health()
        if not is_healthy:
            logger.warning(f"MacWhisper unhealthy: {reason}", job_id=job_id)
            if macwhisper_monitor.can_restart():
                logger.info("Attempting MacWhisper restart before processing", job_id=job_id)
                await macwhisper_monitor.restart_macwhisper()

        # Usar semáforo para controlar concurrencia
        async with job_queue.semaphore:
            # Re-obtener job (puede haber cambiado)
            job = job_queue.get_job(job_id)
            if not job:
                logger.error("Job not found after acquiring semaphore", job_id=job_id)
                return

            logger.info(
                f"Job acquired semaphore, starting transcription",
                job_id=job_id,
                filename=original_filename,
                retry_count=getattr(job, 'retry_count', 0),
                file_size_mb=getattr(job, 'file_size_mb', 0)
            )

            # Verificar que MacWhisper esté corriendo
            is_running, pid = monitoring.is_macwhisper_running()
            if not is_running:
                logger.error("MacWhisper not running, cannot process job", job_id=job_id)
                job_queue.update_job_status(
                    job_id,
                    JobStatus.FAILED,
                    error="MacWhisper is not running"
                )
                return

            # Verificar que temp_file existe
            if not os.path.exists(temp_file):
                logger.error(f"Temp file not found: {temp_file}", job_id=job_id)
                job_queue.update_job_status(
                    job_id,
                    JobStatus.FAILED,
                    error="Temporary file not found"
                )
                return

            # Actualizar status a PROCESSING
            job_queue.update_job_status(job_id, JobStatus.PROCESSING)
            logger.info(f"Job status updated to PROCESSING", job_id=job_id, macwhisper_pid=pid)

            # Transcribir
            service = MacWhisperService()
            result = await service.transcribe_async(temp_file, job_id, original_filename)

            # Validar resultado
            if not result or not result.get('text'):
                logger.warning("Empty transcription result", job_id=job_id)
                # Aún así marcamos como completado si hay resultado (aunque vacío)

            logger.info(f"transcribe_async() COMPLETED", job_id=job_id, words=result.get('words', 0))

            # Éxito
            job_queue.update_job_status(
                job_id,
                JobStatus.COMPLETED,
                result=result
            )
            macwhisper_monitor.record_successful_transcription()

    except TimeoutError as e:
        retry_count = getattr(job, 'retry_count', 0) if job else 0
        logger.error(f"Job timeout: {e}", job_id=job_id, retry_count=retry_count)

        # Marcar como timeout
        job_queue.update_job_status(
            job_id,
            JobStatus.TIMEOUT,
            error=str(e)
        )

        # Intentar retry
        if job and job_queue.can_retry(job_id):
            # FIX: Reset COMPLETO de campos para retry
            job.retry_count = getattr(job, 'retry_count', 0) + 1
            job.status = JobStatus.PENDING
            job.started_at = None
            job.completed_at = None  # FIX: También resetear completed_at
            job.error = None

            # Backoff exponencial: 2, 4, 8 segundos...
            backoff = 2 ** job.retry_count
            logger.info(
                f"Retrying job (attempt {job.retry_count + 1}) after {backoff}s backoff",
                job_id=job_id,
                retry_count=job.retry_count
            )

            await asyncio.sleep(backoff)
            asyncio.create_task(process_job(job_id, temp_file, original_filename))
            return  # No limpiar temp_file todavía

        else:
            logger.error(
                f"Job exhausted all retries",
                job_id=job_id,
                retry_count=retry_count,
                max_retries=config.MAX_RETRIES
            )

    except Exception as e:
        logger.error(f"Job failed: {e}", job_id=job_id)
        traceback.print_exc()
        job_queue.update_job_status(
            job_id,
            JobStatus.FAILED,
            error=str(e)
        )

    finally:
        # Cleanup solo si es estado terminal definitivo
        job = job_queue.get_job(job_id)
        if job:
            is_terminal = job.status in (JobStatus.COMPLETED, JobStatus.FAILED)
            is_final_timeout = (
                job.status == JobStatus.TIMEOUT and
                job.retry_count >= config.MAX_RETRIES
            )

            if is_terminal or is_final_timeout:
                if os.path.exists(temp_file):
                    try:
                        os.remove(temp_file)
                        logger.info(f"Cleaned temp file", job_id=job_id, file=temp_file)
                    except Exception as e:
                        logger.error(f"Failed to clean temp file: {e}", job_id=job_id)


# ============================================================================
# Watchdog Task
# ============================================================================

async def watchdog_task():
    """
    Tarea de background que monitorea y recupera estados inconsistentes.
    """
    logger.info("Watchdog task started")

    while True:
        try:
            await asyncio.sleep(60)  # Check cada minuto

            # 1. Detectar y limpiar jobs stuck
            stuck_count = 0
            for job_id, job in list(job_queue.jobs.items()):
                if job.status == JobStatus.PROCESSING and job.started_at:
                    elapsed = time.time() - job.started_at
                    if elapsed > 1800:  # 30 minutos
                        logger.warning(
                            f"Watchdog: Job stuck for {elapsed/60:.1f} minutes",
                            job_id=job_id
                        )
                        job_queue.update_job_status(
                            job_id, JobStatus.TIMEOUT,
                            error=f"Watchdog: stuck for {elapsed/60:.1f} minutes"
                        )
                        stuck_count += 1

            if stuck_count:
                logger.warning(f"Watchdog cleaned {stuck_count} stuck jobs")

            # 2. Verificar salud de MacWhisper
            is_healthy, reason = await macwhisper_monitor.check_processing_health()
            if not is_healthy:
                macwhisper_monitor.consecutive_failures += 1
                logger.warning(
                    f"MacWhisper health check failed ({macwhisper_monitor.consecutive_failures}): {reason}"
                )

                # Después de 3 fallos consecutivos, intentar restart
                if macwhisper_monitor.consecutive_failures >= 3:
                    logger.error("Multiple health check failures, attempting restart")
                    if await macwhisper_monitor.restart_macwhisper():
                        macwhisper_monitor.consecutive_failures = 0
            else:
                macwhisper_monitor.consecutive_failures = 0

        except Exception as e:
            logger.error(f"Watchdog error: {e}")
            traceback.print_exc()


# ============================================================================
# Main
# ============================================================================

def main():
    """Inicia el servidor HTTP"""
    print("\n" + "="*70)
    print("MacWhisper Transcription API - Queue Based")
    print("="*70 + "\n")

    # Crear aplicación con middlewares
    app = web.Application(
        client_max_size=config.MAX_FILE_SIZE_MB * 1024 * 1024,
        middlewares=[
            rate_limit_middleware,
            logging_middleware
        ]
    )

    # Registrar rutas
    app.router.add_post('/transcribe', handle_transcribe)
    app.router.add_get('/job/{job_id}', handle_job_status)
    app.router.add_get('/jobs/history', handle_job_history)
    app.router.add_get('/queue', handle_queue_status)
    app.router.add_get('/health', handle_health)
    app.router.add_get('/rate-limit', handle_rate_limit_status)

    # Admin endpoints
    app.router.add_post('/admin/cleanup-stuck', handle_cleanup_stuck)
    app.router.add_post('/admin/restart-macwhisper', handle_restart_macwhisper)

    # Banner
    print("\n" + "="*70)
    print(f"Servidor iniciado en http://{config.HOST}:{config.PORT}")
    print(f"Modelo: MacWhisper (WhisperKit Pro / Whisper Large V3)")
    print(f"Backend: Watched Folders")
    print(f"Max file size: {config.MAX_FILE_SIZE_MB} MB")
    print(f"Rate limit: {config.RATE_LIMIT_PER_MINUTE} req/min por IP")
    print(f"Max queue size: {config.MAX_QUEUE_SIZE}")
    print(f"Max concurrent jobs: {config.MAX_CONCURRENT_JOBS}")
    print("\nEndpoints:")
    print(f"  POST /transcribe (submit job)")
    print(f"  GET  /job/{{job_id}} (check status)")
    print(f"  GET  /jobs/history (job history)")
    print(f"  GET  /queue (queue stats)")
    print(f"  GET  /health (health check)")
    print(f"  GET  /rate-limit (rate limit status)")
    print(f"  POST /admin/cleanup-stuck (clean stuck jobs)")
    print(f"  POST /admin/restart-macwhisper (restart MacWhisper)")
    print("\nFeatures:")
    print(f"  - MacWhisper health checks")
    print(f"  - Semaphore-based concurrency control")
    print(f"  - Auto-retry on timeout (max {config.MAX_RETRIES} retries)")
    print(f"  - Dynamic timeout based on file size")
    print(f"  - Watchdog for stuck jobs")
    print(f"  - Auto-restart MacWhisper when stuck")
    print(f"  - File logging to {config.LOG_DIR / 'api.log'}")
    print("\nWatched Folder:")
    print(f"  {config.WATCHED_FOLDER}")
    print("\nIMPORTANT: Configure MacWhisper to watch this folder!")
    print("="*70 + "\n")

    # Background tasks
    async def start_background_tasks(app):
        app['cleanup_task'] = asyncio.create_task(job_queue.start_cleanup_task())
        app['watchdog_task'] = asyncio.create_task(watchdog_task())

    async def cleanup_background_tasks(app):
        app['cleanup_task'].cancel()
        app['watchdog_task'].cancel()
        try:
            await app['cleanup_task']
        except asyncio.CancelledError:
            pass
        try:
            await app['watchdog_task']
        except asyncio.CancelledError:
            pass

    app.on_startup.append(start_background_tasks)
    app.on_cleanup.append(cleanup_background_tasks)

    # Iniciar servidor
    web.run_app(
        app,
        host=config.HOST,
        port=config.PORT,
        print=lambda *args: None
    )


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nServidor detenido")
        sys.exit(0)

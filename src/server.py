#!/usr/bin/env python3
"""
Servidor HTTP para API de transcripción con MacWhisper Watched Folders
"""
import os
import sys
import time
import traceback
import asyncio
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

# Logger y rate limiter globales
logger = get_logger()
rate_limiter = RateLimiter()
job_queue = get_job_queue()


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


async def handle_transcribe(request):
    """
    Endpoint POST /transcribe - Envía archivo a la cola de transcripción

    Query params:
    - wait=true: Modo sincrónico - espera hasta que complete y retorna el resultado
    - wait=false (default): Modo asíncrono - retorna job_id inmediatamente
    """
    try:
        # Verificar si el cliente quiere esperar el resultado (modo sincrónico)
        wait_for_result = request.query.get('wait', '').lower() == 'true'

        # Obtener multipart data
        reader = await request.multipart()
        field = await reader.next()

        if not field or field.name != 'file':
            return web.json_response(
                {"success": False, "error": "Campo 'file' requerido en multipart/form-data"},
                status=400
            )

        # Guardar archivo temporal
        temp_path = f"/tmp/macwhisper_upload_{os.getpid()}_{int(time.time())}.tmp"
        original_filename = field.filename if hasattr(field, 'filename') else None

        try:
            with open(temp_path, 'wb') as f:
                while True:
                    chunk = await field.read_chunk()
                    if not chunk:
                        break
                    f.write(chunk)

            # Validar archivo
            validation = validate_transcription_request(temp_path, original_filename)

            if not validation['valid']:
                return web.json_response(
                    {"success": False, "error": validation['error']},
                    status=400
                )

            logger.info(
                "Audio file validated",
                format=validation['format'],
                size_mb=validation['file_size_mb'],
                sync_mode=wait_for_result
            )

            # Crear job y agregarlo a la cola
            job_id = await job_queue.create_job(temp_path, original_filename)

            # Iniciar procesamiento en background
            asyncio.create_task(process_job(job_id, temp_path, original_filename))

            # MODO SINCRÓNICO: Esperar hasta que complete
            if wait_for_result:
                logger.info(f"Synchronous mode: waiting for job to complete", job_id=job_id)

                poll_interval = 0.5  # Polling cada 0.5 segundos
                max_wait = config.JOB_TIMEOUT
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

                    # Job completado exitosamente
                    if job.status == JobStatus.COMPLETED:
                        logger.info(f"Job completed synchronously", job_id=job_id, elapsed=elapsed)
                        return web.json_response({
                            "success": True,
                            "status": "completed",
                            "job_id": job_id,
                            "result": job.result
                        })

                    # Job falló
                    elif job.status == JobStatus.FAILED:
                        return web.json_response({
                            "success": False,
                            "status": "failed",
                            "job_id": job_id,
                            "error": job.error
                        }, status=500)

                    # Job timeout
                    elif job.status == JobStatus.TIMEOUT:
                        return web.json_response({
                            "success": False,
                            "status": "timeout",
                            "job_id": job_id,
                            "error": job.error
                        }, status=504)

                # Timeout esperando resultado
                return web.json_response({
                    "success": False,
                    "error": f"Timeout waiting for result after {max_wait}s",
                    "job_id": job_id
                }, status=504)

            # MODO ASÍNCRONO: Retornar job_id inmediatamente
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
    """
    Endpoint GET /job/{job_id} - Consulta el status de un job

    Retorna:
    - Si está pending/processing: status y tiempo transcurrido
    - Si está completed: resultado completo de la transcripción
    - Si está failed: error message
    """
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
        # pending or processing
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


async def handle_health(request):
    """Endpoint GET /health - Health check"""
    return web.json_response({
        "status": "ok",
        "model": "MacWhisper (WhisperKit Pro / Whisper Large V3)",
        "backend": "Watched Folders",
        "compute": "MacWhisper App",
        "features": {
            "watched_folders": True,
            "queue_system": True,
            "rate_limiting": True,
            "validation": True
        },
        "limits": {
            "max_file_size_mb": config.MAX_FILE_SIZE_MB,
            "max_audio_duration_min": config.MAX_AUDIO_DURATION / 60,
            "rate_limit_per_minute": config.RATE_LIMIT_PER_MINUTE,
            "max_queue_size": config.MAX_QUEUE_SIZE,
            "max_concurrent_jobs": config.MAX_CONCURRENT_JOBS
        },
        "paths": {
            "watched_input": str(config.WATCHED_INPUT_DIR),
            "watched_output": str(config.WATCHED_OUTPUT_DIR)
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


async def process_job(job_id: str, temp_file: str, original_filename: str):
    """
    Procesa un job de transcripción en background

    Esta función se ejecuta como asyncio task y actualiza el status del job
    """
    try:
        # Actualizar status a processing
        job_queue.update_job_status(job_id, JobStatus.PROCESSING)

        # Transcribir usando MacWhisperService
        service = MacWhisperService()
        result = await service.transcribe_async(temp_file, job_id, original_filename)

        # Actualizar status a completed
        job_queue.update_job_status(
            job_id,
            JobStatus.COMPLETED,
            result=result
        )

    except TimeoutError as e:
        logger.error(f"Job timeout: {e}", job_id=job_id)
        job_queue.update_job_status(
            job_id,
            JobStatus.TIMEOUT,
            error=str(e)
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
        # Limpiar archivo temporal
        if os.path.exists(temp_file):
            os.remove(temp_file)


def main():
    """Inicia el servidor HTTP"""
    print("\n" + "="*70)
    print("🚀 MacWhisper Transcription API - Queue Based")
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
    app.router.add_get('/queue', handle_queue_status)
    app.router.add_get('/health', handle_health)
    app.router.add_get('/rate-limit', handle_rate_limit_status)

    # Banner
    print("\n" + "="*70)
    print(f"✅ Servidor iniciado en http://{config.HOST}:{config.PORT}")
    print(f"📊 Modelo: MacWhisper (WhisperKit Pro / Whisper Large V3)")
    print(f"💻 Backend: Watched Folders")
    print(f"📁 Max file size: {config.MAX_FILE_SIZE_MB} MB")
    print(f"🚦 Rate limit: {config.RATE_LIMIT_PER_MINUTE} req/min por IP")
    print(f"📦 Max queue size: {config.MAX_QUEUE_SIZE}")
    print(f"🔄 Max concurrent jobs: {config.MAX_CONCURRENT_JOBS}")
    print("\nEndpoints:")
    print(f"  - POST http://localhost:{config.PORT}/transcribe (submit job)")
    print(f"  - GET  http://localhost:{config.PORT}/job/{{job_id}} (check status)")
    print(f"  - GET  http://localhost:{config.PORT}/queue (queue stats)")
    print(f"  - GET  http://localhost:{config.PORT}/health (health check)")
    print(f"  - GET  http://localhost:{config.PORT}/rate-limit (rate limit status)")
    print("\nWatched Folders:")
    print(f"  - Input: {config.WATCHED_INPUT_DIR}")
    print(f"  - Output: {config.WATCHED_OUTPUT_DIR}")
    print("\nIMPORTANT: Configure MacWhisper to watch the input folder!")
    print("="*70 + "\n")

    # Iniciar tarea de limpieza de jobs viejos cuando el servidor arranque
    async def start_background_tasks(app):
        app['cleanup_task'] = asyncio.create_task(job_queue.start_cleanup_task())

    async def cleanup_background_tasks(app):
        app['cleanup_task'].cancel()
        await app['cleanup_task']

    app.on_startup.append(start_background_tasks)
    app.on_cleanup.append(cleanup_background_tasks)

    # Iniciar servidor
    web.run_app(
        app,
        host=config.HOST,
        port=config.PORT,
        print=lambda *args: None  # Silenciar logs de aiohttp
    )


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Servidor detenido")
        sys.exit(0)

# MacWhisper Transcription API

API HTTP que utiliza MacWhisper (Watched Folders) para transcripción de audio, con sistema de colas para manejo eficiente de múltiples archivos.

## Características

- **Queue System**: Cola de jobs para manejo de múltiples transcripciones
- **Job Tracking**: Cada transcripción tiene un UUID para consultar su estado
- **Rate Limiting**: Límite de requests por IP
- **Validation**: Validación de archivos de audio
- **Logging Estructurado**: Logs en formato JSON
- **Multiple Formats**: Soporte para MP3, WAV, M4A, FLAC, OGG, Opus, WebM

## Arquitectura

```
Cliente HTTP
    ↓
POST /transcribe → Retorna job_id inmediatamente
    ↓
Archivo copiado a watched_input/ con UUID en el nombre
    ↓
MacWhisper detecta y transcribe automáticamente
    ↓
MacWhisper guarda .txt en el MISMO folder (watched_input/)
    ↓
API detecta resultado y lo asocia con job_id
    ↓
GET /job/{job_id} → Retorna transcripción
```

## Requisitos Previos

### 1. MacWhisper Pro

Este proyecto requiere **MacWhisper Pro** con la funcionalidad de Watched Folders activada.

### 2. Configuración de MacWhisper

**IMPORTANTE**: Antes de iniciar la API, configura MacWhisper:

1. Abre MacWhisper
2. Ve a **Settings** → **Watch Folders**
3. Clic en **"Add Watch Folder"**
4. Selecciona la ruta completa al folder: `<tu-path>/Macwhisperapi/watched_input`
   - Ejemplo: `/Users/JC/Macwhisperapi/watched_input`
5. Configura **Output Format**: Plain Text (.txt)
6. **IMPORTANTE**: Configura **Output Location** a:
   - **"Same as source"** (Mismo que fuente)
   - Esto hace que MacWhisper guarde el .txt en el mismo folder que el audio
7. Activa **"Auto-Transcribe Toggle"**
8. Mantén MacWhisper **corriendo en background**

## Instalación

```bash
# Clonar o navegar al repositorio
cd /path/to/Macwhisperapi

# Instalar dependencias
pip3 install -r requirements.txt
```

## Uso

### Iniciar el servidor

```bash
python3 src/server.py
```

El servidor iniciará en `http://localhost:3001`

### Endpoints

#### 1. POST /transcribe - Enviar archivo para transcripción

```bash
curl -X POST http://localhost:3001/transcribe \
  -F "file=@/path/to/audio.mp3"
```

**Respuesta**:
```json
{
  "success": true,
  "job_id": "abc123-def456-...",
  "status": "queued",
  "message": "Job queued for processing. Use GET /job/{job_id} to check status"
}
```

#### 2. GET /job/{job_id} - Consultar estado de transcripción

```bash
curl http://localhost:3001/job/abc123-def456-...
```

**Respuesta (procesando)**:
```json
{
  "success": true,
  "status": "processing",
  "job_id": "abc123-def456-...",
  "created_at": 1234567890.123,
  "started_at": 1234567892.456,
  "age": 5.3
}
```

**Respuesta (completado)**:
```json
{
  "success": true,
  "status": "completed",
  "job_id": "abc123-def456-...",
  "result": {
    "text": "Transcripción completa del audio...",
    "words": 150,
    "processing_time": 23.45,
    "audio_duration": 120.0,
    "rtf": 0.195,
    "format": "mp3",
    "file_size_mb": 2.5,
    "model": "MacWhisper (WhisperKit Pro / Whisper Large V3)",
    "job_id": "abc123-def456-..."
  },
  "processing_time": 23.45
}
```

#### 3. GET /queue - Estado de la cola

```bash
curl http://localhost:3001/queue
```

**Respuesta**:
```json
{
  "success": true,
  "queue_size": 2,
  "total_jobs": 5,
  "max_queue_size": 50,
  "max_concurrent_jobs": 2,
  "status_counts": {
    "pending": 2,
    "processing": 1,
    "completed": 2,
    "failed": 0,
    "timeout": 0
  }
}
```

#### 4. GET /health - Health check

```bash
curl http://localhost:3001/health
```

#### 5. GET /rate-limit - Rate limit status

```bash
curl http://localhost:3001/rate-limit
```

## Configuración

Edita `src/config.py` para ajustar:

- `PORT`: Puerto del servidor (default: 3001)
- `MAX_CONCURRENT_JOBS`: Máximo de transcripciones simultáneas (default: 2)
- `MAX_QUEUE_SIZE`: Tamaño máximo de la cola (default: 50)
- `JOB_TIMEOUT`: Timeout por job en segundos (default: 600)
- `RATE_LIMIT_PER_MINUTE`: Requests por minuto por IP (default: 10)
- `MAX_FILE_SIZE_MB`: Tamaño máximo de archivo (default: 500MB)

### Retención de Archivos

Por defecto, **todos los archivos se conservan** después de procesar:

- `KEEP_AUDIO_FILES`: True = conserva audios, False = los borra (default: **True**)
- `KEEP_TRANSCRIPTION_FILES`: True = conserva .txt, False = los borra (default: **True**)
- `ARCHIVE_FOLDER`: Carpeta donde se mueven los archivos procesados (default: `audio_archive/`)

Los archivos procesados se mueven automáticamente a `audio_archive/` para mantener organizado el folder `watched_input/`.

**Para borrar archivos después de procesar** (ahorrar espacio en disco):
```python
KEEP_AUDIO_FILES = False
KEEP_TRANSCRIPTION_FILES = False
```

## Comparación vs Parakeet MLX API

| Característica | Parakeet MLX API (Puerto 3000) | MacWhisper API (Puerto 3001) |
|----------------|-------------------------------|------------------------------|
| **Modelo** | Parakeet v3 (0.6B params) | WhisperKit Pro / Whisper Large V3 |
| **Velocidad** | 32x realtime (~25s para 13min) | Depende de MacWhisper |
| **Precisión** | Buena en español | Muy buena (modelos más grandes) |
| **VAD** | ✅ Silero VAD con métricas | ❌ No expuesto |
| **Streaming** | ✅ SSE real-time | ❌ Solo batch |
| **Queue System** | ❌ Sincrónico | ✅ Queue con job tracking |
| **Dependencias** | MLX, Parakeet MLX | MacWhisper App |
| **Setup** | Instalar paquetes Python | Configurar app GUI |

## Flujo de Datos

1. **Cliente** → `POST /transcribe` con archivo MP3
2. **API** → Valida archivo, crea job, retorna `job_id`
3. **API** → Copia archivo a `watched_input/{job_id}_filename.mp3`
4. **MacWhisper** → Detecta archivo nuevo automáticamente
5. **MacWhisper** → Transcribe en background
6. **MacWhisper** → Guarda `{job_id}_filename.txt` en el **mismo folder** (`watched_input/`)
7. **API** → Detecta archivo .txt (polling cada 0.5s)
8. **API** → Lee transcripción y actualiza job status a `completed`
9. **API** → Mueve archivos procesados (audio + .txt) a `audio_archive/` (configurable)
10. **Cliente** → `GET /job/{job_id}` → Obtiene transcripción completa

## Troubleshooting

### El job se queda en "processing" indefinidamente

- Verifica que MacWhisper esté corriendo
- Verifica que MacWhisper tenga configurado el watched folder correcto
- Verifica que "Auto-Transcribe" esté activado
- Revisa los logs de MacWhisper

### No se encuentra el archivo de output

- Verifica que MacWhisper tenga configurado "Output Location" como **"Same as source"**
- MacWhisper debe guardar el .txt en el mismo folder que el audio (`watched_input/`)
- Verifica que el archivo .txt tenga el mismo nombre base que el audio
- Revisa los logs de la API para ver si detecta el archivo .txt

### Rate limit exceeded

- Espera el tiempo especificado en `retry_after_seconds`
- O aumenta `RATE_LIMIT_PER_MINUTE` en config.py

### Queue is full

- Espera a que se procesen jobs existentes
- O aumenta `MAX_QUEUE_SIZE` en config.py

## Logs

Los logs se imprimen en stdout en formato JSON:

```json
{
  "timestamp": "2025-10-26T08:50:00.000Z",
  "level": "INFO",
  "message": "Job created and queued",
  "job_id": "abc123-def456-...",
  "filename": "test.mp3",
  "queue_size": 1
}
```

## Limitaciones

1. **No control de modelo**: Se usa el modelo configurado en MacWhisper UI
2. **No VAD metrics**: MacWhisper no expone información de detección de voz
3. **No streaming real**: MacWhisper procesa el archivo completo antes de guardar
4. **Dependencia externa**: Requiere MacWhisper corriendo en background
5. **Configuración manual**: Los watched folders deben configurarse en la GUI

## Licencia

Este proyecto es un wrapper para MacWhisper. MacWhisper Pro es software comercial de Goodsnooze.

## Soporte

Para issues con:
- **La API**: Reportar en este repositorio
- **MacWhisper**: Contactar support@macwhisper.com

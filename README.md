# MacWhisper Transcription API

API HTTP que utiliza MacWhisper (Watched Folders) para transcripción de audio, con sistema de colas robusto, auto-recovery y monitoreo de salud.

## Características

- **Queue System**: Cola de jobs con semaphore-based concurrency control
- **Job Tracking**: Cada transcripción tiene un UUID para consultar su estado
- **Auto-Retry**: Reintentos automáticos en timeout (máximo 2 reintentos)
- **Watchdog**: Detección y limpieza automática de jobs atascados
- **MacWhisper Monitor**: Auto-restart de MacWhisper cuando se detecta que está bloqueado
- **Rate Limiting**: Límite de requests por IP
- **Dynamic Timeout**: Timeout calculado según tamaño del archivo
- **File Logging**: Logs rotativos en `logs/api.log`
- **Multiple Formats**: Soporte para MP3, WAV, M4A, FLAC, OGG, Opus, WebM, AAC

## Arquitectura

```
Cliente HTTP
    ↓
POST /transcribe → Retorna job_id inmediatamente
    ↓
Archivo copiado a MacwhisperWatched/ con UUID en el nombre
    ↓
MacWhisper detecta y transcribe automáticamente
    ↓
MacWhisper guarda .txt en el MISMO folder
    ↓
API detecta resultado y lo asocia con job_id
    ↓
GET /job/{job_id} → Retorna transcripción
```

## Instalación Automática (Claude Code)

Si eres Claude Code instalando este proyecto en una nueva máquina:

```bash
# 1. Clonar repositorio
git clone https://github.com/[usuario]/macwhisper-transcription-api.git
cd macwhisper-transcription-api

# 2. Ejecutar instalación automática
./scripts/install.sh

# 3. Verificar que funciona
./scripts/test.sh
```

### Scripts Disponibles

| Script | Descripción |
|--------|-------------|
| `scripts/install.sh` | Instalación completa (dependencias + folders + daemon) |
| `scripts/update.sh` | Actualizar desde git y reiniciar servicio |
| `scripts/test.sh` | Ejecutar prueba de transcripción end-to-end |
| `scripts/install-daemon.sh` | Solo instalar/reinstalar el LaunchDaemon |

## Instalación Manual

### Requisitos Previos

1. **macOS** con Python 3.9+
2. **MacWhisper Pro** instalado y con licencia activa
3. **ffmpeg** para conversión de formatos (opus, ogg, webm → mp3)

```bash
# Instalar ffmpeg
brew install ffmpeg
```

### Pasos

```bash
# 1. Clonar repositorio
cd /Users/transcriptionserver
git clone https://github.com/[usuario]/macwhisper-transcription-api.git
cd macwhisper-transcription-api

# 2. Instalar dependencias
pip3 install --user -r requirements.txt

# 3. Crear carpetas necesarias
mkdir -p /Users/transcriptionserver/MacwhisperWatched
mkdir -p logs
mkdir -p audio_archive

# 4. Configurar MacWhisper (ver sección siguiente)

# 5. Iniciar servidor
python3 src/server.py
```

### Configuración de MacWhisper

**IMPORTANTE**: Antes de usar la API, configura MacWhisper:

1. Abre **MacWhisper**
2. Ve a **Settings** → **Watch Folders**
3. Clic en **"Add Watch Folder"**
4. Selecciona: `/Users/transcriptionserver/MacwhisperWatched`
5. Configura **Output Format**: `Plain Text (.txt)`
6. **CRÍTICO**: Configura **Output Location**: `Same as source`
7. Activa **"Auto-Transcribe Toggle"**
8. Mantén MacWhisper **corriendo en background**

## Endpoints

### POST /transcribe
Enviar archivo para transcripción.

```bash
# Modo asíncrono (retorna inmediatamente)
curl -X POST http://localhost:3001/transcribe \
  -F "file=@/path/to/audio.mp3"

# Modo síncrono (espera resultado)
curl -X POST "http://localhost:3001/transcribe?wait=true" \
  -F "file=@/path/to/audio.mp3"
```

### GET /job/{job_id}
Consultar estado de transcripción.

```bash
curl http://localhost:3001/job/{job_id}
```

### GET /jobs/history
Obtener historial de jobs.

```bash
curl http://localhost:3001/jobs/history
```

### GET /queue
Estado de la cola.

```bash
curl http://localhost:3001/queue
```

### GET /health
Health check del servicio.

```bash
curl http://localhost:3001/health
```

### POST /admin/cleanup-stuck
Limpiar jobs atascados manualmente.

```bash
curl -X POST http://localhost:3001/admin/cleanup-stuck
```

### POST /admin/restart-macwhisper
Reiniciar MacWhisper manualmente.

```bash
curl -X POST http://localhost:3001/admin/restart-macwhisper
```

## Configuración

Edita `src/config.py`:

| Variable | Default | Descripción |
|----------|---------|-------------|
| `PORT` | 3001 | Puerto del servidor |
| `MAX_CONCURRENT_JOBS` | 1 | Transcripciones simultáneas |
| `MAX_QUEUE_SIZE` | 50 | Tamaño máximo de cola |
| `MIN_JOB_TIMEOUT` | 60 | Timeout mínimo (1 minuto) |
| `JOB_TIMEOUT` | 60 | Timeout base (segundos) |
| `JOB_TIMEOUT_PER_MB` | 30 | Segundos extra por MB |
| `MAX_JOB_TIMEOUT` | 600 | Timeout máximo (10 min) |
| `MAX_RETRIES` | 2 | Reintentos en timeout |
| `RATE_LIMIT_PER_MINUTE` | 10 | Requests/min por IP |
| `MAX_FILE_SIZE_MB` | 500 | Tamaño máximo de archivo |
| `KEEP_AUDIO_FILES` | True | Conservar audios procesados |
| `KEEP_TRANSCRIPTION_FILES` | True | Conservar .txt procesados |

### Conversión Automática de Formatos

MacWhisper watched folders solo detectan ciertos formatos (mp3, m4a, wav, flac).
La API convierte automáticamente formatos no soportados:

| Formato Original | Acción |
|-----------------|--------|
| mp3, m4a, wav, flac, aiff | Copia directa |
| opus, ogg, webm, wma, amr, aac | Conversión a MP3 (requiere ffmpeg) |

## LaunchDaemon (Auto-start)

Para que el servidor inicie automáticamente:

```bash
# Instalar daemon
./scripts/install-daemon.sh

# O manualmente:
sudo cp scripts/com.transcriptionserver.macwhisper-api.plist /Library/LaunchDaemons/
sudo launchctl load /Library/LaunchDaemons/com.transcriptionserver.macwhisper-api.plist
```

### Comandos del Daemon

```bash
# Ver status
sudo launchctl list | grep macwhisper

# Reiniciar
sudo launchctl unload /Library/LaunchDaemons/com.transcriptionserver.macwhisper-api.plist
sudo launchctl load /Library/LaunchDaemons/com.transcriptionserver.macwhisper-api.plist

# Detener
sudo launchctl unload /Library/LaunchDaemons/com.transcriptionserver.macwhisper-api.plist

# Ver logs
tail -f /Users/transcriptionserver/macwhisper-transcription-api/logs/api.log
```

## Features de Robustez

### Watchdog Task
Cada 60 segundos verifica:
- Jobs en PROCESSING por más de 30 minutos → los marca como TIMEOUT
- Salud de MacWhisper → reinicia si hay 3 fallos consecutivos

### MacWhisper Monitor
- Detecta si MacWhisper dejó de procesar archivos
- Reinicia automáticamente MacWhisper via AppleScript
- Máximo 3 reinicios por hora para evitar loops

### Auto-Retry
- Jobs con timeout se reintentan automáticamente
- Reset completo de timestamps para evitar tiempos negativos
- Máximo 2 reintentos por job

## Troubleshooting

### El job se queda en "processing" indefinidamente
1. El watchdog debería detectarlo después de 30 min
2. Puedes forzar limpieza: `curl -X POST http://localhost:3001/admin/cleanup-stuck`
3. Verifica que MacWhisper esté corriendo

### MacWhisper no procesa archivos
1. El sistema intentará reiniciarlo automáticamente
2. Puedes forzar reinicio: `curl -X POST http://localhost:3001/admin/restart-macwhisper`
3. Verifica configuración de Watch Folders en MacWhisper

### Puerto 3001 ya en uso
```bash
# Encontrar proceso
lsof -ti:3001

# Si es el daemon, usar launchctl
sudo launchctl unload /Library/LaunchDaemons/com.transcriptionserver.macwhisper-api.plist
```

### Tiempos de procesamiento negativos
Este bug fue corregido. Si aparece, actualiza el código:
```bash
./scripts/update.sh
```

## Logs

Los logs se guardan en `logs/api.log` con rotación automática:
- Máximo 10 MB por archivo
- Mantiene últimos 7 archivos

```bash
# Ver logs en tiempo real
tail -f logs/api.log

# Buscar errores
grep -i error logs/api.log
```

## Desarrollo

### Estructura del Proyecto

```
macwhisper-transcription-api/
├── src/
│   ├── server.py          # Servidor principal + watchdog + monitor
│   ├── config.py          # Configuración
│   ├── queue_manager.py   # Sistema de colas
│   ├── file_watcher.py    # Detección de transcripciones
│   └── logger.py          # Logging estructurado
├── scripts/
│   ├── install.sh         # Instalación automática
│   ├── update.sh          # Actualización
│   ├── test.sh            # Pruebas
│   └── install-daemon.sh  # Instalar LaunchDaemon
├── logs/                  # Logs del servidor
├── audio_archive/         # Archivos procesados
└── requirements.txt
```

### Ejecutar en Desarrollo

```bash
# Sin daemon
python3 src/server.py

# Ver logs en otra terminal
tail -f logs/api.log
```

## Licencia

Este proyecto es un wrapper para MacWhisper. MacWhisper Pro es software comercial de Goodsnooze.

## Soporte

- **Issues con la API**: Reportar en este repositorio
- **Issues con MacWhisper**: support@macwhisper.com

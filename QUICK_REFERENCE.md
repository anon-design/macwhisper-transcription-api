# MacWhisper API - Guía de Referencia Rápida

**Para consultas rápidas y troubleshooting**

---

## Acceso por Tailscale

```bash
# Mac Mini
http://100.82.167.27:3001/health

# M1 Pro
http://100.75.165.64:3001/health
```

---

## Timeouts Dinámicos

### Fórmula
```
Timeout = 15s + (MB × 30s)
Máximo: 600s (10 minutos)
```

### Tabla de Referencia
| Audio | MB | Timeout |
|-------|----|---------|
| 1 min | 0.1 | 18s |
| 10 min | 1 | 45s |
| 30 min | 3 | 105s |
| 1 hora | 6 | 195s |
| 2 horas | 12 | 375s |
| 5+ horas | 30+ | 600s (max) |

---

## Endpoints Principales

```bash
# Health
curl http://100.75.165.64:3001/health

# Transcribir (esperar resultado)
curl -X POST "http://100.75.165.64:3001/transcribe?wait=true" \
  -F "file=@audio.mp3"

# Transcribir (asíncrono)
curl -X POST http://100.75.165.64:3001/transcribe \
  -F "file=@audio.mp3"

# Ver job
curl http://100.75.165.64:3001/job/{job_id}

# Cola
curl http://100.75.165.64:3001/queue

# Logs
tail -f /Users/JC/macwhisper-transcription-api/logs/api.log
```

---

## Instalación Nueva

```bash
# 1. Clonar
git clone https://github.com/[usuario]/macwhisper-transcription-api.git
cd macwhisper-transcription-api

# 2. Requisitos
pip install -r requirements.txt

# 3. Configurar (editar src/config.py)
# WATCHED_INPUT_DIR = /Users/[username]/MacwhisperWatched

# 4. Crear folder
mkdir -p /Users/[username]/MacwhisperWatched

# 5. MacWhisper Settings
# Watch Folders → /Users/[username]/MacwhisperWatched
# Auto-Transcribe: ON
# Output Location: Same as source
# Output Format: Plain Text

# 6. LaunchAgent
./scripts/install-daemon.sh

# 7. Verificar
curl http://localhost:3001/health
```

---

## Cambiar Timeouts

### En Cliente (Mediclic)

```typescript
// server/services/transcriptionService.ts
const baseTimeout = 15000;      // ← cambiar
const timeoutPerMb = 30000;     // ← cambiar
const maxTimeout = 600000;      // ← cambiar
```

### En Servidor

```python
# src/config.py
MIN_JOB_TIMEOUT = 30       # 30s mínimo (cold start + archivos cortos)
JOB_TIMEOUT = 20           # Base timeout
JOB_TIMEOUT_PER_MB = 25    # 25s por MB
MAX_JOB_TIMEOUT = 540      # 9 min máximo
```

Después: `launchctl reload ~/Library/LaunchAgents/com.macwhisper.api.plist`

---

## Troubleshooting

### API no responde
```bash
ps aux | grep server.py
curl http://localhost:3001/health
launchctl list | grep macwhisper
```

### MacWhisper no procesa
```bash
# Verificar running
ps aux | grep MacWhisper

# Verificar settings
# MacWhisper → Settings → Watch Folders
# ¿Auto-Transcribe: ON?

# Verificar folder
ls -la /Users/JC/MacwhisperWatched/

# Verificar permisos
chmod 755 /Users/JC/MacwhisperWatched
```

### Timeout muy bajo
```python
# Aumentar en src/config.py
MIN_JOB_TIMEOUT = 30  # Subir de 20
JOB_TIMEOUT = 30      # Subir de 20
```

### Muchos timeouts
```bash
# Ver logs
grep -i timeout logs/api.log | tail -20

# Aumentar timeouts si es patrón
# Ver sección "Cambiar Timeouts"
```

---

## Performance Esperado

| Servidor | 0.1 MB | 1 MB | 6 MB | 225 MB |
|----------|--------|------|------|--------|
| Mac Mini | 1-2s | 1-2s | 3-5s | 96s |
| M1 Pro | 2-3s | 2-3s | 5-10s | 251s |

---

## Logs Útiles

```bash
# Seguir en tiempo real
tail -f logs/api.log

# Buscar errors
grep ERROR logs/api.log

# Buscar timeouts
grep -i timeout logs/api.log

# Ver qué se procesó
grep "Processing complete" logs/api.log

# Ver orphaned files
grep -i orphaned logs/api.log
```

---

## Git Workflow

```bash
# Actualizar
git pull origin main

# Cambios locales
git status

# Ver qué cambió
git diff

# Commit
git add .
git commit -m "fix: description"
git push origin main
```

---

## Database (Mediclic)

```sql
-- Ver timeouts actuales
SELECT server_type, transcription_timeout_ms
FROM transcription_servers;

-- Actualizar
UPDATE transcription_servers
SET transcription_timeout_ms = 15000
WHERE server_type = 'macwhisper';
```

---

## Verificación Rápida

### ¿Todo OK?
```bash
# 1. Health checks
curl http://100.82.167.27:3001/health  # Mac Mini
curl http://100.75.165.64:3001/health  # M1 Pro

# 2. MacWhisper corriendo
ps aux | grep MacWhisper

# 3. Watch folders existen
ls -la /Users/JC/MacwhisperWatched
ls -la /Users/[username]/MacwhisperWatched

# 4. Logs sin errores
tail -20 logs/api.log | grep -i error

# 5. Conexión Tailscale
tailscale ip
```

---

## Contactos & Escalada

| Problema | Acción |
|----------|--------|
| API offline | Restart: `launchctl reload ...plist` |
| MacWhisper offline | Restart: `Cmd+Q` → abrir |
| Timeout muy bajo | Aumentar `MIN_JOB_TIMEOUT` |
| Timeout muy alto | Reducir (mejor respuesta) |
| DB desincronizada | Actualizar `transcription_timeout_ms` |
| Failover frecuente a Groq | Revisar logs, aumentar timeouts |
| Cold start lento | Normal en primera transcripción |

---

## Commits Importantes

```
919d3e9 - feat(transcription): add dynamic timeout based on file size
23996f6 - feat: support long audio files with dynamic timeout
[move commit] - move API from /private/tmp to /Users/JC
```

Ver en: https://github.com/[usuario]/macwhisper-transcription-api/commits

---

## URLs Importantes

```
GitHub API: https://github.com/[usuario]/macwhisper-transcription-api
GitHub Mediclic: https://github.com/[usuario]/Mediclic
Mediclic App: https://app.mediclic.org
```

---

**Última actualización:** Diciembre 26, 2025
**Mantener actualizado cuando cambie**

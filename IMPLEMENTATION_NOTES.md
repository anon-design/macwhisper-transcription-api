# MacWhisper Transcription API - Notas de Implementación

## Documento de Referencia Técnica
**Fecha:** Diciembre 26, 2025
**Versión:** 1.0
**Estado:** Producción (Mac Mini + M1 Pro)

---

## 1. RESUMEN EJECUTIVO

Se implementó un sistema de transcripción de audio distribuido con dos servidores MacWhisper (Mac Mini y MacBook M1 Pro) usando **timeouts dinámicos sincronizados** con el cliente Mediclic backend. El problema principal era que los timeouts estaban desalineados entre cliente y servidores, causando failovers innecesarios a Groq (servicio cloud caro).

**Problema resuelto:** Cliente esperaba 10s, servidores tardaban 60-120s → Solución: timeouts dinámicos basados en tamaño de archivo.

---

## 2. PROBLEMAS IDENTIFICADOS

### 2.1 Timeout Desalineado (Raíz del Problema)

**Antes:**
- Cliente (Mediclic): timeout fijo 10,000ms (10 segundos)
- Mac Mini API: timeout fijo 60,000ms (60 segundos)
- Resultado: Cliente abandonaba requests que todavía estaban siendo procesadas

**Impacto:**
- Failovers frecuentes a Groq (costo $$$)
- Mala experiencia de usuario (transcripciones tardaban)
- Carga innecesaria en servicio cloud

### 2.2 Falta de Soporte para Archivos Largos

MacWhisper no tenía configuración para:
- Audio > 10 minutos
- Cálculo de timeout basado en tamaño
- Escalabilidad a archivos de 4+ horas

### 2.3 Inconsistencias de Instalación

- **Mac Mini:** Ubicación persistente + configuración establecida
- **M1 Pro:** Instalación en `/private/tmp/` (temporal) → No persistente
- Rutas hardcodeadas en lugar de variables
- Falta de sincronización de cambios entre repositorios

---

## 3. SOLUCIONES IMPLEMENTADAS

### 3.1 Timeouts Dinámicos Sincronizados

#### Fórmula Cliente (Mediclic backend)
```
Timeout = base (15s) + (file_size_mb × 30s/MB)
Máximo: 600s (10 minutos)

Ejemplos:
- 0.1 MB (1 min audio):    15 + 3 = 18s
- 1 MB (10 min audio):     15 + 30 = 45s
- 3 MB (30 min audio):     15 + 90 = 105s
- 6 MB (1 hora audio):     15 + 180 = 195s
- 30 MB (5+ horas):        15 + 900 = 915s → capped a 600s
```

#### Fórmula API (MacWhisper)
```
Timeout = base (12s) + (file_size_mb × 25s/MB)
Máximo: 540s (9 minutos)

Ejemplos:
- 0.1 MB:  12 + 2.5 = 14.5s
- 1 MB:    12 + 25 = 37s
- 3 MB:    12 + 75 = 87s
- 6 MB:    12 + 150 = 162s
- 30 MB:   12 + 750 = 762s → capped a 540s
```

**Justificación:**
- API timeout ~10% menor que cliente para graceful failover
- Cliente abandona request → API retorna error → cliente hace failover
- API nunca mata request mientras cliente aún espera

### 3.2 Cambios en Código Cliente (Mediclic)

**Archivo:** `server/services/transcriptionService.ts`

```typescript
private calculateDynamicTimeout(
  audioBuffer: Buffer,
  serverBaseTimeout: number
): number {
  const fileSizeMb = audioBuffer.length / (1024 * 1024);
  const baseTimeout = serverBaseTimeout || 15000; // 15s base
  const timeoutPerMb = 30000; // 30s por MB
  const maxTimeout = 600000; // 10 min máximo

  const calculatedTimeout = baseTimeout + (fileSizeMb * timeoutPerMb);
  const finalTimeout = Math.min(calculatedTimeout, maxTimeout);

  console.log(`📊 Dynamic timeout: ${(finalTimeout / 1000).toFixed(1)}s for ${fileSizeMb.toFixed(2)}MB file`);
  return finalTimeout;
}
```

**Cambio en llamada a API:**
```typescript
// Antes: fixed timeout
const result = await this.transcribeWithMacWhisper(audioBuffer, server.transcriptionTimeoutMs);

// Después: dynamic timeout
const dynamicTimeout = this.calculateDynamicTimeout(audioBuffer, server.transcriptionTimeoutMs);
const result = await this.transcribeWithMacWhisper(audioBuffer, dynamicTimeout);
```

### 3.3 Cambios en Servidores MacWhisper

**Archivo:** `src/config.py`

```python
# Antes (fijo):
JOB_TIMEOUT = 60  # 60 segundos para todo

# Después (dinámico):
MIN_JOB_TIMEOUT = 20  # 20s mínimo (evita timeouts en archivos pequeños)
JOB_TIMEOUT = 20      # Base timeout
JOB_TIMEOUT_PER_MB = 25  # 25s por MB
MAX_JOB_TIMEOUT = 540 # 9 minutos máximo
MAX_RETRIES = 0       # Sin reintentos (cliente hace failover)
```

**Cambio clave:** Función `calculate_dynamic_timeout()` en `monitoring.py`

```python
def calculate_dynamic_timeout(file_size_mb: float) -> int:
    """
    Calcula timeout dinámico basado en tamaño del archivo.
    Sincronizado con cliente (Mediclic backend).
    """
    base_timeout = config.JOB_TIMEOUT
    extra_time = file_size_mb * config.JOB_TIMEOUT_PER_MB
    timeout = int(base_timeout + extra_time)

    # Asegurar mínimo
    timeout = max(timeout, config.MIN_JOB_TIMEOUT)

    # No exceder máximo
    return min(timeout, config.MAX_JOB_TIMEOUT)
```

### 3.4 Actualización de Base de Datos (Production)

```sql
-- Sincronizar timeouts en BD con nuevos valores
UPDATE transcription_servers
SET transcription_timeout_ms = 15000
WHERE server_type = 'macwhisper';

UPDATE transcription_servers
SET transcription_timeout_ms = 30000
WHERE server_type = 'groq';

-- Verificar cambios
SELECT id, name, server_type, transcription_timeout_ms
FROM transcription_servers
ORDER BY priority;
```

### 3.5 Infraestructura (MacBook M1 Pro)

**Problema:** API instalada en `/private/tmp/` (temporal)

**Solución:**
1. Mover API a ubicación persistente: `/Users/JC/macwhisper-transcription-api`
2. Instalar como LaunchAgent (auto-start)
3. Configurar Tailscale para acceso remoto

**IP Tailscale:**
```
Mac Mini: 100.82.167.27:3001
M1 Pro:   100.75.165.64:3001
```

**LaunchAgent (M1 Pro):**
```bash
Location: ~/Library/LaunchAgents/com.macwhisper.api.plist
Status: Active (PID 33144)
Port: 3001 (listening on *:3001)
```

---

## 4. ARQUITECTURA FINAL

```
┌─────────────────────────────────────────────────────────────┐
│                     Mediclic Backend                         │
│  (Express + TS, dynamic timeout calculator)                  │
└──────────┬──────────────────────────────────────────────────┘
           │
           │ POST /transcribe?wait=true
           │ Content-Type: multipart/form-data
           │ Timeout: calculateDynamicTimeout(file_size)
           │
    ┌──────┴──────┬────────────────────────┐
    │             │                        │
    v             v                        v
┌────────────┐ ┌────────────┐       ┌──────────────┐
│  Mac Mini  │ │   M1 Pro   │       │  Groq Cloud  │
│100.82.167. │ │100.75.165. │       │ (Failover)   │
│     27:300 │ │     64:300 │       │              │
│     1      │ │      1     │       │              │
└─────┬──────┘ └────────────┘       └──────────────┘
      │
      ├─ ffmpeg conversion (opus→mp3)
      ├─ Copy to watched folder
      ├─ Poll for .txt output
      ├─ Dynamic timeout: 20s + (MB × 25s)
      └─ Max 540s (9 minutos)
```

---

## 5. RESULTADOS DE TESTS

### Test Summary

| Test | Servidor | Audio | Resultado | Tiempo |
|------|----------|-------|-----------|--------|
| 1 | Mac Mini | Corto (voz) | ✅ PASS | 1.64s |
| 2 | M1 Pro | Corto (voz) | ✅ PASS | 2.02s |
| 3 | Mac Mini | 4.1 horas (225MB) | ✅ PASS | 96.57s |
| 4 | M1 Pro | 4.1 horas (225MB) | ✅ PASS | 251.09s |

### Performance Insights

**Velocidad de procesamiento:**
- Mac Mini: ~92x velocidad real-time (4h en 96s)
- M1 Pro: ~59x velocidad real-time (4h en 251s)
- Ambos dentro de límites: 540s (9 min) máximo

**Cold Start:** Primera transcripción en M1 Pro tarda ~25s (calentamiento), posteriores son rápidas (~2s)

---

## 6. CÓMO ACCEDER Y USAR

### 6.1 Endpoints Principales

```bash
# Health Check
curl http://100.75.165.64:3001/health

# Transcribir (asíncrono)
curl -X POST http://100.75.165.64:3001/transcribe \
  -F "file=@audio.mp3"
# Respuesta: {"job_id": "uuid", "status": "pending"}

# Transcribir (síncrono - espera resultado)
curl -X POST "http://100.75.165.64:3001/transcribe?wait=true" \
  -F "file=@audio.mp3" \
  --max-time 600  # Timeout según tamaño del archivo
# Respuesta: {"success": true, "result": {"text": "...", "processing_time": 2.02}}

# Consultar estado de job
curl http://100.75.165.64:3001/job/{job_id}

# Historial de jobs
curl http://100.75.165.64:3001/jobs/history

# Cola de transcripciones
curl http://100.75.165.64:3001/queue
```

### 6.2 GitHub & Deployment

**Repository:**
```
https://github.com/[usuario]/macwhisper-transcription-api
```

**Instalación en nueva máquina:**
```bash
# 1. Clonar
git clone https://github.com/[usuario]/macwhisper-transcription-api.git
cd macwhisper-transcription-api

# 2. Actualizar
git pull origin main

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Configurar (ver sección 7)
# Editar src/config.py con rutas locales

# 5. Crear watch folder
mkdir -p /Users/[username]/MacwhisperWatched

# 6. Configurar MacWhisper (Manual)
#    Settings → Watch Folders → Add /Users/[username]/MacwhisperWatched
#    Auto-Transcribe: ON
#    Output Location: Same as source
#    Output Format: Plain Text (.txt)

# 7. Instalar como LaunchAgent
./scripts/install-daemon.sh

# 8. Verificar
curl http://localhost:3001/health
```

### 6.3 Actualizar Timeouts

**En cliente (Mediclic):**
```typescript
// server/services/transcriptionService.ts
const baseTimeout = 15000;      // Cambiar aquí
const timeoutPerMb = 30000;     // O aquí
const maxTimeout = 600000;      // O aquí
```

**En servidores MacWhisper:**
```python
# src/config.py
MIN_JOB_TIMEOUT = 20       # Cambiar aquí
JOB_TIMEOUT = 20           # O aquí
JOB_TIMEOUT_PER_MB = 25    # O aquí
MAX_JOB_TIMEOUT = 540      # O aquí
```

**Después de cambios:**
```bash
# Servidores
sudo launchctl unload /Library/LaunchAgents/com.macwhisper.api.plist
sudo launchctl load /Library/LaunchAgents/com.macwhisper.api.plist

# Cliente
npm run build && npm run start
```

---

## 7. LÓGICA DETRÁS DE LAS DECISIONES

### 7.1 ¿Por qué timeouts dinámicos?

**Alternativas consideradas:**
1. Timeout global fijo (10s) → ✗ Falla con archivos > 1MB
2. Timeout global alto (600s) → ✗ Espera innecesaria en archivos pequeños
3. **Timeouts dinámicos** → ✅ Adapta a cada archivo

**Fórmula elegida:** Lineal (base + factor × MB)
- Previsible y matemática
- Fácil de sintonizar
- Refleja realidad: más contenido = más tiempo

### 7.2 ¿Por qué MAX_RETRIES = 0?

**Razonamiento:**
- Cliente ya tiene failover (Mac Mini → M1 Pro → Groq)
- Reintentos internos solo agregan latencia
- Es mejor fallar rápido y dejar que cliente haga failover
- Groq es el destino final (cloud, confiable pero caro)

### 7.3 ¿Por qué API timeout 10% menor que cliente?

**Objetivo:** Graceful degradation

```
Escenario:
1. Cliente: timeout 45s (para 1MB)
2. API: timeout 37s (10% menos)
3. Resultado: API falla primero → retorna error
4. Cliente recibe error → hace failover a M1 Pro/Groq
5. NUNCA: API sigue procesando mientras cliente espera timeout
```

### 7.4 ¿Por qué MIN_JOB_TIMEOUT = 20s en M1 Pro?

**Problema:** Archivos pequeños causaban timeout aunque se completaban

**Causa:** MacWhisper tardaba ~15-20s en "calentar" (cargar modelo en memoria)

**Solución:** Aumentar MIN_JOB_TIMEOUT para dar margen

**En Mac Mini:** Menos problema porque MacWhisper suele estar más activo

---

## 8. TROUBLESHOOTING & DIAGNOSTICS

### 8.1 "Timeout waiting for result after Xs"

**Causa probable:** MacWhisper no está procesando o tardó más del timeout

**Solución:**
```bash
# Verificar MacWhisper corriendo
ps aux | grep MacWhisper

# Verificar watch folder tiene permisos
ls -la /Users/JC/MacwhisperWatched

# Aumentar timeout (en config.py)
MIN_JOB_TIMEOUT = 25  # Subir de 20

# Reiniciar
launchctl unload ~/Library/LaunchAgents/com.macwhisper.api.plist
launchctl load ~/Library/LaunchAgents/com.macwhisper.api.plist

# Verificar logs
tail -f logs/api.log
```

### 8.2 "MacWhisper health: degraded"

**Causa probable:** Archivos huérfanos sin .txt correspondiente

**Solución:**
```bash
# Ver qué archivos están huérfanos
curl http://localhost:3001/health | grep orphaned_files

# Limpiar manualmente
curl -X POST http://localhost:3001/admin/cleanup-stuck

# Ver logs para más detalles
grep "orphaned" logs/api.log
```

### 8.3 "API no responde desde Tailscale"

**Verificar:**
```bash
# 1. API corriendo localmente?
curl http://localhost:3001/health

# 2. Tailscale conectado?
tailscale ip

# 3. IP correcta?
# Mac Mini: 100.82.167.27:3001
# M1 Pro: 100.75.165.64:3001

# 4. Firewall bloqueando?
lsof -i :3001  # Ver qué está escuchando puerto 3001

# 5. API escuchando en 0.0.0.0?
# En config.py: HOST = "0.0.0.0"
```

---

## 9. CAMBIOS A FUTURO

### 9.1 Posibles Optimizaciones

1. **GPU Acceleration:** Usar GPU específica en M1 Pro si está disponible
2. **Model Caching:** Pre-cargar modelo en MacWhisper para evitar cold start
3. **Batch Processing:** Procesar múltiples archivos en paralelo (agregar más MAX_CONCURRENT_JOBS)
4. **Metrics:** Agregar Prometheus/Grafana para monitoreo
5. **Circuit Breaker:** Si Mac Mini falla 3 veces, saltarse y ir directo a M1 Pro

### 9.2 Cambios Recomendados si hay Problemas

```python
# Si M1 Pro sigue siendo lento:
MIN_JOB_TIMEOUT = 30  # Aumentar aún más
JOB_TIMEOUT_PER_MB = 30  # Más tiempo por MB

# Si hay muchos timeouts en cliente:
# (en Mediclic backend)
baseTimeout = 20000  # Subir de 15s
timeoutPerMb = 35000  # Subir de 30s/MB
```

---

## 10. REFERENCIAS & COMMITS

**Commits principales:**

```
Mediclic:
- 919d3e9 feat(transcription): add dynamic timeout based on file size

MacWhisper API:
- 23996f6 feat: support long audio files with dynamic timeout
- [move to persistent location] move from /private/tmp to /Users/JC
```

**Archivos modificados:**

```
Mediclic:
  server/services/transcriptionService.ts
  src/config.ts (DB: transcription_servers.transcription_timeout_ms)

MacWhisper:
  src/config.py (timeouts dinámicos)
  src/monitoring.py (calculate_dynamic_timeout function)
  src/server.py (use dynamic timeout in transcription)
```

---

## 11. CHECKLIST PARA FUTURO

- [ ] Ambos servidores saludables (health check OK)
- [ ] MacWhisper tiene Watch Folders configurados
- [ ] Timeouts en BD sincronizados con código
- [ ] Tests periódicos con archivos pequeños y grandes
- [ ] Monitorear logs para "orphaned files"
- [ ] Revisar CPU/Memory usage de MacWhisper
- [ ] Actualizar documento si hay cambios significativos

---

**Documento creado:** Diciembre 26, 2025
**Próxima revisión:** Enero 2026
**Responsable:** Sistema Mediclic
